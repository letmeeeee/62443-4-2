"""Security-center contracts; missing platform telemetry is explicitly unavailable."""
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file
from sqlalchemy import select
from utils import security_store as store
from utils import security_audit as audit
from utils.access import ABILITIES

security_bp = Blueprint('security', __name__)
DEFAULT_NOTICE = dict(enabled=True, version=1, text='仅限授权人员使用。所有操作可能被记录和审计。')


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('INVALID_JSON')
    return data


@security_bp.errorhandler(ValueError)
def invalid_request(exc):
    value = str(exc)
    code = value if re.fullmatch(r'[A-Z][A-Z0-9_]{1,80}', value) else 'INVALID_REQUEST'
    return jsonify(ok=False, code=code, message=code), 400


@security_bp.errorhandler(FileNotFoundError)
def missing_resource(exc):
    return jsonify(ok=False,code='RESOURCE_NOT_FOUND'),404


@security_bp.route('/permission/login-notice', methods=['GET', 'POST'])
def login_notice():
    with audit.engine().begin() as conn:
        if request.method == 'POST':
            store.lock_security(conn)
            data = _body()
            if type(data.get('enabled')) is not bool or not isinstance(data.get('text'), str) or not 1 <= len(data['text']) <= 4000:
                raise ValueError('INVALID_NOTICE')
            old = store.get_setting(conn, 'login_notice', DEFAULT_NOTICE)
            notice = dict(enabled=data['enabled'], text=data['text'], version=old['version']+1)
            store.set_setting(conn, 'login_notice', notice)
            g.audit_before, g.audit_after = old, notice
        else:
            notice = store.get_setting(conn, 'login_notice', DEFAULT_NOTICE)
    return jsonify(ok=True, **notice)


@security_bp.route('/api/security/password-policy')
def password_policy():
    return jsonify(ok=True, **store.PASSWORD_POLICY)


@security_bp.route('/api/security/roles')
def roles():
    return jsonify(ok=True, abilities=ABILITIES)


@security_bp.route('/api/security/maintenance', methods=['GET','POST'])
def maintenance():
    import time
    if request.method == 'POST':
        from routes.route_permission import _credentials_check
        data = _body()
        enabled = data.get('enabled')
        seconds = data.get('seconds', 900)
        if type(enabled) is not bool or type(seconds) is not int or not 60 <= seconds <= 3600:
            raise ValueError('INVALID_MAINTENANCE_REQUEST')
        if data.get('confirm') != ('ENTER_MAINTENANCE' if enabled else 'EXIT_MAINTENANCE'):
            raise ValueError('CONFIRMATION_REQUIRED')
        _, error = _credentials_check(g.current_user['username'], data.get('password'))
        if error:
            return error
        with audit.engine().begin() as conn:
            store.lock_security(conn)
            g.audit_before = store.maintenance_state(conn)
            store.set_setting(conn,'maintenance',dict(until=time.time()+seconds if enabled else 0,
                                                      operator=g.current_user['username']))
            g.audit_after = store.maintenance_state(conn)
    with audit.engine().connect() as conn:
        return jsonify(ok=True, **store.maintenance_state(conn))


@security_bp.route('/api/history/status')
def history_status():
    return jsonify(ok=True, **audit.status())


@security_bp.route('/api/history/export')
def history_export():
    return audit.export_records()


def _command(arguments):
    try:
        result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=5, check=False, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def memory_usage():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable'):
            values[key] = int(value.split()[0]) * 1024
    total, available = values['MemTotal'], values['MemAvailable']
    return dict(total=total, available=available, used=total-available,
                usedPercent=round((total-available)*100/total, 2))


