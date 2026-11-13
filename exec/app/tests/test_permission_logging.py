"""账号接口新增排障打印：保持响应/审计语义，避免打印凭据或影响业务。"""

import sys
from unittest.mock import Mock

from sqlalchemy import text

from test_auth_session import auth_app, login
from test_security_center import security_app, post


def captured_messages(printer):
    return '\n'.join(' '.join(str(value) for value in call.args) for call in printer.call_args_list)


def test_non_json_update_logs_content_type_without_request_body(security_app):
    client = security_app[0].test_client()
    credentials = login(client).json
    printer = sys.modules['utils.utils'].DPrint
    printer.reset_mock()
    secret = 'UnparsedSecret!123'
    response = client.post(
        '/permission/update',
        data={
            'username': 'alice',
            'old_password': secret,
            'password': secret,
        },
        headers={'X-CSRF-Token': credentials['csrf_token']},
    )
    assert response.status_code == 400 and response.json['code'] == 'INVALID_JSON'
    messages = captured_messages(printer)
    assert '请求体不是有效 JSON 对象' in messages
    assert 'application/x-www-form-urlencoded' in messages
    assert secret not in messages
    assert credentials['session_token'] not in messages
    assert credentials['csrf_token'] not in messages


def test_old_password_failure_logs_reason_without_credentials(security_app):
    client = security_app[0].test_client()
    credentials = login(client).json
    printer = sys.modules['utils.utils'].DPrint
    printer.reset_mock()
    response = post(
        client,
        '/permission/update',
        credentials,
        {
            'username': 'alice',
            'old_password': 'IncorrectOld!123',
            'password': 'FreshGood!12345',
        },
    )
    assert response.status_code == 401 and response.json['code'] == 'INVALID_CREDENTIALS'
    assert response.json['attempts_remaining'] == 4
    messages = captured_messages(printer)
    assert '本人改密的旧口令验证失败' in messages
    assert 'own_account=True' in messages and 'administrator=False' in messages
    for secret in (
        'IncorrectOld!123',
        'FreshGood!12345',
        credentials['session_token'],
        credentials['csrf_token'],
    ):
        assert secret not in messages


def test_successful_password_change_preserves_audit_and_masks_secrets(security_app):
    from utils.security_audit import EVENTS
    from sqlalchemy import select

    app, engine, log = security_app
    client = app.test_client()
    credentials = login(client).json
    printer = sys.modules['utils.utils'].DPrint
    printer.reset_mock()
    response = post(
        client,
        '/permission/update',
        credentials,
        {
            'username': 'alice',
            'old_password': 'correct',
            'password': 'FreshGood!12345',
        },
    )
    assert response.status_code == 200 and response.json['sessions_revoked'] == 1
    with engine.connect() as conn:
        password, salt = conn.execute(
            text("SELECT password,salt FROM users WHERE username='alice'")
        ).one()
        event = (
            conn.execute(select(EVENTS).where(EVENTS.c.operation_type == 'account.password.change'))
            .mappings()
            .one()
        )
    assert event['operator'] == 'alice' and event['result'] == 1
    assert log.enqueue_operation_log.call_args.args[2] == 'user update'
    messages = captured_messages(printer)
    assert '账号更新完成，会话已撤销' in messages
    for secret in (
        'correct',
        'FreshGood!12345',
        password,
        salt,
        credentials['session_token'],
        credentials['csrf_token'],
    ):
        assert secret not in messages
    assert client.get('/permission/session').status_code == 401


def test_new_dprint_failure_does_not_interrupt_account_update(security_app, monkeypatch):
    client = security_app[0].test_client()
    credentials = login(client).json
    monkeypatch.setattr(
        sys.modules['utils.utils'], 'DPrint', Mock(side_effect=RuntimeError('stdout unavailable'))
    )
    response = post(
        client,
        '/permission/update',
        credentials,
        {
            'username': 'alice',
            'old_password': 'correct',
            'password': 'FreshGood!12345',
        },
    )
    assert response.status_code == 200 and response.json['sessions_revoked'] == 1
