#!/usr/bin/env python3
from flask import request, jsonify, Blueprint
from sqlalchemy import text
from config import PERM_TABLE, engine
from utils.method import _ensure_perm_table_in_request, _perm_table_exists, md5_password, generate_salt
import config
import utils.operationLog as operationLog
from datetime import datetime, timedelta

permission_bp = Blueprint("permission", __name__)
# ================== 权限管理 API ==================
@permission_bp.route("/permission/login", methods=["POST"])
def permission_login():
    """
    登录校验：
    请求：
    {
        "username": "用户名",
        "password": "密码"
    }

    返回：
    - ok
    - db_status
    - username
    - permission
    - first_login
    - password_warning      是否进入密码到期提醒期
    - password_expired      密码是否已经过期
    - password_expire_at    密码过期时间
    - password_days_left    密码剩余天数
    - message               提示信息

    说明：
    - 密码过期后不重置密码
    - 密码过期后不修改数据库中的密码字段
    - 密码过期后仍允许登录
    - 前端根据 password_expired 判断是否强制跳转修改密码页面
    """
    _target = "user login"
    _result = operationLog.OperationResult.FAIL
    remark = ""
    operatorName = ""
    err = _ensure_perm_table_in_request()
    if err:
        return jsonify({
            "ok": False,
            "error": f"Permission table initialization failed: {err}"
        }), 500

    data = request.get_json(force=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    if not username or not password:
        return jsonify({
            "ok": False,
            "error": "Missing username/password"
        }), 400

    operatorName = username
    now = datetime.now()
    try:
        with config.engine.begin() as conn:
            if not _perm_table_exists(conn):
                return jsonify({
                    "ok": False,
                    "db_status": 0,
                    "error": "Permission table does not exist"
                }),500
            # 先查用户
            row = conn.execute(
                text(
                    f"""
                    SELECT 
                        password,
                        salt,
                        permission,
                        first_login,
                        password_created_at,
                        password_expire_at
                    FROM `{PERM_TABLE}`
                    WHERE username=:username
                    LIMIT 1
                    """
                ),
                {
                    "username": username
                }
            ).fetchone()

            if row is None:
                return jsonify({
                    "ok":False,
                    "error":"Invalid username or password"
                }),401

            db_hash, salt, permission, first_login, created_at, expire_at = row
            password_warning = False
            password_expired = False
            password_days_left = None
            message = ""

            # 判断密码生命周期

            if expire_at is not None:
                delta = expire_at - now
                total_seconds_left = delta.total_seconds()

                if total_seconds_left < 0:
                    # =========================
                    # 密码已经过期
                    # =========================
                    # 重要：
                    # 这里不重置密码
                    # 这里不修改 password
                    # 这里不修改 password_created_at
                    # 这里不修改 password_expire_at
                    # 这里不修改 last_notify_at
                    # 仍然允许登录
                    password_expired = True
                    password_warning = False
                    password_days_left = 0
                    message = "password expired, please modify password"

                elif delta <= timedelta(days=config.PASSWORD_WARNING_DAYS):
                    # =========================
                    # 密码即将过期
                    # =========================
                    password_expired = False
                    password_warning = True
                    password_days_left = delta.days
                    message = "password will expire soon, please modify password"

                    # 只记录提醒时间，不修改密码本身
                    conn.execute(
                        text(f"""
                            UPDATE `{PERM_TABLE}`
                            SET last_notify_at=:now
                            WHERE username=:username
                        """),
                        {
                            "now": now,
                            "username": username,
                        },
                    )

                else:
                    # =========================
                    # 密码正常
                    # =========================
                    password_expired = False
                    password_warning = False
                    password_days_left = delta.days
                    message = ""

            # 计算输入密码hash
            input_hash = md5_password(
                password,
                salt
            )

            # 比较
            if input_hash != db_hash:
                return jsonify({
                    "ok":False,
                    "error":"Invalid username or password"
                }),401

        _result = operationLog.OperationResult.SUCCESS

        # return jsonify({
        #     "ok":True,
        #     "username":username,
        #     "permission":int(row[2]),
        #     "first_login":int(row[3])
        # })
        return jsonify({
            "ok": True,
            "db_status": 1,
            "username": username,
            "permission": int(permission),
            "first_login": int(first_login),
            "password_warning": password_warning,
            "password_expired": password_expired,
            "password_expire_at": expire_at.strftime("%Y-%m-%d %H:%M:%S") if expire_at else None,
            "password_days_left": password_days_left,
            "message": message,
        })

    except Exception as e:
        _result = operationLog.OperationResult.FAIL
        return jsonify({
            "ok":False,
            "error":str(e)
        }),500


    finally:
        operationLog.enqueue_operation_log(
            operatorName,
            operationLog.OperationType.USER,
            _target,
            1,
            _result,
            remark
        )

@permission_bp.route("/permission/delete", methods=["POST"])
def permission_delete():
    """
    删除用户：请求 {username}
    """
    err = _ensure_perm_table_in_request()
    if err:
        return jsonify({"ok": False, "error": f"Permission table initialization failed: {err}"}), 500

    data = request.get_json(force=True) or {}
    operatorName = str(data.get("operatorName", "")).strip()
    username = str(data.get("username", "")).strip()
    if not operatorName:
        return jsonify({"ok": False, "error": "Missing operatorName"}), 400
    if not username:
        return jsonify({"ok": False, "error": "Missing username"}), 400
    _target = "user account"
    remark = f"delete account{username}"
    _result = operationLog.OperationResult.FAIL
    try:
        with config.engine.begin() as conn:
            if not _perm_table_exists(conn):
                return jsonify({"ok": False, "error": "Permission table does not exist"}), 500
            row = conn.execute(
                text(
                    f"SELECT 1 FROM `{PERM_TABLE}` "
                    f"WHERE username=:username LIMIT 1"
                ),
                {"username": username},
            ).fetchone()
            if row is None:
                return jsonify({"ok": False, "error": "Invalid username"}), 401
            conn.execute(
                text(f"DELETE FROM `{PERM_TABLE}` WHERE username=:username"),
                {"username": username},
            )
            _result = operationLog.OperationResult.SUCCESS
        return jsonify({"ok": True, "deleted": username})
    except Exception as e:
        _result = operationLog.OperationResult.FAIL
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        operationLog.enqueue_operation_log(
            operatorName,
            operationLog.OperationType.USER,
            _target,
            1,
            _result,
            remark
            )

@permission_bp.route("/permission/add", methods=["POST"])
def permission_add():
    """
    增加用户：
    请求 {username, permission}

    默认：
    - password = 12345678
    - first_login = 1
    - 密码有效期 = 6个月
    """
    err = _ensure_perm_table_in_request()
    if err:
        return jsonify({"ok": False, "error": f"Permission table initialization failed: {err}"}), 500

    data = request.get_json(force=True) or {}
    operatorName = str(data.get("operatorName", "")).strip()
    username = str(data.get("username", "")).strip()
    permission = data.get("permission")

    if not operatorName:
        return jsonify({"ok": False, "error": "Missing operatorName"}), 400
    if not username or permission is None:
        return jsonify({"ok": False, "error": "Missing username/permission"}), 400
    _target = "user account"
    _remark = f"add account{username}"
    _result = operationLog.OperationResult.FAIL
    salt = generate_salt()
    password_hash = md5_password(config.DEFAULT_PASSWORD, salt)
    try:
        permission = int(permission)
    except Exception:
        return jsonify({"ok": False, "error": "permission must be an integer"}), 400
    if permission < 1 or permission > 4:
        return jsonify({"ok": False, "error": "permission must be between 1 and 4"}), 400
    password = password_hash
    first_login = 1

    now = datetime.now()
    expire_time = now + timedelta(days=config.PASSWORD_LIFETIME_DAYS)  # 6个月

    try:
        with config.engine.begin() as conn:
            if not _perm_table_exists(conn):
                return jsonify({"ok": False, "error": "Permission table does not exist"}), 500
            exists = conn.execute(
                text(f"SELECT 1 FROM `{PERM_TABLE}` WHERE username=:username LIMIT 1"),
                {"username": username},
            ).fetchone()
            if exists is not None:
                return jsonify({"ok": False, "error": "User already exists"}), 409
            # ===== 插入用户（含密码生命周期）=====
            conn.execute(
                text(f"""
                    INSERT INTO `{PERM_TABLE}`
                    (
                        username,
                        password,
                        salt,
                        permission,
                        first_login,
                        password_created_at,
                        password_expire_at,
                        last_notify_at
                    )
                    VALUES
                    (
                        :username,
                        :password,
                        :salt,
                        :permission,
                        :first_login,
                        :created_at,
                        :expire_at,
                        NULL
                    )
                """),
                {
                    "username": username,
                    "password": password,
                    "salt": salt,
                    "permission": permission,
                    "first_login": first_login,
                    "created_at": now,
                    "expire_at": expire_time,
                },
            )
            _result = operationLog.OperationResult.SUCCESS

        return jsonify({
            "ok": True,
            "username": username,
            "password": password,
            "salt": salt,
            "permission": permission,
            "first_login": first_login,
            "password_created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "password_expire_at": expire_time.strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception as e:
        _result = operationLog.OperationResult.FAIL
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        operationLog.enqueue_operation_log(
            operatorName,
            operationLog.OperationType.USER,
            _target,
            1,
            _result,
            _remark
            )

@permission_bp.route("/permission/update", methods=["POST"])
def permission_update():
    """
    修改用户：
    请求参数：
    {
        "username": "当前用户名",

        可选：
        "new_username": "新用户名",
        "password": "新密码",
        "permission": 1~4,
        "first_login": 0或1
    }

    说明：
    - username 是当前用户名，用于定位数据库里的用户
    - new_username 可选，用于修改用户名
    - password 可选，修改密码时会刷新密码生命周期
    - 如果该用户 password_expire_at 为 NULL，表示永久账号，修改密码后仍保持永久
    """

    err = _ensure_perm_table_in_request()
    if err:
        return jsonify({"ok": False, "error": f"Permission table initialization failed: {err}"}), 500

    data = request.get_json(force=True) or {}
    operatorName = str(data.get("operatorName", "")).strip()
    username = str(data.get("username", "")).strip()
    if not operatorName:
        return jsonify({"ok": False, "error": "Missing operatorName"}), 400
    if not username:
        return jsonify({"ok": False, "error": "Missing username"}), 400
    _target = "user account"
    _remark = f"update account{username}"
    _result = operationLog.OperationResult.FAIL
    new_username = str(data.get("new_username", "")).strip() if data.get("new_username") is not None else ""
    new_password = data.get("password")
    new_permission = data.get("permission")
    new_first_login = data.get("first_login")

    updates = {}
    now = datetime.now()
    salt = generate_salt()
    if new_username:
        updates["username"] = new_username
    if new_password is not None:
        password_hash = md5_password(str(new_password), salt)
        updates["password"] = password_hash
        updates["salt"] = salt
        updates["password_created_at"] = now
        updates["last_notify_at"] = None
    if new_permission is not None:
        try:
            new_permission = int(new_permission)
        except Exception:
            return jsonify({"ok": False, "error": "permission must be an integer"}), 400
        if new_permission < 1 or new_permission > 4:
            return jsonify({"ok": False, "error": "permission must be between 1 and 4"}), 400
        updates["permission"] = new_permission
    if new_first_login is not None:
        try:
            new_first_login = int(new_first_login)
        except Exception:
            return jsonify({"ok": False, "error": "first_login must be an integer"}), 400
        if new_first_login not in (0, 1):
            return jsonify({"ok": False, "error": "first_login must be 0 or 1"}), 400
        updates["first_login"] = new_first_login

    if not updates:
        return jsonify({"ok": False, "error": "No fields to update"}), 400

    try:
        with config.engine.begin() as conn:
            if not _perm_table_exists(conn):
                return jsonify({"ok": False, "error": "Permission table does not exist"}), 500
            row = conn.execute(
                text(f"""
                    SELECT password_expire_at
                    FROM `{PERM_TABLE}`
                    WHERE username=:username
                    LIMIT 1
                """),
                {
                    "username": username
                }
            ).fetchone()

            if row is None:
                return jsonify({
                    "ok": False,
                    "error": "User not found"
                }), 404

            old_password_expire_at = row[0]

            if new_username and new_username != username:
                exists = conn.execute(
                    text(f"""
                        SELECT 1
                        FROM `{PERM_TABLE}`
                        WHERE username=:new_username
                        LIMIT 1
                    """),
                    {
                        "new_username": new_username
                    }
                ).fetchone()

                if exists is not None:
                    return jsonify({
                        "ok": False,
                        "error": "New username already exists"
                    }), 409

            if new_password is not None:
                if old_password_expire_at is None:
                    # password_expire_at 为 NULL 表示永久账号
                    # 永久账号修改密码后仍保持永久
                    updates["password_expire_at"] = None
                else:
                    updates["password_expire_at"] = now + timedelta(days=config.PASSWORD_LIFETIME_DAYS)

            set_clauses = []
            params = {"old_username": username}
            for k, v in updates.items():
                set_clauses.append(f"`{k}`=:{k}")
                params[k] = v
            sql = f"UPDATE `{PERM_TABLE}` SET {', '.join(set_clauses)} WHERE username=:old_username"
            conn.execute(text(sql), params)
            _result = operationLog.OperationResult.SUCCESS

        return jsonify({
            "ok": True,
            "username": updates.get("username", username),
            "updated_fields": list(updates.keys())
        })

    except Exception as e:
        _result = operationLog.OperationResult.FAIL
        return jsonify({"ok": False, "error": str(e)}), 500

    finally:
        operationLog.enqueue_operation_log(
            operatorName,
            operationLog.OperationType.USER,
            _target,
            1,
            _result,
            _remark
            )

@permission_bp.route("/permission/all", methods=["POST"])
def permission_all():
    """
    查询全部用户：返回 Permission_Management 全部内容
    包含密码生命周期字段，方便前端显示密码到期时间/是否即将过期。
    """
    err = _ensure_perm_table_in_request()
    if err:
        return jsonify({
            "ok": False,
            "error": f"Permission table initialization failed: {err}"
        }), 500

    try:
        now = datetime.now()

        with engine.begin() as conn:
            if not _perm_table_exists(conn):
                return jsonify({
                    "ok": False,
                    "error": "Permission table does not exist"
                }), 500

            rows = conn.execute(
                text(f"""
                    SELECT
                        username,
                        password,
                        permission,
                        first_login,
                        password_created_at,
                        password_expire_at,
                        last_notify_at
                    FROM `{PERM_TABLE}`
                    ORDER BY username
                """)
            ).fetchall()

        data = []
        for r in rows:
            username = r[0]
            password = r[1]
            permission = int(r[2])
            first_login = int(r[3])
            password_created_at = r[4]
            password_expire_at = r[5]
            last_notify_at = r[6]

            password_warning = False
            password_expired = False
            password_days_left = None

            if password_expire_at is not None:
                delta = password_expire_at - now
                password_days_left = delta.days

                if delta.total_seconds() < 0:
                    password_expired = True
                elif delta <= timedelta(days=15):
                    password_warning = True

            data.append({
                "username": username,
                "password": password,
                "permission": permission,
                "first_login": first_login,

                "password_created_at": password_created_at.strftime("%Y-%m-%d %H:%M:%S") if password_created_at else None,
                "password_expire_at": password_expire_at.strftime("%Y-%m-%d %H:%M:%S") if password_expire_at else None,
                "last_notify_at": last_notify_at.strftime("%Y-%m-%d %H:%M:%S") if last_notify_at else None,

                "password_warning": password_warning,
                "password_expired": password_expired,
                "password_days_left": password_days_left,
            })

        return jsonify({
            "ok": True,
            "count": len(data),
            "data": data
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500