def certificate_inventory():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from script import pki_common as pki
    import config
    settings=pki.read_config(config.INI_PATH)
    directory=Path(current_app.config.get('MODBUS_CERT_DIR','/etc/ems/modbus'))
    https=Path(current_app.config.get('HTTPS_CERT_DIR','/etc/ssl/g3'))
    paths=[(directory/'master.crt','master'),(directory/'slave.crt','slave'),
           (https/'g3.crt','https'),(settings['ca_file'],'ca-root')]
    items=[]
    now=datetime.now(timezone.utc)
    for path,role in paths:
        if not path.exists():
            continue
        if path.is_symlink() or path.stat().st_size>1024*1024:
            items.append(dict(role=role,status='invalid',reason='INVALID_CERTIFICATE_FILE'))
            continue
        data=path.read_bytes()
        blocks=re.findall(b'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',data,re.S)
        if not blocks:
            items.append(dict(role=role,status='invalid',reason='INVALID_CERTIFICATE'))
            continue
        # A fullchain is one identity, not one device per intermediate certificate.
        if role!='ca-root':
            blocks=blocks[:1]
        for block in blocks:
            try:
                cert=x509.load_pem_x509_certificate(block)
                start,end=cert.not_valid_before_utc,cert.not_valid_after_utc
                digest=cert.fingerprint(hashes.SHA256()).hex()
                public=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
                validity='not_yet_valid' if now<start else 'expired' if now>end else 'expiring' if (end-now).days<=30 else 'valid'
                verified=True
                try:
                    if role=='ca-root':
                        pki.validate_roots(data)
                    else:
                        pki.validate_identity(data,None,settings['ca_file'],'sslclient' if role=='master' else 'sslserver')
                except (OSError,ValueError,subprocess.SubprocessError):
                    verified=False
                items.append(dict(id=digest,role=role,subject=cert.subject.rfc4514_string(),issuer=cert.issuer.rfc4514_string(),
                    notBefore=start.isoformat(),notAfter=end.isoformat(),sha256=digest,keyId=hashlib.sha256(public).hexdigest(),
                    signatureAlgorithmOid=cert.signature_algorithm_oid.dotted_string,status=validity if verified else 'invalid',
                    validityStatus=validity,chainVerified=verified,privateKeyVerified=None,
                    validityOnly=False,revocationStatus='unavailable'))
            except ValueError:
                items.append(dict(role=role,status='invalid',reason='INVALID_CERTIFICATE'))
    return items


@security_bp.route('/api/security/certificates',methods=['GET'])
def certificates():
    items=certificate_inventory()
    return jsonify(ok=True,data=items,scope='ca-issued-device-identities',
        expiringCount=sum(item.get('validityStatus',item['status'])=='expiring' for item in items),
        errorCount=sum(item['status'] in ('invalid','expired','not_yet_valid') for item in items))


@security_bp.route('/api/security/certificates/import',methods=['POST'])
def certificate_import():
    from routes.route_cert import import_signed_identity
    return import_signed_identity()


@security_bp.route('/api/security/certificates/verify', methods=['POST'])
def certificate_verify():
    from routes.route_cert import _cert_run_script, _cert_validate_role, CertificateScriptError
    role = _cert_validate_role(_body().get('role'))
    try:
        _cert_run_script(['check','--role',role])
        return jsonify(ok=True, valid=True, role=role, revocationStatus='unavailable')
    except CertificateScriptError:
        return jsonify(ok=False, code='CERTIFICATE_INVALID', message='Certificate verification failed', valid=False), 422


