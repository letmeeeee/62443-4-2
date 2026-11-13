"""具名设备接口集成测试：真实 Flask 认证/审计，寄存器与设备写入使用替身。"""
import ast
import json
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from constent import common
from test_auth_session import auth_app, login
from test_security_center import security_app, post


@pytest.fixture
def named_app(security_app):
    """仅加载新增接口，避免导入主业务模块时初始化共享内存及 MySQL。"""
    path = Path(__file__).parents[1] / 'routes/route_g3.py'
    tree = ast.parse(path.read_text())
    names = {
        'NamedDeviceError', '_query_error', '_named_device_permission',
        '_named_device_counts', '_named_device_indices', '_named_device_read',
        '_named_device_success', '_named_device_failure', 'get_pcs_verify',
        'get_pcs_firmware_versions', 'get_system_versions', 'get_pcs_charge_state',
        'set_system_time', '_format_pcs_firmware_version',
    }
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    bp = Blueprint('named_device_test', __name__)
    registers = {}

    def read_registers(deviceid, functioncode, address, quantity):
        return [registers.get((functioncode, address + offset), 0) for offset in range(quantity)]

    scope = dict(
        g3_bp=bp, g=g, request=request, jsonify=jsonify, datetime=datetime, common=common,
        threading=threading, time=time, traceback=traceback,
        DPrint=Mock(), READ_INPUT_REGISTER=4, READ_HOLD_REGISTER=3, FIXED_DEVICE_ID=1,
        SYSTEM_TIME_WRITE_LOCK=threading.Lock(),
        PERMISSION_TABLE={'data': [1, 2, 3, 4], 'param': [2, 3, 4]},
        read_ini_all=Mock(return_value={'SYSTEM': {'pcsNum': '4', 'sysNum': '2'}}),
        _ini_get_int=lambda data, section, key, default=0: int(data.get(section, {}).get(key, default)),
        method=SimpleNamespace(registers_model=SimpleNamespace(INPUT_SIZE=65536, HOLD_SIZE=65536)),
        query_register_data=Mock(side_effect=read_registers),
        write_register_with_retry=Mock(return_value=(SimpleNamespace(isError=lambda: False), 1)),
    )
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    app, engine, log = security_app
    app.register_blueprint(bp)
    return app, engine, scope, registers


def admin_client(named_app):
    client = named_app[0].test_client()
    return client, login(client, 'admin').json


def test_verify_decodes_all_four_pcs_and_two_groups(named_app):
    client, _ = admin_client(named_app)
    registers = named_app[3]
    for pcs, standard, role in ((1, 3, 1), (2, 6, 0), (3, 99, 2), (4, 0, 0)):
        registers[3, 12100 + (pcs - 1) * 700] = standard
        registers[3, 12009 + (pcs - 1) * 700] = role
    registers.update({(4, 17060): 0, (4, 17062): 1 << 14, (4, 17064): (1 << 5) | 4,
                      (4, 17360): 1 << 9, (4, 17362): 0, (4, 17364): 3})
    response = client.get('/api/device/pcs/verify?pcs=1,2,3,4&groups=1,2')
    assert response.status_code == 200
    payload = response.json
    assert payload['ok'] and datetime.fromisoformat(payload['sampledAt']).tzinfo is not None
    assert [row['name'] for row in payload['data']['standards']] == ['G99', 'UL_1547', None, 'VDE_AR_N_4110']
    assert [row['role'] for row in payload['data']['masterSlave']] == ['master', 'slave', 'unknown', 'slave']
    groups = payload['data']['groups']
    assert groups[0] == {
        'group': 1,
        'parallelMode': [{'pcs': 1, 'mode': 'single_bus'}, {'pcs': 2, 'mode': 'double_bus'}],
        'gridMode': 'off_grid', 'runMode': 'volt_var',
    }
    assert groups[1]['parallelMode'] == [{'pcs': 3, 'mode': 'double_bus'}, {'pcs': 4, 'mode': 'single_bus'}]
    assert groups[1]['gridMode'] == 'grid_connected' and groups[1]['runMode'] == 'none'
    assert named_app[2]['query_register_data'].call_count == 10


