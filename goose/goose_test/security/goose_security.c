#define _GNU_SOURCE
#define OPENSSL_SUPPRESS_DEPRECATED
#include "goose_security.h"
#include "goose_log.h"
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/x509v3.h>
#include <openssl/ec.h>
#include <openssl/kdf.h>
#include <openssl/rand.h>
#include <openssl/err.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

struct GooseSecurity {
    EVP_PKEY *identity;
    X509 *certificate, *peer_cert;
    X509_STORE *trust;
    STACK_OF(X509) *issuers;
    uint16_t appid;
    uint8_t destination[6];
    char reference[130];
    uint8_t key[16], hello_hash[32], ack[GSEC_MAX_HANDSHAKE];
    size_t ack_length;
    uint32_t peer_ip, last_st, last_sq;
    int established, replay_valid, first_frame;
    struct timespec last_activity;
    uint64_t accepted, rejected;
    time_t credentials_checked;
    int credentials_valid, last_cert_error;
};

static int reject(GooseSecurity *s, const char *reason)
{
    s->rejected++;
    /* Log first failures and aggregate persistent floods without per-packet disk I/O. */
    if (s->rejected <= 10 || s->rejected % 1000 == 0)
        GLOG("WARNING", "GOOSE rejected: %s accepted=%llu rejected=%llu last_cert_error=%d", reason,
             (unsigned long long)s->accepted, (unsigned long long)s->rejected, s->last_cert_error);
    ERR_clear_error();
    return -1;
}

