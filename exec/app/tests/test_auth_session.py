"""Authentication integration tests; no device or external MySQL is required."""
import ast
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, g, jsonify
from sqlalchemy import create_engine, text

from utils.auth import LOGIN_SESSIONS, init_auth


@pytest.fixture
def auth_app(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE users (username TEXT PRIMARY KEY, password TEXT, salt TEXT, "
            "permission INTEGER, first_login INTEGER, password_created_at DATETIME, "
            "password_expire_at DATETIME)"
        ))
        for username, permission in (("alice", 1), ("admin", 4)):
            connection.execute(text(
                "INSERT INTO users VALUES (:name, 'hash:correct:salt', 'salt', :level, 0, NULL, NULL)"
            ), {"name": username, "level": permission})
    config = types.ModuleType("config")
    config.engine = engine
    config.PERM_TABLE = "users"
    config.HTTPS_ENABLE = True
    monkeypatch.setitem(sys.modules, "config", config)
    method = types.ModuleType("utils.method")
    method._ensure_perm_table_in_request = lambda: None
    method._perm_table_exists = lambda connection: True
    method.md5_password = lambda password, salt: "hash:" + password + ":" + salt
    method.generate_salt = lambda: "salt"
    monkeypatch.setitem(sys.modules, "utils.method", method)
    log = types.ModuleType("utils.operationLog")
    log.OperationResult = types.SimpleNamespace(SUCCESS=1, FAIL=0)
    log.OperationType = types.SimpleNamespace(USER=1)
    log.enqueue_operation_log = Mock()
    monkeypatch.setitem(sys.modules, "utils.operationLog", log)
    import utils
    monkeypatch.setattr(utils, "operationLog", log, raising=False)
    spec = importlib.util.spec_from_file_location(
        "session_test_permission", Path(__file__).parents[1] / "routes/route_permission.py")
    permission = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(permission)

    app = Flask(__name__, static_folder=str(tmp_path / "static"))
    app.config.update(TESTING=True, SECRET_KEY="test-only-secret-" * 4,
                      AUTH_COOKIE_SECURE=False)
    init_auth(app)
    app.register_blueprint(permission.permission_bp)
    for name in ("g2", "g3"):
        bp = Blueprint(name, __name__)
        bp.add_url_rule("/" + name, "protected", lambda: jsonify(g.current_user),
                        methods=["GET", "POST"])
        app.register_blueprint(bp)

    @app.route("/")
    def serve_spa():
        return "login page"

    @app.route("/future-route")
    def future_route():
        return "protected by default"

    yield app, engine, log
    engine.dispose()


def login(client, username="alice"):
    response = client.post("/permission/login", json={"username": username, "password": "correct"})
    assert response.status_code == 200
    return response


@pytest.mark.parametrize("path,method", [
    ("/g2", "GET"), ("/g3", "POST"), ("/future-route", "GET"),
    ("/permission/add", "POST"), ("/permission/delete", "POST"),
    ("/permission/update", "POST"), ("/permission/all", "POST"),
    ("/permission/session", "GET"), ("/permission/logout", "POST"),
])
def test_anonymous_requests_rejected(auth_app, path, method):
    response = auth_app[0].test_client().open(path, method=method)
    assert response.status_code == 401
    assert response.json["code"] == "SESSION_INVALID"


def test_login_and_current_identity(auth_app):
    client = auth_app[0].test_client()
    response = login(client)
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/permission/session").json["username"] == "alice"
    assert client.get("/g2").json["permission"] == 1
    assert client.get("/").status_code == 200
    assert client.options("/g2").status_code == 200


@pytest.mark.parametrize("username,password", [("alice", "wrong"), ("unknown", "correct")])
def test_failed_login_never_creates_session(auth_app, username, password):
    client = auth_app[0].test_client()
    assert client.post("/permission/login", json=dict(username=username, password=password)).status_code == 401
    assert client.get("/g2").status_code == 401
    assert auth_app[2].enqueue_operation_log.call_args.args[4] == 0