def test_verify_respects_selected_indices_and_configured_counts(named_app):
    client, _ = admin_client(named_app)
    scope = named_app[2]
    scope['read_ini_all'].return_value = {'SYSTEM': {'pcsNum': '1', 'sysNum': '1'}}
    result = client.get('/api/device/pcs/verify?pcs=1&groups=1')
    assert result.status_code == 200
    assert len(result.json['data']['standards']) == 1
    assert result.json['data']['groups'][0]['parallelMode'] == [{'pcs': 1, 'mode': 'single_bus'}]
    scope['query_register_data'].reset_mock()
    assert client.get('/api/device/pcs/verify?pcs=2&groups=1').status_code == 400
    scope['query_register_data'].assert_not_called()


@pytest.mark.parametrize('query', ['pcs=1,1,5&groups=1', 'pcs=1,1&groups=1', 'pcs=0&groups=1',
                                   'pcs=5&groups=1', 'pcs=1&groups=3', 'pcs=1,&groups=1',
                                   'pcs=abc&groups=1', 'pcs=1&pcs=2&groups=1', 'groups=1', 'pcs=1'])
def test_invalid_indices_fail_before_register_access(named_app, query):
    client, _ = admin_client(named_app)
    response = client.get('/api/device/pcs/verify?' + query)
    assert response.status_code == 400 and response.json['code'] == 'INVALID_DEVICE_INDEX'
    assert response.headers['X-Trace-Id'] == response.json['trace_id']
    named_app[2]['query_register_data'].assert_not_called()


@pytest.mark.parametrize('path,expected', [
    ('/api/device/pcs/verify?pcs=&groups=', {'standards': [], 'groups': [], 'masterSlave': []}),
    ('/api/device/pcs/versions?pcs=', []),
    ('/api/device/pcs/charge-state?groups=', {'chargeDischarging': False, 'groups': []}),
])
def test_empty_indices_do_not_access_registers(named_app, path, expected):
    client, _ = admin_client(named_app)
    response = client.get(path)
    assert response.status_code == 200 and response.json['data'] == expected
    named_app[2]['query_register_data'].assert_not_called()


def test_firmware_versions_decode_eight_words_and_offsets(named_app):
    client, _ = admin_client(named_app)
    registers = named_app[3]
    words = [100, 205 | (1 << 10) | (1 << 13), 1023 | (7 << 10) | (2 << 13),
             0, 1, 99, 1000, 100 | (3 << 13)]
    for pcs in (1, 4):
        for offset, word in enumerate(words):
            registers[4, 2604 + (pcs - 1) * 300 + offset] = word
    result = client.get('/api/device/pcs/versions?pcs=1,4')
    assert result.status_code == 200
    rows = result.json['data']
    assert [row['pcs'] for row in rows] == [1, 4]
    for row in rows:
        assert [c['name'] for c in row['components']] == [
            'controller', 'sdsp', 'sfpga', 'cdsp', 'j1dsp', 'j1fpga', 'j2dsp', 'j2fpga']
        assert [c['version'] for c in row['components']] == [
            'V1.00-0-M', 'V2.05-1-P', 'V10.23-7-V', 'V0.00-0-M',
            'V0.01-0-M', 'V0.99-0-M', 'V10.00-0-M', 'V1.00-0-RESERVED_3']
    calls = named_app[2]['query_register_data'].call_args_list
    assert [(call.kwargs['functioncode'], call.kwargs['address'], call.kwargs['quantity'])
            for call in calls] == [(4, 2604, 8), (4, 3504, 8)]


@pytest.mark.parametrize('word,expected', [
    (100, 'V1.00-0-M'),
    (205 | (1 << 10), 'V2.05-1-M'),
    (100 | (1 << 13), 'V1.00-0-P'),
    (100 | (2 << 13), 'V1.00-0-V'),
    (65535, 'V10.23-7-RESERVED_7'),
])
def test_firmware_version_bitfields(named_app, word, expected):
    client, _ = admin_client(named_app)
    named_app[3][4, 2604] = word
    result = client.get('/api/device/pcs/versions?pcs=1')
    assert result.status_code == 200
    assert result.json['data'][0]['components'][0]['version'] == expected


