"""Bilingual notice persistence, legacy fallback and version conflict coverage."""
import pytest

from test_auth_session import auth_app, login
from test_security_center import security_app, post
from utils import security_store as store


def test_bilingual_notice_persists_and_english_changes_share_version(security_app):
    app, engine, _ = security_app
    admin = app.test_client()
    credentials = login(admin, 'admin').json
    initial = admin.get('/permission/login-notice').json
    assert initial['text_en']
    body = dict(enabled=True, text='仅限授权人员使用。', text_en='Authorized users only.',
                expectedVersion=initial['version'])
    saved = post(admin, '/permission/login-notice', credentials, body)
    assert saved.status_code == 200
    with engine.connect() as conn:
        stored = store.get_setting(conn, 'login_notice', {})
    assert stored['text_en'] == body['text_en'] and stored['text'] == body['text']
    public = app.test_client().get('/permission/login-notice').json
    assert public['text_en'] == body['text_en'] and public['version'] == saved.json['version']
    body['expectedVersion'] = saved.json['version']
    assert post(admin, '/permission/login-notice', credentials, body).json['version'] == body['expectedVersion']
    body['text_en'] = 'Authorized personnel only.'
    changed = post(admin, '/permission/login-notice', credentials, body)
    assert changed.json['version'] == body['expectedVersion'] + 1
    # A stale form must not overwrite either language.
    assert post(admin, '/permission/login-notice', credentials, body).status_code == 409
    assert app.test_client().get('/permission/login-notice').json['text_en'] == body['text_en']


def test_legacy_custom_notice_does_not_get_an_unrelated_default_translation(security_app):
    app, engine, _ = security_app
    with engine.begin() as conn:
        store.set_setting(conn, 'login_notice', dict(enabled=False, text='现场专用提示', version=7))
    notice = app.test_client().get('/permission/login-notice').json
    assert notice['text'] == '现场专用提示' and notice['text_en'] == '' and notice['version'] == 7
    with engine.connect() as conn:
        assert 'text_en' not in store.get_setting(conn, 'login_notice', {})


def test_legacy_updates_preserve_english_only_when_chinese_is_unchanged(security_app):
    app = security_app[0]
    client = app.test_client()
    credentials = login(client, 'admin').json
    saved = post(client, '/permission/login-notice', credentials,
                 dict(enabled=True, text='专用提示', text_en='Site-specific notice.')).json
    toggled = post(client, '/permission/login-notice', credentials,
                   dict(enabled=False, text=saved['text'])).json
    assert toggled['text_en'] == saved['text_en'] and toggled['version'] == saved['version'] + 1
    edited = post(client, '/permission/login-notice', credentials,
                  dict(enabled=False, text='更新后的专用提示')).json
    assert edited['text_en'] == '' and edited['version'] == toggled['version'] + 1


@pytest.mark.parametrize('english', [None, 123, True, [], {}, 'x' * 4001])
def test_invalid_english_does_not_change_notice(security_app, english):
    client = security_app[0].test_client()
    credentials = login(client, 'admin').json
    before = client.get('/permission/login-notice').json
    response = post(client, '/permission/login-notice', credentials,
                    dict(enabled=True, text=before['text'], text_en=english))
    assert response.status_code == 400 and response.json['code'] == 'INVALID_NOTICE'
    assert client.get('/permission/login-notice').json == before


def test_empty_english_is_supported_and_low_role_cannot_change_either_language(security_app):
    app = security_app[0]
    admin = app.test_client()
    credentials = login(admin, 'admin').json
    saved = post(admin, '/permission/login-notice', credentials,
                 dict(enabled=True, text='仅中文提示', text_en=''))
    assert saved.status_code == 200 and saved.json['text_en'] == ''
    user = app.test_client()
    credentials = login(user).json
    assert post(user, '/permission/login-notice', credentials,
                dict(enabled=False, text='恶意修改', text_en='Modified')).status_code == 403
    assert app.test_client().get('/permission/login-notice').json['text'] == '仅中文提示'