static BIO *read_pki(int directory, const char *name, int private)
{
    int fd = openat(directory, name, O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    struct stat info;
    if (fd < 0) return NULL;
    if (fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_size <= 0 ||
        info.st_size > 1024*1024 || info.st_uid != geteuid() ||
        (info.st_mode & (private ? 0077 : 0022))) {
        close(fd); return NULL;
    }
    BIO *bio = BIO_new_fd(fd, BIO_CLOSE);
    if (!bio) close(fd);
    return bio;
}

static int p256(EVP_PKEY *key)
{
    if (!key || EVP_PKEY_base_id(key) != EVP_PKEY_EC) return 0;
    EC_KEY *ec = EVP_PKEY_get1_EC_KEY(key);
    int valid = ec && EC_GROUP_get_curve_name(EC_KEY_get0_group(ec)) == NID_X9_62_prime256v1 &&
                EC_KEY_check_key(ec) == 1;
    EC_KEY_free(ec);
    return valid;
}

static int verify_cert(GooseSecurity *s, X509 *certificate)
{
    int ok = 0;
    X509_STORE_CTX *ctx = X509_STORE_CTX_new();
    EVP_PKEY *public = X509_get_pubkey(certificate);
    ASN1_BIT_STRING *usage = X509_get_ext_d2i(certificate, NID_key_usage, NULL, NULL);
    if (ctx && p256(public) && X509_check_ca(certificate) == 0 && usage &&
        ASN1_BIT_STRING_get_bit(usage, 0) &&
        X509_STORE_CTX_init(ctx, s->trust, certificate, s->issuers) == 1) {
        X509_STORE_CTX_set_depth(ctx, 8);
        ok = X509_verify_cert(ctx) == 1;
        s->last_cert_error = X509_STORE_CTX_get_error(ctx);
    }
    ASN1_BIT_STRING_free(usage);
    EVP_PKEY_free(public);
    X509_STORE_CTX_free(ctx);
    return ok;
}

GooseSecurity *gsec_create(const char *directory, uint16_t appid,
                          const uint8_t destination[6], const char *reference)
{
    GooseSecurity *s = calloc(1, sizeof(*s));
    BIO *bio = NULL;
    int fd = -1, ok = 0;
    if (!s || !reference || strlen(reference) >= sizeof(s->reference)) goto out;
    /* current is an atomic generation link owned by the PKI manager. Pin its inode
     * once so a concurrent import cannot mix keys, roots and CRLs. */
    int parent = open(directory, O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
    struct stat info;
    if (parent < 0) goto out;
    if (fstat(parent, &info) || info.st_uid != geteuid() || (info.st_mode & 0022)) {
        close(parent); goto out;
    }
    fd = openat(parent, "current", O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    close(parent);
    if (fd < 0 || fstat(fd, &info) || info.st_uid != geteuid() || (info.st_mode & 0022)) goto out;
    s->trust = X509_STORE_new();
    s->issuers = sk_X509_new_null();
    if (!s->trust || !s->issuers) goto out;
    bio = read_pki(fd, "ca-roots.crt", 0);
    if (!bio) goto out;
    X509 *root;
    int roots = 0;
    while ((root = PEM_read_bio_X509(bio, NULL, NULL, NULL))) {
        int added = X509_STORE_add_cert(s->trust, root);
        X509_free(root);
        if (added != 1) goto out;
        roots++;
    }
    BIO_free(bio); bio = NULL; ERR_clear_error();
    if (!roots) goto out;
    bio = read_pki(fd, "crls.pem", 0);
    if (!bio) goto out;
    /* CRL bundle may contain intermediate issuer certificates, as in TLS store. */
    STACK_OF(X509_INFO) *items = PEM_X509_INFO_read_bio(bio, NULL, NULL, NULL);
    if (!items) goto out;
    int lists = 0, loaded = 1;
    for (int i = 0; i < sk_X509_INFO_num(items); i++) {
        X509_INFO *item = sk_X509_INFO_value(items, i);
        if (item->crl) {
            if (X509_STORE_add_crl(s->trust, item->crl) != 1) loaded = 0;
            lists++;
        }
        /* Chain-building candidates only; never promote these to trust anchors. */
        if (item->x509) {
            if (X509_up_ref(item->x509) != 1) loaded = 0;
            else if (!sk_X509_push(s->issuers, item->x509)) {
                X509_free(item->x509); loaded = 0;
            }
        }
    }
    sk_X509_INFO_pop_free(items, X509_INFO_free);
    BIO_free(bio); bio = NULL;
    if (!loaded || !lists || X509_STORE_set_flags(s->trust, X509_V_FLAG_CRL_CHECK |
            X509_V_FLAG_CRL_CHECK_ALL | X509_V_FLAG_X509_STRICT) != 1) goto out;
    bio = read_pki(fd, "enc.crt", 0);
    if (!bio) goto out;
    s->certificate = PEM_read_bio_X509(bio, NULL, NULL, NULL);
    X509 *issuer;
    while ((issuer = PEM_read_bio_X509(bio, NULL, NULL, NULL))) {
        if (!sk_X509_push(s->issuers, issuer)) { X509_free(issuer); goto out; }
    }
    ERR_clear_error();
    BIO_free(bio); bio = NULL;
    bio = read_pki(fd, "enc.key", 1);
    if (!bio) goto out;
    /* Explicit empty password prevents an interactive prompt on encrypted/unknown input. */
    s->identity = PEM_read_bio_PrivateKey(bio, NULL, NULL, "");
    BIO_free(bio); bio = NULL;
    if (!s->certificate || !p256(s->identity) ||
        X509_check_private_key(s->certificate, s->identity) != 1 ||
        !verify_cert(s, s->certificate)) goto out;
    int der = i2d_X509(s->certificate, NULL);
    /* 126 B TLV overhead/fields, <=72 B ECDSA signature, 65+32 byte ephemeral parameters. */
    if (der <= 0 || der + 3*7 + 5+1+2+65+32+72 > GSEC_MAX_HANDSHAKE) goto out;
    s->appid = appid;
    memcpy(s->destination, destination, 6);
    strcpy(s->reference, reference);
    GLOG("INFO", "GOOSE PKI loaded: P-256 identity, CA root, CRL; APPID=0x%04x stream=%s", appid, reference);
    ok = 1;
out:
    BIO_free(bio);
    if (fd >= 0) close(fd);
    if (!ok) {
        GLOG("ERROR", "GOOSE PKI initialization failed certificate_error=%d openssl_error=%lu; no plaintext fallback",
             s ? s->last_cert_error : -1, ERR_peek_last_error());
        gsec_destroy(s); s = NULL;
    }
    ERR_clear_error();
    return s;
}

void gsec_destroy(GooseSecurity *s)
{
    if (!s) return;
    EVP_PKEY_free(s->identity);
    X509_free(s->certificate);
    X509_free(s->peer_cert);
    X509_STORE_free(s->trust);
    sk_X509_pop_free(s->issuers, X509_free);
    OPENSSL_cleanse(s, sizeof(*s));
    free(s);
}

typedef struct { const uint8_t *value; size_t size; } Field;
static int parse_hello(const uint8_t *p, size_t n, Field f[9])
{
    if (n > GSEC_MAX_HANDSHAKE) return 0;
    while (n) {
        if (n < 3) return 0;
        unsigned tag = p[0];
        size_t size = ((size_t)p[1]<<8) | p[2];
        p += 3; n -= 3;
        if (size > n || tag < 1 || tag > 8 || f[tag].value) return 0;
        f[tag].value = p; f[tag].size = size;
        p += size; n -= size;
    }
    for (int i = 1; i <= 7; i++) if (!f[i].value) return 0;
    return f[1].size == 5 && !memcmp(f[1].value, "GSEC1", 5) &&
        f[2].size == 1 && *f[2].value == 1 && f[3].size == 2 &&
        f[3].value[0] == 0 && f[3].value[1] == 1 &&
        f[4].size == 65 && *f[4].value == 4 && f[5].size == 32 &&
        f[6].size > 0 && f[7].size > 0 && f[7].size <= 72 &&
        (!f[8].value || f[8].size == 32);
}
static int signature(EVP_PKEY *key, int sign, const uint8_t *text, size_t size,
                     uint8_t *sig, size_t *sig_size)
{
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    int ok = ctx && (sign ? EVP_DigestSignInit(ctx, NULL, EVP_sha256(), NULL, key) :
                          EVP_DigestVerifyInit(ctx, NULL, EVP_sha256(), NULL, key)) == 1;
    if (ok) ok = sign ? EVP_DigestSign(ctx, sig, sig_size, text, size) == 1 :
                        EVP_DigestVerify(ctx, sig, *sig_size, text, size) == 1;
    EVP_MD_CTX_free(ctx);
    return ok;
}
static int put(uint8_t *out, size_t *used, uint8_t tag, const uint8_t *p, size_t n)
{
    if (n > GSEC_MAX_HANDSHAKE - 3 || *used > GSEC_MAX_HANDSHAKE - 3 - n) return 0;
    out[(*used)++] = tag; out[(*used)++] = (uint8_t)(n>>8); out[(*used)++] = (uint8_t)n;
    memcpy(out+*used, p, n); *used += n;
    return 1;
}

int gsec_hello(GooseSecurity *s, const uint8_t *packet, size_t length,
               uint32_t peer, uint8_t *ack, size_t *ack_length)
{
    Field f[9] = {{0}};
    uint8_t transcript[202], digest[32], salt[64], shared[32], key[16], eph[65], sig[80];
    unsigned digest_len = 0;
    EVP_PKEY *remote = NULL, *temporary = NULL, *public = NULL;
    EVP_PKEY_CTX *derive = NULL, *hkdf = NULL, *generation = NULL;
    X509 *cert = NULL;
    EC_KEY *remote_ec = NULL;
    int ok = 0;
    size_t sig_len = sizeof(sig), shared_len = sizeof(shared), key_len = sizeof(key), used = 0;
    struct timespec now;
    *ack_length = 0;
    if (!parse_hello(packet, length, f)) return reject(s, "malformed HELLO/TLV");
    const unsigned char *cp = f[6].value;
    cert = d2i_X509(NULL, &cp, (long)f[6].size);
    if (!cert || cp != f[6].value + f[6].size || !verify_cert(s, cert) ||
        !verify_cert(s, s->certificate)) goto out;
    memcpy(transcript, "GSEC1\x01\x00\x01", 8);
    memcpy(transcript+8, f[4].value, 65); memcpy(transcript+73, f[5].value, 32);
    public = X509_get_pubkey(cert);
    sig_len = f[7].size;
    if (!signature(public, 0, transcript, 105, (uint8_t *)f[7].value, &sig_len) ||
        EVP_Digest(transcript, 105, digest, &digest_len, EVP_sha256(), NULL) != 1 || digest_len != 32) goto out;
    clock_gettime(CLOCK_MONOTONIC, &now);
    if (s->established && CRYPTO_memcmp(digest, s->hello_hash, 32) == 0) {
        /* Idempotent retransmission. No rekey and, critically, no replay reset. */
        if (peer != s->peer_ip) goto out;
        memcpy(ack, s->ack, s->ack_length); *ack_length = s->ack_length;
        /* The normal success record plus counters are sufficient; avoid logging
         * each unauthenticated UDP retransmission to persistent storage. */
        ok = 1; goto out;
    }
    if (s->established && now.tv_sec - s->last_activity.tv_sec < 30) {
        X509_free(cert); EVP_PKEY_free(public);
        OPENSSL_cleanse(shared,sizeof(shared)); OPENSSL_cleanse(key,sizeof(key));
        return reject(s,"rekey deferred: active session, retry after 30s idle");
    }
    remote_ec = EC_KEY_new_by_curve_name(NID_X9_62_prime256v1);
    if (!remote_ec) goto out;
    const unsigned char *point = f[4].value;
    if (!o2i_ECPublicKey(&remote_ec, &point, 65) || EC_KEY_check_key(remote_ec) != 1) goto out;
    remote = EVP_PKEY_new();
    if (!remote || EVP_PKEY_set1_EC_KEY(remote, remote_ec) != 1) goto out;
    generation = EVP_PKEY_CTX_new_id(EVP_PKEY_EC, NULL);
    if (!generation || EVP_PKEY_keygen_init(generation) != 1 ||
        EVP_PKEY_CTX_set_ec_paramgen_curve_nid(generation, NID_X9_62_prime256v1) != 1 ||
        EVP_PKEY_keygen(generation, &temporary) != 1) goto out;
    EC_KEY *temp_ec = EVP_PKEY_get1_EC_KEY(temporary);
    if (!temp_ec) goto out;
    int point_ok = EC_POINT_point2oct(EC_KEY_get0_group(temp_ec), EC_KEY_get0_public_key(temp_ec),
                   POINT_CONVERSION_UNCOMPRESSED, eph, sizeof(eph), NULL) == 65;
    EC_KEY_free(temp_ec);
    if (!point_ok) goto out;
    memcpy(salt, f[5].value, 32);
    if (RAND_bytes(salt+32, 32) != 1) goto out;
    derive = EVP_PKEY_CTX_new(temporary, NULL);
    if (!derive || EVP_PKEY_derive_init(derive) != 1 ||
        EVP_PKEY_derive_set_peer(derive, remote) != 1 ||
        EVP_PKEY_derive(derive, shared, &shared_len) != 1 || shared_len != 32) goto out;
    hkdf = EVP_PKEY_CTX_new_id(EVP_PKEY_HKDF, NULL);
    if (!hkdf || EVP_PKEY_derive_init(hkdf) != 1 ||
        EVP_PKEY_CTX_set_hkdf_md(hkdf, EVP_sha256()) != 1 ||
        EVP_PKEY_CTX_set1_hkdf_salt(hkdf, salt, 64) != 1 ||
        EVP_PKEY_CTX_set1_hkdf_key(hkdf, shared, 32) != 1 ||
        EVP_PKEY_CTX_add1_hkdf_info(hkdf, (const uint8_t *)"GOOSE_SEC_P2S_V1", 16) != 1 ||
        EVP_PKEY_derive(hkdf, key, &key_len) != 1 || key_len != 16) goto out;
    memcpy(transcript, "GSEC1\x02\x00\x01", 8);
    memcpy(transcript+8, eph, 65); memcpy(transcript+73, salt+32, 32);
    memcpy(transcript+105, f[4].value, 65); memcpy(transcript+170, f[5].value, 32);
    sig_len = sizeof(sig);
    if (!signature(s->identity, 1, transcript, 202, sig, &sig_len)) goto out;
    uint8_t der[GSEC_MAX_HANDSHAKE], *der_cursor = der;
    int der_len = i2d_X509(s->certificate, &der_cursor);
    const uint8_t type = 2, keyid[2] = {0,1};
    if (der_len <= 0 || !put(ack,&used,1,(const uint8_t *)"GSEC1",5) ||
        !put(ack,&used,2,&type,1) || !put(ack,&used,3,keyid,2) || !put(ack,&used,4,eph,65) ||
        !put(ack,&used,5,salt+32,32) || !put(ack,&used,6,der,(size_t)der_len) ||
        !put(ack,&used,7,sig,sig_len)) goto out;
    memcpy(s->key, key, 16); memcpy(s->hello_hash, digest, 32);
    memcpy(s->ack, ack, used); s->ack_length = used; s->peer_ip = peer;
    X509_free(s->peer_cert); s->peer_cert = cert; cert = NULL;
    s->credentials_checked = 0; s->credentials_valid = 0;
    s->established = 1; s->replay_valid = 0; s->first_frame = 1; s->last_activity = now;
    *ack_length = used;
    GLOG("INFO", "GOOSE session established: ECDSA/ECDHE P-256, HKDF-SHA256, AES-128-GCM keyId=1");
    if (getenv("GOOSE_DEBUG_KEY_FINGERPRINT")) {
        uint8_t fp[32]; unsigned len = 0;
        if (EVP_Digest(key,16,fp,&len,EVP_sha256(),NULL) == 1 && len == 32)
            GLOG("DEBUG", "P2S rxKey SHA256 prefix=%02x%02x%02x%02x%02x%02x%02x%02x",
                 fp[0],fp[1],fp[2],fp[3],fp[4],fp[5],fp[6],fp[7]);
    }
    ok = 1;
out:
    X509_free(cert); EVP_PKEY_free(public); EVP_PKEY_free(remote); EVP_PKEY_free(temporary);
    EC_KEY_free(remote_ec); EVP_PKEY_CTX_free(generation);
    EVP_PKEY_CTX_free(derive); EVP_PKEY_CTX_free(hkdf);
    OPENSSL_cleanse(shared,sizeof(shared)); OPENSSL_cleanse(key,sizeof(key));
    if (!ok) { OPENSSL_cleanse(ack,GSEC_MAX_HANDSHAKE); return reject(s,"HELLO authentication/key agreement failed"); }
    ERR_clear_error(); return 0;
}

/* Bounded definite-length BER reader. No recursive decoding of ciphertext. */
typedef struct { uint8_t tag; size_t start, value, length, end; } Ber;
static int ber(const uint8_t *p, size_t end, size_t *offset, Ber *v)
{
    size_t i = *offset;
    if (i >= end) return 0;
    v->start = i; v->tag = p[i++];
    if ((v->tag & 31) == 31 || i >= end) return 0;
    size_t n = p[i++];
    if (n & 128) {
        size_t count = n & 127; n = 0;
        if (!count || count > 3 || count > end-i) return 0;
        for (size_t j = 0; j < count; j++) n = (n<<8)|p[i++];
    }
    if (n > end-i) return 0;
    v->value = i; v->length = n; v->end = i+n; *offset = i+n;
    return 1;
}
static int integer(const uint8_t *p, const Ber *v, uint32_t *value)
{
    size_t i = v->value, n = v->length;
    if (!n || n > 5 || (p[i]&128)) return 0;
    if (n == 5) { if (p[i++]) return 0; n--; }
    uint32_t result = 0;
    while (n--) result = (result<<8)|p[i++];
    *value = result; return 1;
}
static size_t put_length(uint8_t *p, size_t n)
{
    if (n < 128) { p[0]=(uint8_t)n; return 1; }
    if (n < 256) { p[0]=0x81; p[1]=(uint8_t)n; return 2; }
    p[0]=0x82; p[1]=(uint8_t)(n>>8); p[2]=(uint8_t)n; return 3;
}

static int dataset_valid(const uint8_t *p, size_t n, unsigned depth, uint32_t *count)
{
    size_t offset = 0;
    uint32_t entries = 0;
    if (depth > 16) return 0;
    while (offset < n) {
        Ber v;
        if (!ber(p,n,&offset,&v) || ++entries > 256) return 0;
        if (v.tag == 0xa1 || v.tag == 0xa2) {
            uint32_t nested;
            if (!dataset_valid(p+v.value,v.length,depth+1,&nested)) return 0;
        } else {
            switch (v.tag) {
            case 0x83: if (v.length!=1) return 0; break;
            case 0x84: if (!v.length || p[v.value]>7) return 0; break;
            case 0x85: case 0x86: if (!v.length || v.length>8) return 0; break;
            case 0x87: if (v.length!=5 && v.length!=9) return 0; break;
            case 0x89: case 0x8a: case 0x90: break;
            case 0x8c: if (v.length!=4 && v.length!=6) return 0; break;
            case 0x91: if (v.length!=8) return 0; break;
            default: return 0;
            }
        }
    }
    *count = entries;
    return 1;
}

int gsec_open_frame(GooseSecurity *s, const uint8_t *frame, size_t size,
                    uint8_t *plain, int *new_session)
{
    Ber outer, fields[12], security;
    uint8_t candidate[GSEC_MAX_FRAME], nonce[12] = {0};
    EVP_CIPHER_CTX *ctx = NULL;
    const char *reason = "malformed Ethernet/BER/security";
    size_t eth = 14, offset, length;
    uint32_t st = 0, sq = 0, ignored, expected_entries=0;
    int out = 0, final = 0, result = -1;
    memset(plain,0,GSEC_MAX_FRAME); *new_session = 0;
    if (size < 22 || size > GSEC_MAX_FRAME || memcmp(frame,s->destination,6)) goto done;
    if (frame[12]==0x81 && frame[13]==0) eth = 18;
    if (size < eth+8 || frame[eth-2]!=0x88 || frame[eth-1]!=0xb8 ||
        (((unsigned)frame[eth]<<8)|frame[eth+1]) != s->appid) goto done;
    length = ((size_t)frame[eth+2]<<8)|frame[eth+3];
    if (length < 8 || length > size-eth) goto done;
    const uint8_t *p = frame+eth+8;
    size_t n = length-8;
    offset=0;
    if (!ber(p,n,&offset,&outer) || outer.tag != 0x61 || outer.end != n) goto done;
    offset=outer.value;
    memset(fields,0,sizeof(fields));
    unsigned seen = 0;
    int previous = -1;
    while (offset < outer.end) {
        Ber v;
        if (!ber(p,outer.end,&offset,&v)) goto done;
        int index = (v.tag>=0x80 && v.tag<=0x8a) ? v.tag-0x80 : (v.tag==0xab ? 11 : -1);
        if (index < 0 || index <= previous || (seen & (1u<<index))) goto done;
        fields[index]=v; seen |= 1u<<index; previous=index;
        if (index==11) break;
    }
    /* goID (0x83) is optional; other baseline fields are required. */
    if ((seen|8u) != 0xfffu || fields[0].length != strlen(s->reference) ||
        memcmp(p+fields[0].value,s->reference,fields[0].length) ||
        !fields[2].length || fields[2].length>129 || fields[3].length>129 ||
        fields[4].length!=8 || fields[7].length!=1 || fields[9].length!=1 ||
        !integer(p,&fields[1],&ignored) || !integer(p,&fields[5],&st) ||
        !integer(p,&fields[6],&sq) || !integer(p,&fields[8],&ignored) ||
        !integer(p,&fields[10],&expected_entries)) goto done;
    if (!ber(p,outer.end,&offset,&security) || security.tag != 0x9c ||
        security.length != 19 || offset != outer.end ||
        memcmp(p+security.value,"\x01\x00\x01",3)) goto done;
    reason="no authenticated session";
    if (!s->established) goto done;
    reason="expired/revoked certificate or CRL";
    /* PKI generation is immutable. Recheck at wall-clock second boundaries,
     * including backward clock changes, to enforce certificate/CRL expiry while
     * avoiding two X.509 signature-chain validations on every real-time frame. */
    time_t wall = time(NULL);
    if (wall == (time_t)-1) goto done;
    if (wall != s->credentials_checked) {
        s->credentials_valid = verify_cert(s,s->peer_cert) && verify_cert(s,s->certificate);
        s->credentials_checked = wall;
    }
    if (!s->credentials_valid) goto done;
    reason="GCM tag mismatch";
    for (int i=0;i<4;i++) { nonce[7-i]=(uint8_t)(st>>(8*i)); nonce[11-i]=(uint8_t)(sq>>(8*i)); }
    ctx=EVP_CIPHER_CTX_new();
    Ber *data=&fields[11];
    if (!ctx || EVP_DecryptInit_ex(ctx,EVP_aes_128_gcm(),NULL,NULL,NULL)!=1 ||
        EVP_CIPHER_CTX_ctrl(ctx,EVP_CTRL_GCM_SET_IVLEN,12,NULL)!=1 ||
        EVP_DecryptInit_ex(ctx,NULL,NULL,s->key,nonce)!=1 ||
        EVP_DecryptUpdate(ctx,NULL,&out,p+outer.value,(int)(data->value-outer.value))!=1 ||
        EVP_DecryptUpdate(ctx,candidate,&out,p+data->value,(int)data->length)!=1 ||
        EVP_CIPHER_CTX_ctrl(ctx,EVP_CTRL_GCM_SET_TAG,16,(void *)(p+security.value+3))!=1 ||
        EVP_DecryptFinal_ex(ctx,candidate+out,&final)!=1 || (size_t)(out+final)!=data->length) goto done;
    uint32_t actual_entries=0;
    reason="invalid authenticated allData BER/count";
    if (!dataset_valid(candidate,data->length,0,&actual_entries) || actual_entries!=expected_entries) goto done;
    reason="replayed/out-of-order frame";
    if (s->replay_valid && (st<s->last_st || (st==s->last_st && sq<=s->last_sq))) goto done;
    /* Rebuild outer length to handle 127/128 and 255/256 transitions. The
     * underlying allData decoder sees only authenticated plaintext. */
    size_t body_size=data->end-outer.value, h=1;
    uint8_t header[4]={0x61}; h+=put_length(header+1,body_size);
    size_t total=eth+8+h+body_size;
    if (total>GSEC_MAX_FRAME) goto done;
    memcpy(plain,frame,eth+8); memcpy(plain+eth+8,header,h);
    memcpy(plain+eth+8+h,p+outer.value,body_size);
    memcpy(plain+eth+8+h+data->value-outer.value,candidate,data->length);
    size_t goose_size=8+h+body_size;
    plain[eth+2]=(uint8_t)(goose_size>>8); plain[eth+3]=(uint8_t)goose_size;
    s->last_st=st; s->last_sq=sq; s->replay_valid=1;
    clock_gettime(CLOCK_MONOTONIC,&s->last_activity);
    *new_session=s->first_frame; s->first_frame=0;
    s->accepted++;
    if (s->accepted==1 || s->accepted%1000==0)
        GLOG("INFO","GOOSE authenticated APPID=0x%04x stNum=%u sqNum=%u accepted=%llu rejected=%llu",
             s->appid,st,sq,(unsigned long long)s->accepted,(unsigned long long)s->rejected);
    result=(int)total;
done:
    EVP_CIPHER_CTX_free(ctx); OPENSSL_cleanse(candidate,sizeof(candidate));
    if (result<0) return reject(s,reason);
    return result;
}
