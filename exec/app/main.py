from utils.utils import DPrint, now_str
from config import remote_client_lock, HOST_IP, HTTPS_ENABLE
from utils.method import ensure_remote_connected
from utils.ini import ini_param
from flask import Flask, request, jsonify, g
from flask_socketio import SocketIO
import os
from threading import Lock
from hashlib import sha256
from utils.auth import init_auth, authenticate_session
from script.session_config import configure_session



def create_app():
    # 在这里统一导入并注册
    # 获取当前 main.py 所在目录
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    # 往上跳一级，就是dist所在目录
    parent_dir = os.path.dirname(current_file_dir)
    static_folder_path = os.path.join(parent_dir, "dist")

    DPrint(f"静态前端目录: {static_folder_path}")
    DPrint(f"index.html 是否存在: {os.path.exists(os.path.join(static_folder_path, 'index.html'))}")
    app = Flask(__name__, static_folder=static_folder_path, static_url_path="/")
    configure_session(app)
    init_auth(app)
    from utils.security_audit import init_security_http
    init_security_http(app)
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_spa(path):
        if path.startswith("api"):
            return jsonify({"error": "not found"}), 404
        return app.send_static_file("index.html")
    from routes.route_g2 import g2_bp
    from routes.route_g3 import g3_bp
    from routes import route_cert, route_tee  # noqa: F401 - register routes
    from routes.route_permission import permission_bp
    from routes.route_system import system_bp
    app.register_blueprint(g2_bp)
    app.register_blueprint(g3_bp)
    app.register_blueprint(permission_bp)
    app.register_blueprint(system_bp)
    from routes.route_security import security_bp
    app.register_blueprint(security_bp)
    return app

app = create_app()
socketio = SocketIO(app)
MAX_WEB_CONNECTIONS = 20
web_connections = set()
web_connection_sessions = {}
web_connections_lock = Lock()


def get_web_connection_capacity():
    with web_connections_lock:
        active = len(web_connections)
        return {'limit': MAX_WEB_CONNECTIONS, 'active': active,
                'remaining': max(0, MAX_WEB_CONNECTIONS - active)}


app.extensions['web_connection_capacity'] = get_web_connection_capacity


def disconnect_session_connections(session_id, *, hashed=False):
    with web_connections_lock:
        connections = [sid for sid, login_sid in web_connection_sessions.items()
                       if (sha256(login_sid.encode("utf-8")).hexdigest()
                           if hashed else login_sid) == session_id]
    # disconnect invokes on_disconnect, which takes the same lock.
    for sid in connections:
        socketio.server.disconnect(sid, namespace='/')


app.extensions['disconnect_session_connections'] = disconnect_session_connections
app.extensions['disconnect_session_connections_by_id'] = (
    lambda session_id: disconnect_session_connections(session_id, hashed=True))

def main():
    from utils.disk_cleanup import start_disk_cleanup_monitor
    start_disk_cleanup_monitor(DPrint)
    from utils.port_monitor import start_port_monitor
    start_port_monitor(DPrint)
    from utils.ini_integrity import start_ini_integrity_monitor
    start_ini_integrity_monitor(DPrint)
    DPrint(f"[{now_str()}] [MAIN] 尝试首次连接远程 Modbus 服务器 {HOST_IP}:1502")
    with remote_client_lock:
        ok = ensure_remote_connected("startup")
    if not ok:
        DPrint(f"[{now_str()}] [MAIN] 无法连接远程 Modbus TCP 服务器")
    else:
        DPrint(f"[{now_str()}] [MAIN] 成功连接远程 Modbus TCP 服务器")
    # socketio.start_background_task(background_thread)
    if HTTPS_ENABLE:
        # 使用 HTTPS 运行 Flask SocketIO 服务器
        socketio.run(app, host='127.0.0.1', port=8000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
        DPrint(f"[{now_str()}] [MAIN] 启动 Flask SocketIO 服务器 (127.0.0.1:8000)")
    else:
        socketio.run(app, host='0.0.0.0', port=8000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
        DPrint(f"[{now_str()}] [MAIN] 启动 Flask SocketIO 服务器 (0.0.0.0:8000)")
@socketio.on('connect')
def on_connect(auth=None):
    try:
        token = auth.get("session_token", "") if isinstance(auth, dict) else ""
        if not authenticate_session(token):
            DPrint(f"[{now_str()}] [SocketIO] 客户端连接被拒绝: {request.remote_addr}")
            return False
    except Exception:
        app.logger.exception("SocketIO authentication failed")
        DPrint(f"[{now_str()}] [SocketIO] 客户端连接验证失败: {request.remote_addr}")
        return False
    with web_connections_lock:
        if request.sid not in web_connections and len(web_connections) >= MAX_WEB_CONNECTIONS:
            DPrint(f"[{now_str()}] [SocketIO] 连接被拒绝（达到上限）: "
                   f"sid={request.sid}, ip={request.remote_addr}, "
                   f"connections={len(web_connections)}/{MAX_WEB_CONNECTIONS}, remaining=0")
            return False
        web_connections.add(request.sid)
        web_connection_sessions[request.sid] = g.session_id
        DPrint(f"[{now_str()}] [SocketIO] 前端连接: sid={request.sid}, "
               f"ip={request.remote_addr}, connections={len(web_connections)}/{MAX_WEB_CONNECTIONS}, "
               f"remaining={MAX_WEB_CONNECTIONS - len(web_connections)}")


@socketio.on('disconnect')
def on_disconnect(reason=None):
    with web_connections_lock:
        if request.sid not in web_connections:
            return
        web_connections.remove(request.sid)
        web_connection_sessions.pop(request.sid, None)
        DPrint(f"[{now_str()}] [SocketIO] 前端断连: sid={request.sid}, "
               f"ip={request.remote_addr}, reason={reason}, "
               f"connections={len(web_connections)}/{MAX_WEB_CONNECTIONS}, "
               f"remaining={MAX_WEB_CONNECTIONS - len(web_connections)}")

if __name__ == '__main__':
    main()
