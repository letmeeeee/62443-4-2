from utils.utils import DPrint, now_str
from config import remote_client_lock, HOST_IP
from utils.method import ensure_remote_connected
from utils.ini import ini_param
from flask import Flask, request, jsonify
from flask_socketio import SocketIO
import os

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
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_spa(path):
        if path.startswith("api"):
            return jsonify({"error": "not found"}), 404
        return app.send_static_file("index.html")
    from routes.route_g2 import g2_bp
    from routes.route_g3 import g3_bp
    from routes.route_permission import permission_bp
    app.register_blueprint(g2_bp)
    app.register_blueprint(g3_bp)
    app.register_blueprint(permission_bp)
    return app

app = create_app()
socketio = SocketIO(app, cors_allowed_origins="*")

def main():
    DPrint(f"[{now_str()}] [MAIN] 尝试首次连接远程 Modbus 服务器 {HOST_IP}:1502")
    with remote_client_lock:
        ok = ensure_remote_connected("startup")
    if not ok:
        DPrint(f"[{now_str()}] [MAIN] 无法连接远程 Modbus TCP 服务器")
    else:
        DPrint(f"[{now_str()}] [MAIN] 成功连接远程 Modbus TCP 服务器")
    # socketio.start_background_task(background_thread)
    DPrint(f"[{now_str()}] [MAIN] 启动 Flask SocketIO 服务器 (127.0.0.1:8000)")
    socketio.run(app, host='127.0.0.1', port=8000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

@socketio.on('connect')
def on_connect():
    DPrint(f"[{now_str()}] [SocketIO] 新客户端连接: {request.remote_addr}")

if __name__ == '__main__':
    main()
