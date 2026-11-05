"""Server-side capabilities shared with the security-center role matrix."""
from flask import g, request

ABILITIES = {
    'account:manage': [4], 'role:read': [4], 'audit:read': [3, 4],
    'audit:export': [3, 4], 'param:write': [2, 3, 4],
    'device:control': [2, 3, 4], 'device:upgrade': [3, 4],
    'cert:manage': [4], 'backup:manage': [4], 'decommission': [4],
    'maintenance:enter': [4], 'security:read': [3, 4],
}


def allowed(ability):
    return g.current_user['permission'] in ABILITIES[ability]


def request_ability():
    path = request.path
    if path == '/api' and request.method == 'POST':
        data = request.get_json(silent=True) or {}
        codes = str(data.get('functioncode', '')).split(',') if isinstance(data, dict) else []
        return 'param:write' if any(int(code) == 6 for code in codes) else None
    if path in ('/permission/add', '/permission/delete', '/permission/all',
                '/permission/reset-password', '/permission/sessions', '/permission/sessions/revoke'):
        return 'account:manage'
    if path == '/permission/login-notice' and request.method != 'GET':
        return 'account:manage'
    if path.startswith('/api/cert/') or path.startswith('/api/security/certificates'):
        return 'cert:manage'
    if path == '/api/security/keys':
        return 'cert:manage'
    if path.startswith('/api/security/backups') or path == '/api/security/factory-reset':
        return 'backup:manage'
    if path == '/api/security/decommission':
        return 'decommission'
    if path == '/api/security/roles':
        return 'role:read'
    if path == '/api/security/maintenance' and request.method == 'POST':
        return 'maintenance:enter'
    if path.startswith('/api/history/'):
        return 'audit:export' if path.endswith('/export') else 'audit:read'
    if path == '/export_csv_stream':
        return 'audit:export'
    if path in ('/ini/update', '/network/set_ip', '/ini/system_counts') and request.method == 'POST':
        return 'param:write'
    if path == '/api/paraConfig/modifyParams':
        return 'param:write'
    if path in ('/system/reboot', '/status/update'):
        return 'device:control'
    if path in ('/fault_wave/diag', '/sqlite/count_rows', '/sqlite/query_series', '/zlog/query_series'):
        return 'security:read'
    if path.startswith('/api/security/') and path != '/api/security/password-policy':
        return 'security:read'
    return None


def validate_protocol_request():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return 'INVALID_JSON'
    try:
        if any(not isinstance(data.get(key), str) or len(data[key]) > 1000 for key in
               ('deviceid','functioncode','Address','Quantity')):
            return 'INVALID_PROTOCOL_FIELD'
        if 'value' in data and (not isinstance(data['value'],str) or len(data['value'])>1000):
            return 'INVALID_WRITE_VALUE'
        fields = {key: [int(value) for value in str(data[key]).split(',')]
                  for key in ('deviceid','functioncode','Address','Quantity')}
        count = len(fields['deviceid'])
        if not 1 <= count <= 100 or any(len(value) != count for value in fields.values()):
            return 'INVALID_BATCH_SIZE'
        values = [int(value) for value in str(data.get('value','0')).split(',')]
        for i in range(count):
            device, code, address, quantity = (fields[key][i] for key in
                ('deviceid','functioncode','Address','Quantity'))
            if not 1 <= device <= 247 or code not in (3,4,6) or not 0 <= address <= 65535:
                return 'INVALID_PROTOCOL_FIELD'
            if not 1 <= quantity <= 125 or address + quantity > 65536:
                return 'INVALID_REGISTER_RANGE'
            if code == 6 and (quantity != 1 or len(values) != count or not -32768 <= values[i] <= 65535):
                return 'INVALID_WRITE_VALUE'
    except (KeyError, TypeError, ValueError):
        return 'INVALID_PROTOCOL_FIELD'
    return None
