from __future__ import annotations

import ctypes
import sys
import threading
import time
import traceback

from app.config import AppConfig


def prepare_output() -> None:
    """Keep errors available when the packaged app has no console."""
    data_dir = AppConfig.from_env().data_dir
    if sys.stdout is None:
        sys.stdout = (data_dir / "server.stdout.log").open("a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = (data_dir / "server.stderr.log").open("a", encoding="utf-8")


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "W1ndVoice", 0x10)


def run_desktop() -> None:
    prepare_output()

    import uvicorn
    import webview

    from app.main import app, config

    server = uvicorn.Server(
        uvicorn.Config(app, host=config.host, port=config.port, log_level=config.log_level.lower())
    )
    server_error: list[BaseException] = []

    def serve() -> None:
        try:
            server.run()
        except BaseException as exc:  # noqa: BLE001 - capture server thread startup failures
            server_error.append(exc)
            traceback.print_exc()

    thread = threading.Thread(target=serve, name="w1ndvoice-server", daemon=True)
    thread.start()
    for _ in range(200):
        if server.started or not thread.is_alive():
            break
        time.sleep(0.1)

    if not server.started:
        detail = f"\n\n原因：{server_error[0]}" if server_error else ""
        show_error(f"W1ndVoice 启动失败，请检查 {config.port} 端口是否被占用。{detail}")
        return

    try:
        webview.create_window("W1ndVoice", f"http://127.0.0.1:{config.port}", width=1280, height=840)
        webview.start(gui="edgechromium")
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    try:
        run_desktop()
    except Exception as exc:  # noqa: BLE001 - windowed builds must show startup errors
        traceback.print_exc()
        show_error(f"W1ndVoice 无法打开：{exc}")