def test_system_version_formats_and_zero_pcs_version_is_null(named_app):
    client, _ = admin_client(named_app)
    named_app[3].update({(4, 1): 16, (4, 2): 1, (4, 3): 2, (4, 4): 3, (4, 5): 7,
                        (4, 2604): 205 | (1 << 10) | (1 << 13)})
    result = client.get('/api/system/versions')
    assert result.status_code == 200
    assert result.json['data'] == {
        'protocolVersion': 'V0.16', 'softwareVersion': 'V01R02C03', 'patchNumber': 'SPC007',
        'pcs': [{'pcs': 1, 'version': 'V2.05-1-P'}, {'pcs': 2, 'version': None},
                {'pcs': 3, 'version': None}, {'pcs': 4, 'version': None}],
    }


@pytest.mark.parametrize('words,state,active', [((0, 0), 'idle', False), ((1, 0), 'discharge', True),
                                               ((0, 2), 'charge', True), ((1, 2), 'unknown', True),
                                               ((1, 1), 'discharge', True), ((9, 9), 'idle', False)])
def test_charge_state_is_conservative_for_conflicting_states(named_app, words, state, active):
    client, _ = admin_client(named_app)
    named_app[3].update({(4, 17032): words[0], (4, 17033): words[1]})
    response = client.get('/api/device/pcs/charge-state?groups=1')
    assert response.status_code == 200
    assert response.json['data'] == {'chargeDischarging': active, 'groups': [{'group': 1, 'state': state}]}


@pytest.mark.parametrize('returned', [None, [], [1], [None, 0], [True, 0], [-1, 0], [65536, 0], [1.5, 0]])
def test_invalid_register_data_is_not_filled_with_zero(named_app, returned):
    client, _ = admin_client(named_app)
    named_app[2]['query_register_data'].side_effect = None
    named_app[2]['query_register_data'].return_value = returned
    response = client.get('/api/device/pcs/charge-state?groups=1')
    assert response.status_code == 503 and response.json['code'] == 'DEVICE_UNAVAILABLE'
    assert 'data' not in response.json


def test_register_timeout_has_specific_code(named_app):
    client, _ = admin_client(named_app)
    named_app[2]['query_register_data'].side_effect = TimeoutError('private connection details')
    response = client.get('/api/device/pcs/verify?pcs=1&groups=1')
    assert response.status_code == 503 and response.json['code'] == 'MODBUS_TIMEOUT'
    assert 'private connection details' not in response.get_data(as_text=True)


@pytest.mark.parametrize('path', ['/api/device/pcs/verify?pcs=1&groups=1', '/api/device/pcs/versions?pcs=1',
                                 '/api/system/versions', '/api/device/pcs/charge-state?groups=1,2'])
def test_anonymous_reads_are_rejected(named_app, path):
    assert named_app[0].test_client().get(path).status_code == 401
    named_app[2]['query_register_data'].assert_not_called()


def test_visitor_can_read_status_but_not_firmware_versions_or_write_time(named_app):
    client = named_app[0].test_client()
    credentials = login(client).json
    assert client.get('/api/device/pcs/verify?pcs=1&groups=1').status_code == 200
    assert client.get('/api/system/versions').status_code == 200
    assert client.get('/api/device/pcs/charge-state?groups=1').status_code == 200
    assert client.get('/api/device/pcs/versions?pcs=1').status_code == 403
    assert post(client, '/api/system/time', credentials,
                {'datetime': '2026-11-10 12:00:00', 'confirm': 'SET_SYSTEM_TIME'}).status_code == 403
    named_app[2]['write_register_with_retry'].assert_not_called()


@pytest.mark.parametrize('body,code', [
    ([], 'INVALID_QUERY'), ({}, 'SET_TIME_CONFIRMATION_REQUIRED'),
    ({'confirm': 'wrong'}, 'SET_TIME_CONFIRMATION_REQUIRED'),
    ({'confirm': 'SET_SYSTEM_TIME'}, 'SYSTEM_TIME_INVALID'),
    ({'confirm': 'SET_SYSTEM_TIME', 'datetime': '2026-11-10T12:34:56'}, 'SYSTEM_TIME_INVALID'),
    ({'confirm': 'SET_SYSTEM_TIME', 'datetime': '2026-02-29 12:34:56'}, 'SYSTEM_TIME_INVALID'),
    ({'confirm': 'SET_SYSTEM_TIME', 'datetime': '1999-12-31 23:59:59'}, 'SYSTEM_TIME_INVALID'),
    ({'confirm': 'SET_SYSTEM_TIME', 'datetime': '2100-01-01 00:00:00'}, 'SYSTEM_TIME_INVALID'),
])
def test_invalid_time_never_writes_registers(named_app, body, code):
    client, credentials = admin_client(named_app)
    response = post(client, '/api/system/time', credentials, body)
    assert response.status_code == 400 and response.json['code'] == code
    named_app[2]['write_register_with_retry'].assert_not_called()


