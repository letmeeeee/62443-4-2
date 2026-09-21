#!/usr/bin/env python3
"""Create and load persistent Session startup settings; never print the secret."""
import fcntl
import json
import os
from pathlib import Path
import secrets
import tempfile


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "instance" / "session_config.json"
DEFAULT_SESSION_SECONDS = 1800
DEFAULT_COOKIE_SECURE = True


def _validate(settings):
    disabled = settings.get("DISABLE_DEVELOPER_ACCOUNTS", True)
    accounts = settings.get("DEVELOPER_ACCOUNTS", ["trinastorage"])
    if type(disabled) is not bool or not isinstance(accounts, list) or any(
        not isinstance(name, str) or not name.strip() for name in accounts
    ):
        raise ValueError("Invalid developer account configuration")
    if disabled and not accounts:
        raise ValueError("DEVELOPER_ACCOUNTS cannot be empty when disabling developer accounts")
    secret = settings.get("FLASK_SECRET_KEY")
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError("FLASK_SECRET_KEY must contain at least 32 characters")
    seconds = settings.get("AUTH_SESSION_SECONDS")
    if type(seconds) is not int or seconds <= 0:
        raise ValueError("AUTH_SESSION_SECONDS must be a positive integer")
    if type(settings.get("SESSION_COOKIE_SECURE")) is not bool:
        raise ValueError("SESSION_COOKIE_SECURE must be true or false")


def load_session_config(path=None):
    """Environment overrides file values. Missing files are initialized once under a lock."""
    path = Path(path or os.environ.get("SESSION_CONFIG_FILE") or DEFAULT_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        exists = path.exists()
        if exists:
            with path.open(encoding="utf-8") as source:
                settings = json.load(source)
            if not isinstance(settings, dict):
                raise ValueError("Session configuration must be a JSON object")
            # Invalid files are never silently replaced, particularly their signing key.
            _validate(settings)
            os.chmod(path, 0o600)
        else:
            settings = {
                "FLASK_SECRET_KEY": secrets.token_hex(32),
                "SESSION_COOKIE_SECURE": DEFAULT_COOKIE_SECURE,
                "AUTH_SESSION_SECONDS": DEFAULT_SESSION_SECONDS,
                "DISABLE_DEVELOPER_ACCOUNTS": True,
                "DEVELOPER_ACCOUNTS": ["trinastorage"],
            }
        if "FLASK_SECRET_KEY" in os.environ:
            settings["FLASK_SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]
        if "AUTH_SESSION_SECONDS" in os.environ:
            settings["AUTH_SESSION_SECONDS"] = int(os.environ["AUTH_SESSION_SECONDS"])
        if "SESSION_COOKIE_SECURE" in os.environ:
            value = os.environ["SESSION_COOKIE_SECURE"]
            if value not in ("0", "1"):
                raise ValueError("SESSION_COOKIE_SECURE environment value must be 0 or 1")
            settings["SESSION_COOKIE_SECURE"] = value == "1"
        _validate(settings)
        if not exists:
            fd, temporary = tempfile.mkstemp(prefix=".session-", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as target:
                    json.dump(settings, target, indent=2)
                    target.write("\n")
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    return settings


def configure_session(app):
    settings = load_session_config()
    app.config["SECRET_KEY"] = settings["FLASK_SECRET_KEY"]
    app.config["AUTH_COOKIE_SECURE"] = settings["SESSION_COOKIE_SECURE"]
    app.config["AUTH_SESSION_SECONDS"] = settings["AUTH_SESSION_SECONDS"]
    app.config["DISABLE_DEVELOPER_ACCOUNTS"] = settings.get("DISABLE_DEVELOPER_ACCOUNTS", True)
    app.config["DEVELOPER_ACCOUNTS"] = settings.get("DEVELOPER_ACCOUNTS", ["trinastorage"])


if __name__ == "__main__":
    load_session_config()
    print("Session configuration ready (secret omitted).")
