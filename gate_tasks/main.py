"""Launcher: starts the server and opens the browser."""

import logging
import sys
import webbrowser
from threading import Timer

import uvicorn

from . import config
from .app import create_app


def _hide_console() -> None:
    if not sys.platform.startswith("win") or not config.HIDE_CONSOLE:
        return
    try:
        import ctypes

        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:  # pragma: no cover - best effort only
        pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _hide_console()
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=config.PORT, log_level="warning"))
    app.state.server = server

    browse_host = "127.0.0.1" if config.HOST in ("0.0.0.0", "::") else config.HOST
    url = f"http://{browse_host}:{config.PORT}"
    logging.info("Gate Tasks running at %s (data: %s)", url, config.DB_PATH)
    if config.OPEN_BROWSER:
        Timer(1.0, lambda: webbrowser.open(url)).start()
    server.run()


if __name__ == "__main__":
    main()