@security_bp.route('/api/security/keys')
def keys():
    # Public certificate references do not imply a successful TEE hardware self-test.
    items = [dict(keyId=item['keyId'], role=item['role'], source='certificate',
                  lastRotation=None, privateKeyExportable=False)
             for item in certificate_inventory() if 'keyId' in item]
    tee_status = 'unavailable'
    try:
        from routes.route_tee import _run
        public = _run('public-key')
        modulus, exponent = int(public['n'],16), int(public['e'],16)
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        from cryptography.hazmat.primitives import serialization
        der = RSAPublicNumbers(exponent,modulus).public_key().public_bytes(
            serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        with audit.engine().connect() as conn:
            from sqlalchemy import func
            rotated = conn.execute(select(func.max(audit.EVENTS.c.operation_time)).where(
                audit.EVENTS.c.operation_target=='/api/cert/tee/rotate-rsa',audit.EVENTS.c.result==1)).scalar()
        items.append(dict(keyId=hashlib.sha256(der).hexdigest(),source='tee-public-key',
            algorithm='RSA-3072', lastRotation=rotated.isoformat() if rotated else None,
            privateKeyExportable=False))
        tee_status = 'public_key_available'
    except Exception:
        current_app.logger.info('TEE public key telemetry is not available')
    return jsonify(ok=True, data=items, rotationTelemetryAvailable=True,
                   teeStatus=tee_status, symmetricKeyTelemetryAvailable=False)


@security_bp.route('/api/security/peer-status')
def peers():
    items = [dict(identity=item.get('subject'), keyId=item.get('keyId'),
                  trusted=True, authenticationStatus='unknown', connected=None)
             for item in certificate_inventory() if item['role']=='trusted-master']
    return jsonify(ok=True, data=items, liveAuthenticationTelemetryAvailable=False)


@security_bp.route('/api/security/network-rules')
def network_rules():
    addresses = _command(['ip','-j','address','show'])
    routes = _command(['ip','-j','route','show'])
    rules = _command(['nft','-j','list','ruleset'])
    return jsonify(ok=True, interfaces=json.loads(addresses) if addresses else [],
        routes=json.loads(routes) if routes else [], rules=json.loads(rules) if rules else None,
        interfacesAvailable=addresses is not None, rulesAvailable=rules is not None,
        source='kernel-iproute2-nftables', writable=False)


@security_bp.route('/api/system/components')
def components():
    python_packages = sorted([dict(name=d.metadata['Name'], version=d.version, type='python-package')
        for d in importlib.metadata.distributions() if d.metadata.get('Name')], key=lambda item:item['name'].lower())
    base = [dict(name='Python', version=platform.python_version(), type='runtime'),
            dict(name='Linux', version=platform.release(), type='kernel')]
    for name, command in (('Node.js',['node','--version']), ('MySQL client',['mysql','--version'])):
        version = _command(command)
        base.append(dict(name=name, version=version, available=version is not None))
    manifest = current_app.config.get('COMPONENT_MANIFEST')
    supplied = []
    if manifest:
        path=Path(manifest)
        if path.stat().st_size > 1024*1024:
            raise ValueError('COMPONENT_MANIFEST_TOO_LARGE')
        entries=json.loads(path.read_text())
        if not isinstance(entries,list) or any(not isinstance(item,dict) for item in entries):
            raise ValueError('INVALID_COMPONENT_MANIFEST')
        for item in entries:
            supplied.append({key:value for key,value in item.items() if key in
                ('name','version','type','supplier','license','purl','sha256') and isinstance(value,str)})
    return jsonify(ok=True, components=base+python_packages+supplied,
        scope='backend-runtime-and-configured-manifest', firmwareInventoryComplete=bool(supplied))


@security_bp.route('/api/security/config-summary')
def config_summary():
    from utils.auth import is_developer_account_disabled
    from sqlalchemy import text
    import config
    with audit.engine().connect() as conn:
        users = conn.execute(text(f'SELECT username,permission FROM `{config.PERM_TABLE}`')).mappings().all()
        identities = []
        for user in users:
            state = store.read_account_state(conn, user['username'])
            identities.append(dict(username=user['username'], permission=user['permission'],
                uid=state['uid'] if state else None, enabled=(state['enabled'] if state else True)
                and not is_developer_account_disabled(user['username'])))
    return jsonify(ok=True, schemaVersion=1, generatedAt=datetime.now(timezone.utc).isoformat(),
        users=identities, abilities=ABILITIES, passwordPolicy=store.PASSWORD_POLICY,
        session=dict(absoluteSeconds=int(current_app.permanent_session_lifetime.total_seconds()),
                     idleSeconds=current_app.config['AUTH_IDLE_SECONDS']),
        certificates=certificate_inventory(), audit=audit.status(),
        networkRules=network_rules().get_json(), components=components().get_json(),
        timePolicy=dict(timezone=str(datetime.now().astimezone().tzinfo), syncPolicy='platform-managed'))


@security_bp.route('/api/security/status')
def security_status():
    from utils.auth import login_capacity
    from utils.system_usage import cpu_usage
    from utils.ini_integrity import verify_ini_checksum
    checks = {}
    for name, provider in (('cpu',cpu_usage), ('memory',memory_usage), ('audit',audit.status),
                           ('certificates',certificate_inventory), ('loginSessions',login_capacity)):
        try:
            checks[name] = dict(available=True, data=provider())
        except Exception:
            current_app.logger.exception('Security status collection failed: %s', name)
            checks[name] = dict(available=False, reason='COLLECTION_FAILED')
    try:
        usage = shutil.disk_usage(current_app.config.get('SECURITY_DISK_PATH','/'))
        checks['disk'] = dict(available=True, data=dict(total=usage.total, used=usage.used,
            free=usage.free, usagePercent=round(usage.used*100/usage.total,2)))
    except OSError:
        checks['disk'] = dict(available=False)
    valid, detail = verify_ini_checksum()
    checks['configurationIntegrity'] = dict(available=not detail.startswith('Integrity check unavailable'), valid=valid)
    ntp = _command(['timedatectl','show','--property=NTPSynchronized','--value'])
    checks['timeSync'] = dict(available=ntp in ('yes','no'), synchronized=ntp=='yes' if ntp in ('yes','no') else None)
    provider = current_app.extensions.get('web_connection_capacity')
    checks['webConnections'] = dict(available=provider is not None, data=provider() if provider else None)
    checks['tee'] = dict(available=False, reason='HARDWARE_TELEMETRY_NOT_PROVIDED')
    with audit.engine().connect() as conn:
        maintenance_state=store.maintenance_state(conn)
    alerts=[]
    for name in ('cpu','memory','disk'):
        value=checks[name]
        if value.get('available'):
            percent=value['data'].get('usedPercent',value['data'].get('usagePercent',0))
            if percent >= 90:
                alerts.append(dict(code='RESOURCE_USAGE_HIGH',source=name,usagePercent=percent))
    log_status=checks['audit']
    if audit.write_failed():
        alerts.append(dict(code='AUDIT_WRITE_FAILED',source='audit'))
    if log_status.get('available'):
        capacity_code = audit.capacity_alert(log_status['data'])
        if capacity_code:
            alerts.append(dict(code=capacity_code,source='audit'))
    cert_status=checks['certificates']
    if cert_status.get('available') and any(item['status'] != 'valid' for item in cert_status['data']):
        alerts.append(dict(code='CERTIFICATE_ATTENTION_REQUIRED',source='certificates'))
    if checks['configurationIntegrity']['available'] and not valid:
        alerts.append(dict(code='CONFIGURATION_INTEGRITY_FAILED',source='configurationIntegrity'))
    return jsonify(ok=True, checks=checks, maintenance=maintenance_state, alerts=alerts,
                   sampledAt=datetime.now(timezone.utc).isoformat())


@security_bp.route('/api/security/backups', methods=['GET', 'POST'])
def backups():
    from utils import security_backup as backup
    if request.method == 'GET':
        return jsonify(ok=True, data=backup.list_backups())
    result = backup.create_backup()
    audit.record_event('backup.create', result['id'], True)
    return jsonify(ok=True, **result), 201


@security_bp.route('/api/security/backups/<identifier>/download')
def backup_download(identifier):
    from utils.security_backup import _path, MAX_BACKUP_BYTES
    path = _path(identifier)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BACKUP_BYTES+64:
        return jsonify(ok=False,code='BACKUP_NOT_FOUND'),404
    if not audit.record_event('backup.download',identifier,True):
        return jsonify(ok=False,code='AUDIT_UNAVAILABLE'),503
    response=send_file(path,as_attachment=True,download_name='backup-'+identifier+'.lcb',
                       mimetype='application/octet-stream')
    response.headers['X-Backup-SHA256']=hashlib.sha256(path.read_bytes()).hexdigest()
    return response


@security_bp.route('/api/security/backups/<identifier>/validate', methods=['POST'])
def backup_validate(identifier):
    from utils.security_backup import read_backup
    data = _body()
    _, result = read_backup(identifier, data.get('sha256'))
    return jsonify(result)


def _maintenance_confirmation(action):
    data = _body()
    if data.get('dry_run', True) is not False:
        return data, False
    if not current_app.config.get('SECURITY_ALLOW_DESTRUCTIVE', False):
        raise ValueError('DESTRUCTIVE_OPERATIONS_DISABLED')
    if data.get('confirm') != action:
        raise ValueError('CONFIRMATION_REQUIRED')
    with audit.engine().connect() as conn:
        if not store.maintenance_state(conn)['active']:
            raise ValueError('MAINTENANCE_REQUIRED')
    # Fresh credential verification is in addition to administrator Bearer and CSRF.
    from routes.route_permission import _credentials_check
    _, error = _credentials_check(g.current_user['username'], data.get('password'))
    if error:
        raise ValueError('REAUTHENTICATION_FAILED')
    return data, True


@security_bp.route('/api/security/backups/<identifier>/restore', methods=['POST'])
def backup_restore(identifier):
    from utils.security_backup import read_backup, restore_backup
    data, execute = _maintenance_confirmation('RESTORE_BACKUP')
    _, checked = read_backup(identifier, data.get('sha256'))
    if not execute:
        return jsonify(ok=True, dry_run=True, validation=checked, sessions_will_be_revoked=True,
                       restart_required=True, executionEnabled=current_app.config.get('SECURITY_ALLOW_DESTRUCTIVE',False))
    if data.get('sha256') != checked['sha256']:
        raise ValueError('VALIDATED_DIGEST_REQUIRED')
    if not audit.record_event('backup.restore', identifier, True, 'Execution authorized'):
        return jsonify(ok=False, code='AUDIT_UNAVAILABLE'), 503
    return jsonify(restore_backup(identifier, checked['sha256']))


@security_bp.route('/api/security/factory-reset', methods=['POST'])
def factory_reset():
    from utils.security_backup import read_backup, restore_backup
    data, execute = _maintenance_confirmation('FACTORY_RESET')
    identifier = current_app.config.get('SECURITY_FACTORY_BACKUP_ID')
    digest = current_app.config.get('SECURITY_FACTORY_BACKUP_SHA256')
    if not identifier or not digest:
        return jsonify(ok=False, code='FACTORY_BASELINE_NOT_CONFIGURED',
                       message='Provision a trusted device-specific factory baseline first'), 409
    baseline, checked = read_backup(identifier, digest)
    if any(not user['password'].startswith('pbkdf2_sha256$') for user in baseline['users']):
        return jsonify(ok=False, code='FACTORY_BASELINE_REQUIRES_STRONG_CREDENTIALS'),409
    if not execute:
        return jsonify(ok=True, dry_run=True, validation=checked, scope='application-security',
                       restart_required=True)
    if not audit.record_event('factory.reset', identifier, True, 'Execution authorized'):
        return jsonify(ok=False, code='AUDIT_UNAVAILABLE'), 503
    return jsonify(restore_backup(identifier, digest, force_password_change=True))


@security_bp.route('/api/security/decommission', methods=['POST'])
def decommission():
    """Conservative application identity removal; platform secure erase is separate."""
    from utils.auth import LOGIN_SESSIONS, disconnect_revoked
    from utils.security_files import private_directory
    from sqlalchemy import MetaData, Table
    import config
    data, execute = _maintenance_confirmation('DECOMMISSION_APPLICATION')
    plan = dict(scope='application-identities', tables=[config.PERM_TABLE,
        store.ACCOUNT_STATE.name, store.SESSION_STATE.name, store.SESSION_LOCKS.name, LOGIN_SESSIONS.name,
        store.ATTEMPTS.name, store.RATE_LIMITS.name, store.SETTINGS.name], privateFiles=['credentials','backups'],
        excluded=['platform-and-TEE-keys','device-configuration','certificates','business-database','audit-and-application-logs'],
        completeDeviceErasure=False)
    if not execute:
        return jsonify(ok=True, dry_run=True, plan=plan,
                       executionEnabled=current_app.config.get('SECURITY_ALLOW_DESTRUCTIVE',False))
    if data.get('scope') != 'application-identities':
        raise ValueError('EXPLICIT_SCOPE_REQUIRED')
    targets={name:list(private_directory(name).iterdir()) for name in ('credentials','backups')}
    if not audit.record_event('decommission', 'application-identities', True, 'Execution authorized'):
        return jsonify(ok=False, code='AUDIT_UNAVAILABLE'), 503
    with audit.engine().begin() as conn:
        store.lock_security(conn)
        users = Table(config.PERM_TABLE, MetaData(), autoload_with=conn)
        ids = conn.execute(select(LOGIN_SESSIONS.c.sid)).scalars().all()
        for table in (users,store.ACCOUNT_STATE,store.SESSION_STATE,store.SESSION_LOCKS,LOGIN_SESSIONS,store.ATTEMPTS,store.RATE_LIMITS,store.SETTINGS):
            conn.execute(table.delete())
    disconnect_revoked(ids)
    failures = []
    for name, paths in targets.items():
        for path in paths:
            if path.is_file() and not path.is_symlink():
                try:
                    path.unlink()
                except OSError:
                    failures.append(name)
            elif path.exists() or path.is_symlink():
                failures.append(name)
    return jsonify(ok=not failures, plan=plan, failedScopes=sorted(set(failures)),
                   reprovisionRequired=True), (200 if not failures else 500)
