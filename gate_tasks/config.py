"""Runtime settings, all overridable with environment variables."""

import os
import sys
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "off", "no", "")


PACKAGE_DIR = Path(__file__).resolve().parent
# When frozen with PyInstaller, bundled files live in _MEIPASS and user data next to the .exe.
if getattr(sys, "frozen", False):
    STATIC_DIR = Path(getattr(sys, "_MEIPASS", PACKAGE_DIR)) / "gate_tasks" / "static"
    PROJECT_DIR = Path(sys.executable).resolve().parent
else:
    STATIC_DIR = PACKAGE_DIR / "static"
    PROJECT_DIR = PACKAGE_DIR.parent

DATA_DIR = Path(os.environ.get("GATE_TASKS_DATA_DIR", PROJECT_DIR / "data"))
DB_PATH = Path(os.environ.get("GATE_TASKS_DB", DATA_DIR / "gate_tasks.db"))
# The single-user version stored everything in tasks_db.json; it is imported once on first setup.
LEGACY_JSON = Path(os.environ.get("GATE_TASKS_LEGACY_JSON", PROJECT_DIR / "tasks_db.json"))

HOST = os.environ.get("GATE_TASKS_HOST", "127.0.0.1")  # use 0.0.0.0 to serve the whole office LAN
PORT = int(os.environ.get("GATE_TASKS_PORT", "8000"))
PET_ENABLED = _flag("GATE_TASKS_PET", True)
OPEN_BROWSER = _flag("GATE_TASKS_OPEN_BROWSER", True)
HIDE_CONSOLE = _flag("GATE_TASKS_HIDE_CONSOLE", True)

SESSION_COOKIE = "gt_session"
SESSION_DAYS = 14
MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 60
