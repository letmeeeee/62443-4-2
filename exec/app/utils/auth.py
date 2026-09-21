"""Flask signed cookie + persistent, revocable server-side login sessions."""
import hashlib
import hmac
import os
import secrets
import time
from contextlib import contextmanager
from datetime import timedelta
from urllib.parse import urlsplit

from flask import current_app, g, jsonify, request, session
from sqlalchemy import Column, Float, MetaData, String, Table
from sqlalchemy.schema import CreateTable


LOGIN_SESSIONS = Table(
    "login_sessions", MetaData(),
    Column("sid", String(64), primary_key=True),
    Column("username", String(64), nullable=False),
    Column("credential", String(64), nullable=False),
    Column("expires_at", Float(precision=53), nullable=False),
    Column("csrf_token", String(64), nullable=False),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)


@contextmanager
def _store():
    # Reuse the same MySQL engine/pool as the account table.
    import config

    with config.engine.begin() as connection:
        yield connection


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def init_developer_accounts(app):
    """Load explicit account policy and revoke their existing sessions at startup."""
    enabled = app.config.get("DISABLE_DEVELOPER_ACCOUNTS", False)
    accounts = app.config.get("DEVELOPER_ACCOUNTS", [])
    if type(enabled) is not bool or not isinstance(accounts, list) or any(
        not isinstance(name, str) or not name.strip() for name in accounts
    ):
        raise ValueError("Invalid developer account configuration")
    if enabled and not accounts:
        raise ValueError("DEVELOPER_ACCOUNTS cannot be empty when disabling developer accounts")
    blocked = frozenset(name.strip().casefold() for name in accounts) if enabled else frozenset()
    app.extensions["disabled_developer_accounts"] = blocked
    if blocked:
        with app.app_context(), _store() as connection:
            # Normalize in Python, consistently with the checks below.
            names = connection.execute(LOGIN_SESSIONS.select()).mappings().all()
            sids = [row["sid"] for row in names if row["username"].casefold() in blocked]
            if sids:
                connection.execute(LOGIN_SESSIONS.delete().where(LOGIN_SESSIONS.c.sid.in_(sids)))


def is_developer_account_disabled(username):
    return username.casefold() in current_app.extensions.get("disabled_developer_accounts", ())


def load_user(username):
    # Lazy imports keep authentication infrastructure independent of device startup.
    from sqlalchemy import text
    import config

    with config.engine.connect() as connection:
        row = connection.execute(text(
            f"SELECT username, password, salt, permission FROM `{config.PERM_TABLE}` "
            "WHERE username=:username"
        ), {"username": username}).fetchone()
    if row is None:
        return None
    return {
        "username": row[0], "permission": int(row[3]),
        "credential": _digest(row[1] + ":" + row[2]),
        "disabled": is_developer_account_disabled(row[0]),
    }


def revoke_session():
    sid = session.get("sid")
    if isinstance(sid, str):
        with _store() as connection:
            connection.execute(LOGIN_SESSIONS.delete().where(LOGIN_SESSIONS.c.sid == _digest(sid)))
    session.clear()


def establish_session(username, password_hash, salt):
    """Call only after successful password verification. Rotate existing session."""
    revoke_session()
    sid = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = time.time() + current_app.permanent_session_lifetime.total_seconds()
    with _store() as connection:
        connection.execute(LOGIN_SESSIONS.delete().where(LOGIN_SESSIONS.c.expires_at <= time.time()))
        connection.execute(LOGIN_SESSIONS.insert().values(
            sid=_digest(sid), username=username,
            credential=_digest(password_hash + ":" + salt),
            expires_at=expires_at, csrf_token=csrf_token,
        ))
    session["sid"] = sid
    session.permanent = True
    return csrf_token


def authenticate_session():
    sid = session.get("sid")
    if not isinstance(sid, str):
        return False
    with _store() as connection:
        row = connection.execute(
            LOGIN_SESSIONS.select().where(LOGIN_SESSIONS.c.sid == _digest(sid))
        ).mappings().first()
    if row is None or row["expires_at"] <= time.time():
        revoke_session()
        return False
    user = current_app.config["AUTH_USER_LOADER"](row["username"])
    if (user is None or user.get("disabled", False)
            or not hmac.compare_digest(user["credential"], row["credential"])):
        revoke_session()
        return False
    g.current_user = user
    g.csrf_token = row["csrf_token"]
    return True


def _same_origin():
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        scheme = "https" if current_app.config["SESSION_COOKIE_SECURE"] else request.scheme
        return (parsed.scheme, parsed.netloc) == (scheme, request.host)
    return request.headers.get("Sec-Fetch-Site") == "same-origin"


def init_auth(app):
    secret = app.config.get("SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY")
    if not secret or len(secret) < 32:
        raise RuntimeError("Set FLASK_SECRET_KEY to a persistent random secret of at least 32 characters")
    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_NAME="lc_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=app.config.get(
            "AUTH_COOKIE_SECURE", os.environ.get("SESSION_COOKIE_SECURE", "1") != "0"),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_REFRESH_EACH_REQUEST=False,
        PERMANENT_SESSION_LIFETIME=timedelta(seconds=int(
            app.config.get("AUTH_SESSION_SECONDS", os.environ.get("AUTH_SESSION_SECONDS", "1800")))),
    )
    if app.permanent_session_lifetime.total_seconds() <= 0:
        raise ValueError("AUTH_SESSION_SECONDS must be positive")
    app.config.setdefault("AUTH_USER_LOADER", load_user)
    # IF NOT EXISTS also permits simultaneous worker startup. DDL errors abort startup.
    with app.app_context(), _store() as connection:
        connection.execute(CreateTable(LOGIN_SESSIONS, if_not_exists=True))
    init_developer_accounts(app)

    @app.before_request
    def check_session():
        # Only the SPA, static assets, and login are public. New routes are protected by default.
        if request.endpoint in (None, "static", "serve_spa"):
            return None
        if request.method == "OPTIONS":
            return app.make_default_options_response()
        if request.endpoint == "permission.permission_login":
            if (request.headers.get("Origin") or request.headers.get("Referer")
                    or request.headers.get("Sec-Fetch-Site")) and not _same_origin():
                return jsonify(ok=False, error="Cross-origin login denied"), 403
            return None
        try:
            if not authenticate_session():
                return jsonify(ok=False, error="Authentication required", code="SESSION_INVALID"), 401
        except Exception:
            app.logger.exception("Session verification failed")
            return jsonify(ok=False, error="Authentication service unavailable"), 503
        if request.method not in ("GET", "HEAD") and not _same_origin():
            token = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(token.encode("utf-8"), g.csrf_token.encode("utf-8")):
                return jsonify(ok=False, error="CSRF validation failed"), 403

    @app.after_request
    def prevent_auth_caching(response):
        if request.endpoint not in (None, "static", "serve_spa"):
            response.headers["Cache-Control"] = "no-store"
        return response