@pytest.mark.parametrize('token', [None, 'WRONG-TOKEN'])
def test_time_write_requires_csrf_even_for_same_origin(named_app, token):
    client, _ = admin_client(named_app)
    headers = {'Origin': 'http://localhost'}
    if token is not None:
        headers['X-CSRF-Token'] = token
    response = client.post('/api/system/time', json={
        'datetime': '2026-11-10 12:34:56', 'confirm': 'SET_SYSTEM_TIME'}, headers=headers)
    assert response.status_code == 403 and response.json['code'] == 'CSRF_INVALID'
    named_app[2]['write_register_with_retry'].assert_not_called()


def test_time_write_is_six_fc6_writes_with_audit_snapshots(named_app):
    from utils.security_audit import EVENTS
    client, credentials = admin_client(named_app)
    response = post(client, '/api/system/time', credentials, {
        'datetime': '2028-02-29 12:34:56', 'confirm': 'SET_SYSTEM_TIME', 'operatorName': 'forged'})
    assert response.status_code == 200
    assert response.json == {'ok': True, 'applied': True, 'reboot_scheduled_in': None}
    calls = named_app[2]['write_register_with_retry'].call_args_list
    assert [call.args for call in calls] == [(1500, 2028), (1501, 2), (1502, 29), (1503, 12), (1504, 34), (1505, 56)]
    assert all(call.kwargs == {'slave': 1} for call in calls)
    with named_app[1].connect() as conn:
        event = conn.execute(select(EVENTS).where(EVENTS.c.operation_type == 'system.time.set')).mappings().one()
    assert event['operator'] == 'admin' and event['result'] == 1
    assert json.loads(event['before_summary'])['datetime']
    after = json.loads(event['after_summary'])
    assert after['datetime'] == '2028-02-29 12:34:56' and after['applied']
    assert after['writtenRegisters'] == list(range(1500, 1506))


def test_time_write_stops_on_failure_and_audits_partial_progress(named_app):
    from utils.security_audit import EVENTS
    client, credentials = admin_client(named_app)
    named_app[2]['write_register_with_retry'].side_effect = [
        (SimpleNamespace(isError=lambda: False), 1), (None, 2)]
    response = post(client, '/api/system/time', credentials, {
        'datetime': '2026-11-10 12:34:56', 'confirm': 'SET_SYSTEM_TIME'})
    assert response.status_code == 503 and response.json['code'] == 'DEVICE_UNAVAILABLE'
    assert named_app[2]['write_register_with_retry'].call_count == 2
    with named_app[1].connect() as conn:
        event = conn.execute(select(EVENTS).where(EVENTS.c.operation_type == 'system.time.set')).mappings().one()
    assert event['result'] == 0
    after = json.loads(event['after_summary'])
    assert after['writtenRegisters'] == [1500] and after['applied'] is False


def test_maintenance_blocks_time_writes_but_allows_reads(named_app):
    client, credentials = admin_client(named_app)
    entered = post(client, '/api/security/maintenance', credentials, {
        'enabled': True, 'confirm': 'ENTER_MAINTENANCE', 'password': 'correct'})
    assert entered.status_code == 200
    response = post(client, '/api/system/time', credentials, {
        'datetime': '2026-11-10 12:34:56', 'confirm': 'SET_SYSTEM_TIME'})
    assert response.status_code == 409 and response.json['code'] == 'MAINTENANCE_IN_PROGRESS'
    named_app[2]['write_register_with_retry'].assert_not_called()
    assert client.get('/api/system/versions').status_code == 200


@pytest.mark.parametrize('word', [100, 205 | (1 << 10) | (1 << 13), 1023 | (7 << 10) | (2 << 13), 65535])
def test_system_pcs_version_matches_firmware_controller(named_app, word):
    client, _ = admin_client(named_app)
    named_app[3][4, 2604] = word
    system = client.get('/api/system/versions')
    firmware = client.get('/api/device/pcs/versions?pcs=1')
    assert system.status_code == firmware.status_code == 200
    assert system.json['data']['pcs'][0]['version'] == firmware.json['data'][0]['components'][0]['version']
