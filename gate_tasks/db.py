"""SQLite storage for users, sessions and tasks."""

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import security

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title      TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT '',
    priority   TEXT NOT NULL DEFAULT 'Pass',
    deadline   TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'To Do',
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""

USER_COLUMNS = "id, username, display_name, is_admin, created_at"
TASK_SELECT = """
SELECT t.id, t.owner_id, t.created_by, t.title, t.category, t.priority, t.deadline, t.status, t.notes,
       t.created_at, t.updated_at, c.display_name AS created_by_name, o.display_name AS owner_name
FROM tasks t
LEFT JOIN users c ON c.id = t.created_by
LEFT JOIN users o ON o.id = t.owner_id
"""

STATUSES = ("To Do", "In Progress", "No Need", "Completed")
PRIORITIES = ("Pass", "Fail")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _user(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    user = dict(row)
    user["is_admin"] = bool(user["is_admin"])
    user.pop("password_hash", None)
    return user


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def _write(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, args)

    # -- meta -------------------------------------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        row = self._one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._write("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    # -- users ------------------------------------------------------------------------------
    def user_count(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM users")["n"]

    def admin_count(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM users WHERE is_admin = 1")["n"]

    def create_user(self, username: str, display_name: str, password: str, is_admin: bool = False) -> dict:
        cur = self._write(
            "INSERT INTO users(username, display_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
            (username.strip(), display_name.strip(), security.hash_password(password), int(is_admin), now_iso()),
        )
        return self.get_user(cur.lastrowid)

    def get_user(self, user_id: int) -> Optional[dict]:
        return _user(self._one(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user_id,)))

    def get_user_by_username(self, username: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM users WHERE username = ?", (username.strip(),))

    def list_users(self) -> list[dict]:
        rows = self._all(
            f"""SELECT {', '.join('u.' + c.strip() for c in USER_COLUMNS.split(','))},
                       (SELECT COUNT(*) FROM tasks t WHERE t.owner_id = u.id) AS task_count,
                       (SELECT COUNT(*) FROM tasks t WHERE t.owner_id = u.id AND t.status = 'Completed') AS done_count
                FROM users u ORDER BY u.display_name COLLATE NOCASE"""
        )
        for row in rows:
            row["is_admin"] = bool(row["is_admin"])
        return rows

    def update_user(self, user_id: int, *, display_name: Optional[str] = None, is_admin: Optional[bool] = None,
                    password: Optional[str] = None) -> Optional[dict]:
        if display_name is not None:
            self._write("UPDATE users SET display_name = ? WHERE id = ?", (display_name.strip(), user_id))
        if is_admin is not None:
            self._write("UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id))
        if password is not None:
            self._write("UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_password(password), user_id))
        return self.get_user(user_id)

    def delete_user(self, user_id: int) -> None:
        self._write("DELETE FROM users WHERE id = ?", (user_id,))

    def check_login(self, username: str, password: str) -> Optional[dict]:
        row = self.get_user_by_username(username)
        if row is None or not security.verify_password(password, row["password_hash"]):
            return None
        return _user(row)

    # -- sessions ---------------------------------------------------------------------------
    def create_session(self, user_id: int, days: int) -> str:
        token = security.new_session_token()
        self._write(
            "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (security.token_digest(token), user_id, time.time() + days * 86400),
        )
        self._write("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        return token

    def user_for_session(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        row = self._one(
            f"""SELECT {', '.join('u.' + c.strip() for c in USER_COLUMNS.split(','))}
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ?""",
            (security.token_digest(token), time.time()),
        )
        return _user(row)

    def delete_session(self, token: Optional[str]) -> None:
        if token:
            self._write("DELETE FROM sessions WHERE token_hash = ?", (security.token_digest(token),))

    def delete_sessions_for(self, user_id: int, keep_token: Optional[str] = None) -> None:
        keep = security.token_digest(keep_token) if keep_token else ""
        self._write("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, keep))

    # -- tasks ------------------------------------------------------------------------------
    def list_tasks(self, owner_id: int) -> list[dict]:
        return self._all(TASK_SELECT + " WHERE t.owner_id = ? ORDER BY t.id", (owner_id,))

    def get_task(self, task_id: int) -> Optional[dict]:
        row = self._one(TASK_SELECT + " WHERE t.id = ?", (task_id,))
        return dict(row) if row else None

    def create_task(self, owner_id: int, created_by: Optional[int], data: dict[str, Any]) -> dict:
        stamp = now_iso()
        cur = self._write(
            """INSERT INTO tasks(owner_id, created_by, title, category, priority, deadline, status, notes,
                                 created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (owner_id, created_by, data["title"], data.get("category", ""), data.get("priority", "Pass"),
             data.get("deadline", ""), data.get("status", "To Do"), data.get("notes", ""), stamp, stamp),
        )
        return self.get_task(cur.lastrowid)

    def update_task(self, task_id: int, data: dict[str, Any]) -> Optional[dict]:
        fields = [k for k in ("title", "category", "priority", "deadline", "status", "notes", "owner_id") if k in data]
        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self._write(
                f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?",
                tuple(data[k] for k in fields) + (now_iso(), task_id),
            )
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> None:
        self._write("DELETE FROM tasks WHERE id = ?", (task_id,))

    # -- migration from the single-user JSON file --------------------------------------------
    def import_legacy_json(self, path: Path, owner_id: int) -> int:
        if self.get_meta("legacy_imported") or not Path(path).exists():
            return 0
        try:
            items = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        count = 0
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not str(item.get("title", "")).strip():
                continue
            status = item.get("status") if item.get("status") in STATUSES else "To Do"
            priority = item.get("priority") if item.get("priority") in PRIORITIES else "Pass"
            self.create_task(owner_id, owner_id, {
                "title": str(item["title"])[:200], "category": str(item.get("category", ""))[:60],
                "priority": priority, "deadline": str(item.get("deadline", ""))[:10], "status": status,
                "notes": str(item.get("notes", ""))[:10000],
            })
            count += 1
        self.set_meta("legacy_imported", now_iso())
        return count
