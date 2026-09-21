import json
from concurrent.futures import ProcessPoolExecutor

from flask import Flask
import pytest

from script.session_config import configure_session, load_session_config


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("FLASK_SECRET_KEY", "SESSION_COOKIE_SECURE", "AUTH_SESSION_SECONDS", "SESSION_CONFIG_FILE"):
        monkeypatch.delenv(name, raising=False)


def test_first_start_and_restart(tmp_path, monkeypatch):
    path = tmp_path / "private" / "session.json"
    monkeypatch.setenv("SESSION_CONFIG_FILE", str(path))
    app = Flask(__name__)
    configure_session(app)
    assert app.config["AUTH_SESSION_SECONDS"] == 1800
    assert app.config["AUTH_COOKIE_SECURE"] is True
    assert len(app.secret_key) == 64
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_session_config()["FLASK_SECRET_KEY"] == app.secret_key


def test_file_settings_and_environment_override(tmp_path, monkeypatch):
    path = tmp_path / "session.json"
    settings = load_session_config(path)
    settings.update(AUTH_SESSION_SECONDS=3600, SESSION_COOKIE_SECURE=False)
    path.write_text(json.dumps(settings))
    assert load_session_config(path) == settings
    monkeypatch.setenv("AUTH_SESSION_SECONDS", "900")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    assert load_session_config(path)["AUTH_SESSION_SECONDS"] == 900
    assert load_session_config(path)["SESSION_COOKIE_SECURE"] is True
    assert json.loads(path.read_text()) == settings


def test_concurrent_workers_share_key(tmp_path):
    path = str(tmp_path / "session.json")
    with ProcessPoolExecutor(max_workers=3) as workers:
        settings = list(workers.map(load_session_config, [path] * 6))
    assert len({item["FLASK_SECRET_KEY"] for item in settings}) == 1


@pytest.mark.parametrize("field,value", [
    ("FLASK_SECRET_KEY", "short"), ("AUTH_SESSION_SECONDS", 0),
    ("AUTH_SESSION_SECONDS", True), ("SESSION_COOKIE_SECURE", "false"),
])
def test_invalid_file_is_preserved(tmp_path, field, value):
    path = tmp_path / "session.json"
    settings = load_session_config(path)
    settings[field] = value
    path.write_text(json.dumps(settings))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        load_session_config(path)
    assert path.read_bytes() == before
