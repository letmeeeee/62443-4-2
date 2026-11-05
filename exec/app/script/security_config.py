"""Optional deployment settings; no destructive operation is enabled by default."""
import json
import os
from pathlib import Path

DEFAULTS = dict(AUTH_IDLE_SECONDS=900, AUDIT_RETENTION_DAYS=180,
    # Legacy key accepted for deployment-file compatibility; disk telemetry supersedes it.
    AUDIT_CAPACITY_BYTES=256*1024*1024, SECURITY_ALLOW_DESTRUCTIVE=False,
    SECURITY_DISK_PATH='/', TRUST_LOOPBACK_PROXY=True, HTTP_REQUESTS_PER_MINUTE=3000)
PATHS = {'SECURITY_STATE_DIR','SECURITY_DISK_PATH','MODBUS_CERT_DIR','HTTPS_CERT_DIR','COMPONENT_MANIFEST'}
STRINGS = {'SECURITY_DEVICE_ID','SECURITY_FACTORY_BACKUP_ID','SECURITY_FACTORY_BACKUP_SHA256'}


def configure_security(app):
    source = os.environ.get('SECURITY_CONFIG_FILE')
    values = json.loads(Path(source).read_text()) if source else {}
    if not isinstance(values, dict) or set(values) - (set(DEFAULTS) | PATHS | STRINGS):
        raise ValueError('Invalid security configuration keys')
    settings = dict(DEFAULTS, **values)
    for key in ('AUTH_IDLE_SECONDS','AUDIT_RETENTION_DAYS','AUDIT_CAPACITY_BYTES','HTTP_REQUESTS_PER_MINUTE'):
        if type(settings[key]) is not int or settings[key] <= 0:
            raise ValueError(key+' must be a positive integer')
    for key in ('SECURITY_ALLOW_DESTRUCTIVE','TRUST_LOOPBACK_PROXY'):
        if type(settings[key]) is not bool:
            raise ValueError(key+' must be boolean')
    for key in PATHS & settings.keys():
        if not isinstance(settings[key], str) or not Path(settings[key]).is_absolute():
            raise ValueError(key+' must be an absolute path')
    for key in STRINGS & settings.keys():
        if not isinstance(settings[key], str) or not settings[key]:
            raise ValueError(key+' must be a nonempty string')
    app.config.update(settings)
    root = Path(settings.get('SECURITY_STATE_DIR', str(Path(__file__).resolve().parents[2] / 'instance' / 'security')))
    if (root / 'recovery' / 'pending.json').exists():
        raise RuntimeError('Pending security restore: perform local recovery before starting the service')