def test_csrf_and_same_origin_browser(auth_app):
    client = auth_app[0].test_client()
    token = login(client).json["csrf_token"]
    assert client.post("/g3").status_code == 403
    assert client.post("/g3", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/g3", headers={"Origin": "http://localhost"}).status_code == 200
    assert client.post("/g3", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.post("/permission/login", json={}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_logout_revokes_copied_cookie(auth_app):
    app = auth_app[0]
    client = app.test_client()
    token = login(client).json["csrf_token"]
    old_cookie = client.get_cookie("lc_session").value
    assert client.post("/permission/logout", headers={"X-CSRF-Token": token}).status_code == 200
    attacker = app.test_client()
    attacker.set_cookie("lc_session", old_cookie)
    assert attacker.get("/g2").status_code == 401


def test_relogin_rotates_and_revokes_old_cookie(auth_app):
    app = auth_app[0]
    client = app.test_client()
    login(client)
    old_cookie = client.get_cookie("lc_session").value
    login(client, "admin")
    assert client.get("/g2").json["username"] == "admin"
    attacker = app.test_client()
    attacker.set_cookie("lc_session", old_cookie)
    assert attacker.get("/g2").status_code == 401


def test_tampered_and_expired_session(auth_app):
    app = auth_app[0]
    client = app.test_client()
    login(client)
    cookie = client.get_cookie("lc_session").value
    client.set_cookie("lc_session", "tampered" + cookie)
    assert client.get("/g2").status_code == 401
    client.set_cookie("lc_session", cookie)
    with auth_app[1].begin() as connection:
        connection.execute(text("UPDATE login_sessions SET expires_at=0"))
    assert client.get("/g2").status_code == 401


@pytest.mark.parametrize("sql", [
    "DELETE FROM users WHERE username='alice'",
    "UPDATE users SET password='new-hash' WHERE username='alice'",
    "UPDATE users SET username='renamed' WHERE username='alice'",
])
def test_account_changes_invalidate_session(auth_app, sql):
    app, engine, _ = auth_app
    client = app.test_client()
    login(client)
    with engine.begin() as connection:
        connection.execute(text(sql))
    assert client.get("/g2").status_code == 401


def test_permissions_reloaded_and_audit_identity_not_spoofable(auth_app):
    app, engine, log = auth_app
    client = app.test_client()
    token = login(client).json["csrf_token"]
    with engine.begin() as connection:
        connection.execute(text("UPDATE users SET permission=2 WHERE username='alice'"))
    assert client.get("/permission/session").json["permission"] == 2
    # Delete a nonexistent target to exercise the real route without altering users.
    client.post("/permission/delete", json={"operatorName": "admin", "username": "missing"},
                headers={"X-CSRF-Token": token})
    assert log.enqueue_operation_log.call_args.args[0] == "alice"


def test_user_store_failure_fails_closed(auth_app):
    app = auth_app[0]
    client = app.test_client()
    login(client)
    app.config["AUTH_USER_LOADER"] = Mock(side_effect=RuntimeError("database unavailable"))
    assert client.get("/g2").status_code == 503


def test_session_store_failure_fails_closed(auth_app, monkeypatch):
    app, engine, _ = auth_app
    client = app.test_client()
    login(client)
    monkeypatch.setattr(engine, "begin", Mock(side_effect=RuntimeError("MySQL unavailable")))
    assert client.get("/g2").status_code == 503


def test_session_is_stored_in_account_database_and_removed_on_logout(auth_app):
    import hashlib

    app, engine, _ = auth_app
    client = app.test_client()
    token = login(client).json["csrf_token"]
    with client.session_transaction() as cookie_session:
        sid = cookie_session["sid"]
    with engine.connect() as connection:
        row = connection.execute(LOGIN_SESSIONS.select()).mappings().one()
        assert row["sid"] == hashlib.sha256(sid.encode()).hexdigest()
        assert row["username"] == "alice"
    assert client.post("/permission/logout", headers={"X-CSRF-Token": token}).status_code == 200
    with engine.connect() as connection:
        assert connection.execute(LOGIN_SESSIONS.select()).first() is None


def test_mysql_schema_and_failed_initialization(auth_app, monkeypatch):
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateTable

    ddl = str(CreateTable(LOGIN_SESSIONS, if_not_exists=True).compile(dialect=mysql.dialect()))
    assert "CREATE TABLE IF NOT EXISTS login_sessions" in ddl
    assert "VARCHAR(64)" in ddl
    assert "InnoDB" in ddl
    assert "utf8mb4" in ddl
    another_app = Flask("unavailable-database")
    another_app.config.update(auth_app[0].config)
    monkeypatch.setattr(auth_app[1], "begin", Mock(side_effect=RuntimeError("MySQL unavailable")))
    with pytest.raises(RuntimeError, match="MySQL unavailable"):
        init_auth(another_app)


def test_sessions_survive_app_restart(auth_app):
    app = auth_app[0]
    client = app.test_client()
    login(client)
    another_app = Flask("restarted")
    another_app.config.update(app.config)
    init_auth(another_app)
    another_app.add_url_rule("/protected", "protected", lambda: jsonify(g.current_user))
    another_client = another_app.test_client()
    another_client.set_cookie("lc_session", client.get_cookie("lc_session").value)
    assert another_client.get("/protected").json["username"] == "alice"


def test_missing_secret_fails_startup(monkeypatch):
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FLASK_SECRET_KEY"):
        init_auth(Flask("missing-key"))


def test_https_cookie_defaults_and_origin(auth_app, monkeypatch):
    app = auth_app[0]
    app.config.pop("AUTH_COOKIE_SECURE")
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    https_app = Flask("https-test")
    https_app.config.update(app.config)
    init_auth(https_app)
    https_app.register_blueprint(app.blueprints["permission"])
    client = https_app.test_client()
    response = client.post("/permission/login", base_url="https://localhost",
                           json={"username": "alice", "password": "correct"},
                           headers={"Origin": "https://localhost"})
    assert response.status_code == 200
    assert "Secure;" in response.headers["Set-Cookie"]
    assert client.post("/permission/logout", base_url="https://localhost",
                       headers={"Origin": "https://localhost"}).status_code == 200


def test_main_guards_all_registered_routes_and_socket_connect(auth_app, monkeypatch, tmp_path):
    """Use real main/login; replace device handlers while preserving their URL maps."""
    source = Path(__file__).parents[1]
    monkeypatch.setenv("SESSION_CONFIG_FILE", str(tmp_path / "session_config.json"))
    monkeypatch.setenv("FLASK_SECRET_KEY", auth_app[0].secret_key)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    sys.modules["config"].remote_client_lock = None
    sys.modules["config"].HOST_IP = "127.0.0.1"
    sys.modules["config"].HTTPS_ENABLE = False
    sys.modules["utils.method"].ensure_remote_connected = lambda reason: True
    for module_name, attributes in {
        "utils.utils": {"DPrint": lambda *args: None, "now_str": lambda: "now"},
        "utils.ini": {"ini_param": None},
    }.items():
        module = types.ModuleType(module_name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, module_name, module)
    for name in ("g2", "g3"):
        bp = Blueprint(name, __name__)
        tree = ast.parse((source / "routes" / ("route_" + name + ".py")).read_text())
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "route"):
                    kwargs = {item.arg: ast.literal_eval(item.value) for item in decorator.keywords}
                    bp.add_url_rule(ast.literal_eval(decorator.args[0]), node.name, lambda: "device", **kwargs)
        module = types.ModuleType("routes.route_" + name)
        setattr(module, name + "_bp", bp)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    permission_module = types.ModuleType("routes.route_permission")
    permission_module.permission_bp = auth_app[0].blueprints["permission"]
    monkeypatch.setitem(sys.modules, permission_module.__name__, permission_module)
    spec = importlib.util.spec_from_file_location("session_test_main", source / "main.py")
    main = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, main)
    spec.loader.exec_module(main)
    main.app.config["TESTING"] = True
    client = main.app.test_client()
    count = 0
    for rule in main.app.url_map.iter_rules():
        if rule.endpoint in ("static", "serve_spa", "permission.permission_login"):
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            assert client.open(rule.rule, method=method).status_code == 401, rule.rule
            count += 1
    assert count >= 40
    anonymous_socket = main.socketio.test_client(main.app, flask_test_client=client)
    assert not anonymous_socket.is_connected()
    token = login(client).json["csrf_token"]
    socket = main.socketio.test_client(main.app, flask_test_client=client)
    assert socket.is_connected()
    socket.disconnect()
    assert client.post("/permission/logout", headers={"X-CSRF-Token": token}).status_code == 200
    assert not main.socketio.test_client(main.app, flask_test_client=client).is_connected()


@pytest.fixture
def upgrade_service(auth_app, monkeypatch, tmp_path):
    """Load the actual independent service with only device dependencies stubbed."""
    monkeypatch.setenv("SESSION_CONFIG_FILE", str(tmp_path / "shared-session.json"))
    monkeypatch.setenv("FLASK_SECRET_KEY", auth_app[0].secret_key)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    config = sys.modules["config"]
    for name, value in dict(FIXED_DEVICE_ID=1, READ_INPUT_REGISTER=4,
                            UPGRADE_STATE_MAP={}, STATUS_DIR=tmp_path,
                            STATE_ERROR=5, remote_client_lock=None,
                            HOST_IP="127.0.0.1").items():
        monkeypatch.setattr(config, name, value, raising=False)
    utility = types.ModuleType("utils.utils")
    utility.DPrint = lambda *args: None
    utility.now_str = lambda: "now"
    monkeypatch.setitem(sys.modules, "utils.utils", utility)
    status_reader = Mock(return_value=(100, 2, "done"))
    monkeypatch.setattr(sys.modules["utils.method"], "get_job_upgrade_status",
                        status_reader, raising=False)
    (tmp_path / "task.json").write_text("{}")
    spec = importlib.util.spec_from_file_location(
        "session_test_upgrade", Path(__file__).parents[1] / "upgrade/upgrade.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    module.app.config["TESTING"] = True
    return module, status_reader


def test_upgrade_shares_login_and_revocation(auth_app, upgrade_service):
    module, reader = upgrade_service
    client = module.app.test_client()
    path = "/api/upgrade/process?taskName=task"
    assert client.get(path).status_code == 401
    reader.assert_not_called()
    main_client = auth_app[0].test_client()
    token = login(main_client).json["csrf_token"]
    cookie = main_client.get_cookie("lc_session").value
    client.set_cookie("lc_session", cookie)
    response = client.get(path)
    assert response.status_code == 200
    assert response.json["process"] == [100]
    assert response.headers["Cache-Control"] == "no-store"
    assert main_client.post("/permission/logout", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.get(path).status_code == 401
    assert reader.call_count == 1


@pytest.mark.parametrize("failure", ["tampered", "expired", "password", "database"])
def test_upgrade_rejects_invalid_sessions(auth_app, upgrade_service, monkeypatch, failure):
    module, reader = upgrade_service
    main_client = auth_app[0].test_client()
    login(main_client)
    cookie = main_client.get_cookie("lc_session").value
    if failure == "tampered":
        cookie = "tampered" + cookie
    elif failure in ("expired", "password"):
        with auth_app[1].begin() as connection:
            connection.execute(text("UPDATE login_sessions SET expires_at=0" if failure == "expired"
                                    else "UPDATE users SET password='changed' WHERE username='alice'"))
    else:
        monkeypatch.setattr(auth_app[1], "begin", Mock(side_effect=RuntimeError("database down")))
    client = module.app.test_client()
    client.set_cookie("lc_session", cookie)
    assert client.get("/api/upgrade/process?taskName=task").status_code == (503 if failure == "database" else 401)
    reader.assert_not_called()


def test_upgrade_socket_requires_shared_login(auth_app, upgrade_service):
    module, _ = upgrade_service
    client = module.app.test_client()
    assert not module.socketio.test_client(module.app, flask_test_client=client).is_connected()
    main_client = auth_app[0].test_client()
    token = login(main_client).json["csrf_token"]
    client.set_cookie("lc_session", main_client.get_cookie("lc_session").value)
    socket = module.socketio.test_client(module.app, flask_test_client=client)
    assert socket.is_connected()
    socket.disconnect()
    main_client.post("/permission/logout", headers={"X-CSRF-Token": token})
    assert not module.socketio.test_client(module.app, flask_test_client=client).is_connected()


def test_developer_account_disabled_at_startup(auth_app):
    from utils.auth import init_developer_accounts

    app, engine, log = auth_app
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users VALUES ('trinastorage', 'hash:correct:salt', 'salt', 4, 0, NULL, NULL)"
        ))
    developer = app.test_client()
    personal = app.test_client()
    login(developer, "trinastorage")
    login(personal, "admin")
    app.config.update(DISABLE_DEVELOPER_ACCOUNTS=True, DEVELOPER_ACCOUNTS=["trinastorage"])
    init_developer_accounts(app)
    assert developer.get("/g2").status_code == 401
    assert personal.get("/g2").status_code == 200
    response = developer.post("/permission/login", json={"username": "trinastorage", "password": "correct"})
    assert response.status_code == 401
    assert log.enqueue_operation_log.call_args.args[4] == 0
    with engine.connect() as connection:
        assert connection.execute(LOGIN_SESSIONS.select().where(
            LOGIN_SESSIONS.c.username == "trinastorage")).first() is None
    app.config["DISABLE_DEVELOPER_ACCOUNTS"] = False
    init_developer_accounts(app)
    # Re-enabling does not restore the revoked session.
    assert developer.get("/g2").status_code == 401
    login(developer, "trinastorage")


def test_disabled_policy_checked_by_user_loader(auth_app):
    from utils.auth import load_user
    app = auth_app[0]
    client = app.test_client()
    login(client, "admin")
    app.extensions["disabled_developer_accounts"] = frozenset(["admin"])
    with app.app_context():
        assert load_user("admin")["disabled"] is True
    assert client.get("/g2").status_code == 401
