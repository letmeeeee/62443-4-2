#define _GNU_SOURCE
#include "goose_transport.h"
#include "goose_log.h"
#include "goose_subscriber.h"
#include <sys/socket.h>
#include <linux/if_packet.h>
#include <net/ethernet.h>
#include <net/if.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <unistd.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>


struct GooseTransport {
    GooseSecurity *security;
    GooseReceiver receiver;
    int ethernet, udp, wake[2];
    pthread_t thread;
    pthread_mutex_t state_lock;
    int healthy;
    int (*on_session)(void);
};

static void *receive_loop(void *arg)
{
    GooseTransport *t=arg;
    uint8_t packet[GSEC_MAX_FRAME], plain[GSEC_MAX_FRAME], ack[GSEC_MAX_HANDSHAKE];
    GLOG("INFO","GOOSE secure listener ready: UDP/30001 and Ethernet/0x88b8; plaintext disabled");
    struct timespec started;
    clock_gettime(CLOCK_MONOTONIC,&started);
    int wait_logged=0;
    int have_session=0;
    for (;;) {
        fd_set fds;
        FD_ZERO(&fds); FD_SET(t->ethernet,&fds); FD_SET(t->udp,&fds); FD_SET(t->wake[0],&fds);
        int max=t->ethernet>t->udp?t->ethernet:t->udp;
        if(t->wake[0]>max) max=t->wake[0];
        struct timeval timeout={0,500000};
        int ready=select(max+1,&fds,NULL,NULL,&timeout);
        if(ready<0) { if(errno==EINTR) continue; GLOG("ERROR","GOOSE select failed: %s",strerror(errno)); break; }
        if(FD_ISSET(t->wake[0],&fds)) break;
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC,&now);
        if(!have_session && !wait_logged && now.tv_sec-started.tv_sec>=30) {
            GLOG("WARNING","No session after initial 30s wait; continuing to listen for authenticated HELLO");
            wait_logged=1;
        }
        if(FD_ISSET(t->udp,&fds)) {
            struct sockaddr_in peer={0}; socklen_t peer_len=sizeof(peer);
            ssize_t n=recvfrom(t->udp,packet,GSEC_MAX_HANDSHAKE+1,MSG_TRUNC,(struct sockaddr *)&peer,&peer_len);
            if(n>0 && n<=GSEC_MAX_HANDSHAKE && peer_len==sizeof(peer) && peer.sin_family==AF_INET) {
                size_t length=0;
                if(gsec_hello(t->security,packet,(size_t)n,peer.sin_addr.s_addr,ack,&length)==0) {
                    if(sendto(t->udp,ack,length,0,(struct sockaddr *)&peer,peer_len)!=(ssize_t)length)
                        GLOG("WARNING","GOOSE ACK send failed: %s; HELLO retry may recover",strerror(errno));
                    else have_session=1;
                }
            } else GLOG("WARNING","Invalid/oversized HELLO datagram rejected size=%zd",n);
        }
        if(FD_ISSET(t->ethernet,&fds)) {
            struct sockaddr_ll source={0}; socklen_t source_len=sizeof(source);
            ssize_t n=recvfrom(t->ethernet,packet,sizeof(packet),MSG_TRUNC,(struct sockaddr *)&source,&source_len);
            if(n<=0 || n>(ssize_t)sizeof(packet) || source.sll_family!=AF_PACKET || source.sll_pkttype==PACKET_OUTGOING) continue;
            size_t eth=14;
            if(n>=18 && packet[12]==0x81 && packet[13]==0) eth=18;
            if((size_t)n<eth+8 || packet[eth-2]!=0x88 || packet[eth-1]!=0xb8) continue;
            int first=0;
            int length=gsec_open_frame(t->security,packet,(size_t)n,plain,&first);
            if(length>0) {
                if(first && t->on_session && t->on_session()!=0) {
                    GLOG("ERROR","Failed to reset decoder for new authenticated session; reception stopped");
                    memset(plain,0,sizeof(plain));
                    break;
                }
                /* The receiver has no started socket/thread: this is its sole ingress. */
                GooseReceiver_handleMessage(t->receiver,plain,length);
                memset(plain,0,sizeof(plain));
            }
        }
    }
    pthread_mutex_lock(&t->state_lock);
    t->healthy=0;
    pthread_mutex_unlock(&t->state_lock);
    GLOG("INFO","GOOSE secure receive loop stopped");
    return NULL;
}

