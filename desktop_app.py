"""
DeepSeek Chat Desktop
=====================
将 Flask WebUI 包装为原生桌面应用（pywebview）。
双击运行，直接弹出桌面窗口，无需打开浏览器。

用法:
    python desktop_app.py               # 以桌面模式运行
    build_exe.bat                       # 打包为 exe 程序包
"""

import os
import sys
import socket
import threading
import time


def _get_app_dir() -> str:
    """获取应用根目录（处理 PyInstaller 打包与开发模式）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后：exe 所在目录
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _get_app_dir()


def find_free_port() -> int:
    """找到一个空闲的本地端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def start_flask(port: int):
    """在后台线程启动 Flask 服务器"""
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    # 切换到应用根目录，确保 Flask 能找到配置文件等
    os.chdir(APP_DIR)

    from app import app
    app.run(
        host='127.0.0.1',
        port=port,
        debug=False,
        use_reloader=False,
    )


def get_icon_path() -> str:
    """获取鲸鱼图标路径，不存在则返回空字符串"""
    icon = os.path.join(APP_DIR, 'whale.ico')
    return icon if os.path.exists(icon) else ''


def get_window_title() -> str:
    """获取窗口标题（含版本号）"""
    try:
        import yaml
        cfg_path = os.path.join(APP_DIR, 'config.yaml')
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            model = cfg.get('model', {}).get('name', '')
            if model:
                return f'DeepSeek Chat - {model}'
    except Exception:
        pass
    return 'DeepSeek Chat'


def main():
    # 1. 找空闲端口
    port = find_free_port()

    # 2. 启动 Flask（守护线程）
    t = threading.Thread(target=start_flask, args=(port,), daemon=True)
    t.start()
    time.sleep(1.0)  # 等 Flask 启动完毕

    # 3. 打开原生桌面窗口
    import webview
    webview.create_window(
        get_window_title(),
        f'http://127.0.0.1:{port}',
        width=1100,
        height=750,
        resizable=True,
        min_size=(800, 500),
    )
    webview.start(icon=get_icon_path())


if __name__ == '__main__':
    main()