GooseTransport *goose_transport_start(GooseReceiver receiver, const char *interface,
    const char *directory, uint16_t appid, const uint8_t destination[6], const char *reference, int (*on_session)(void))
{
    GooseTransport *t=calloc(1,sizeof(*t));
    if(!t) return NULL;
    if(pthread_mutex_init(&t->state_lock,NULL)) { free(t); return NULL; }
    t->healthy=1;
    t->ethernet=t->udp=t->wake[0]=t->wake[1]=-1; t->receiver=receiver; t->on_session=on_session;
    t->security=gsec_create(directory,appid,destination,reference);
    if(!t->security) goto fail;
    unsigned index=if_nametoindex(interface);
    if(!index) goto fail;
    /* ETH_P_ALL also receives VLAN-tagged frames; authenticate/filter below. */
    t->ethernet=socket(AF_PACKET,SOCK_RAW|SOCK_CLOEXEC,htons(ETH_P_ALL));
    struct sockaddr_ll link={0}; link.sll_family=AF_PACKET; link.sll_ifindex=(int)index; link.sll_protocol=htons(ETH_P_ALL);
    if(t->ethernet<0 || bind(t->ethernet,(struct sockaddr *)&link,sizeof(link))) goto fail;
    struct packet_mreq membership={0}; membership.mr_ifindex=(int)index;
    membership.mr_type=PACKET_MR_MULTICAST; membership.mr_alen=6;
    memcpy(membership.mr_address,destination,6);
    if(setsockopt(t->ethernet,SOL_PACKET,PACKET_ADD_MEMBERSHIP,&membership,sizeof(membership))) goto fail;
    t->udp=socket(AF_INET,SOCK_DGRAM|SOCK_CLOEXEC,0);
    if(t->udp<0 || setsockopt(t->udp,SOL_SOCKET,SO_BINDTODEVICE,interface,strlen(interface)+1)) goto fail;
    struct sockaddr_in address={0}; address.sin_family=AF_INET;
    address.sin_port=htons(30001); address.sin_addr.s_addr=htonl(INADDR_ANY);
    if(bind(t->udp,(struct sockaddr *)&address,sizeof(address)) || pipe(t->wake)) goto fail;
    if(t->ethernet>=FD_SETSIZE || t->udp>=FD_SETSIZE || t->wake[0]>=FD_SETSIZE) goto fail;
    int error=pthread_create(&t->thread,NULL,receive_loop,t);
    if(error) { errno=error; goto fail; }
    return t;
fail:
    GLOG("ERROR","GOOSE security startup failed interface=%s: %s (no plaintext fallback)",interface,strerror(errno));
    if(t->ethernet>=0) close(t->ethernet);
    if(t->udp>=0) close(t->udp);
    if(t->wake[0]>=0) close(t->wake[0]);
    if(t->wake[1]>=0) close(t->wake[1]);
    gsec_destroy(t->security); pthread_mutex_destroy(&t->state_lock); free(t); return NULL;
}
int goose_transport_is_running(GooseTransport *t)
{
    if(!t) return 0;
    pthread_mutex_lock(&t->state_lock);
    int healthy=t->healthy;
    pthread_mutex_unlock(&t->state_lock);
    return healthy;
}
void goose_transport_stop(GooseTransport *t)
{
    if(!t) return;
    char stop=1;
    (void)write(t->wake[1],&stop,1);
    pthread_join(t->thread,NULL);
    close(t->wake[0]); close(t->wake[1]); close(t->ethernet); close(t->udp);
    gsec_destroy(t->security); pthread_mutex_destroy(&t->state_lock); free(t);
}
