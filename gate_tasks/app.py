"""FastAPI application: pages, auth and the task API."""

import mimetypes
import threading
import time
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, config, export
from .db import Database

# On Windows the registry can map .js to text/plain, which browsers refuse to run as a module.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")

Status = Literal["To Do", "In Progress", "No Need", "Completed"]
Priority = Literal["Pass", "Fail"]
Username = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
Password = Field(min_length=6, max_length=200)
DisplayName = Field(min_length=1, max_length=60)


# -- request bodies --------------------------------------------------------------------------
class SetupIn(BaseModel):
    username: str = Username
    display_name: str = DisplayName
    password: str = Password


class LoginIn(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=200)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Password


class UserCreateIn(BaseModel):
    username: str = Username
    display_name: str = DisplayName
    password: str = Password
    is_admin: bool = False


class UserUpdateIn(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    is_admin: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=200)


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=60)
    priority: Priority = "Pass"
    deadline: str = Field(default="", max_length=10)
    status: Status = "To Do"
    notes: str = Field(default="", max_length=10000)
    owner_id: Optional[int] = None  # assign to a colleague; defaults to yourself


class ExportIn(BaseModel):
    user_id: Optional[int] = None  # one board; leave out for the whole team (admins) or your own board


class TaskUpdateIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=60)
    priority: Optional[Priority] = None
    deadline: Optional[str] = Field(default=None, max_length=10)
    status: Optional[Status] = None
    notes: Optional[str] = Field(default=None, max_length=10000)
    owner_id: Optional[int] = None


def create_app(db_path: Optional[Path] = None, legacy_json: Optional[Path] = None,
               static_dir: Optional[Path] = None, export_dir: Optional[Path] = None) -> FastAPI:
    app = FastAPI(title="Gate Tasks", version=__version__, docs_url=None, redoc_url=None)
    db = Database(db_path or config.DB_PATH)
    legacy = legacy_json if legacy_json is not None else config.LEGACY_JSON
    static = Path(static_dir or config.STATIC_DIR)
    exports = Path(export_dir or config.EXPORT_DIR)
    app.state.db = db
    app.state.server = None  # set by main() so an admin can stop the server from the UI
    failures: dict[str, tuple[int, float]] = {}
    failures_lock = threading.Lock()

    app.mount("/static", StaticFiles(directory=str(static)), name="static")

    # -- helpers -----------------------------------------------------------------------------
    def page(name: str) -> HTMLResponse:
        html = (static / name).read_text(encoding="utf-8")
        html = html.replace("__PET_ENABLED__", "true" if config.PET_ENABLED else "false")
        html = html.replace("__VERSION__", __version__)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    def start_session(response: Response, user_id: int) -> None:
        token = db.create_session(user_id, config.SESSION_DAYS)
        response.set_cookie(config.SESSION_COOKIE, token, max_age=config.SESSION_DAYS * 86400,
                            httponly=True, samesite="lax", path="/")

    def current_user(request: Request) -> dict:
        user = db.user_for_session(request.cookies.get(config.SESSION_COOKIE))
        if user is None:
            raise HTTPException(status_code=401, detail="Please sign in.")
        return user

    def admin_user(user: dict = Depends(current_user)) -> dict:
        if not user["is_admin"]:
            raise HTTPException(status_code=403, detail="Admins only.")
        return user

    def task_for(user: dict, task_id: int) -> dict:
        task = db.get_task(task_id)
        if task is None or (task["owner_id"] != user["id"] and not user["is_admin"]):
            raise HTTPException(status_code=404, detail="Task not found.")
        return task

    def valid_owner(owner_id: Optional[int], user: dict) -> int:
        if owner_id is None:
            return user["id"]
        if db.get_user(owner_id) is None:
            raise HTTPException(status_code=400, detail="That person doesn't exist.")
        return owner_id

    # -- pages -------------------------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def index(request: Request):
        if db.user_count() == 0:
            return RedirectResponse("/login", status_code=303)
        if db.user_for_session(request.cookies.get(config.SESSION_COOKIE)) is None:
            return RedirectResponse("/login", status_code=303)
        return page("index.html")

    @app.get("/login", include_in_schema=False)
    def login_page():
        return page("login.html")

    @app.get("/healthz", include_in_schema=False)
    def health():
        return {"ok": True, "version": __version__}

    # -- auth --------------------------------------------------------------------------------
    @app.get("/api/auth/status")
    def auth_status(request: Request):
        user = db.user_for_session(request.cookies.get(config.SESSION_COOKIE))
        return {"needs_setup": db.user_count() == 0, "user": user, "version": __version__}

    @app.post("/api/setup")
    def setup(body: SetupIn, response: Response):
        if db.user_count() > 0:
            raise HTTPException(status_code=409, detail="Setup has already been done.")
        user = db.create_user(body.username, body.display_name, body.password, is_admin=True)
        imported = db.import_legacy_json(legacy, user["id"])
        start_session(response, user["id"])
        return {"user": user, "imported": imported}

    @app.post("/api/login")
    def login(body: LoginIn, response: Response):
        key = body.username.strip().lower()
        with failures_lock:
            count, until = failures.get(key, (0, 0.0))
            if until > time.time():
                raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")
        user = db.check_login(body.username, body.password)
        if user is None:
            with failures_lock:
                count += 1
                lock_until = time.time() + config.LOCKOUT_SECONDS if count >= config.MAX_LOGIN_FAILURES else 0.0
                failures[key] = (0 if lock_until else count, lock_until)
            raise HTTPException(status_code=401, detail="Wrong username or password.")
        with failures_lock:
            failures.pop(key, None)
        start_session(response, user["id"])
        return {"user": user}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        db.delete_session(request.cookies.get(config.SESSION_COOKIE))
        response.delete_cookie(config.SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)):
        return user

    @app.post("/api/me/password")
    def change_password(body: PasswordIn, request: Request, user: dict = Depends(current_user)):
        if db.check_login(user["username"], body.current_password) is None:
            raise HTTPException(status_code=400, detail="Your current password is wrong.")
        db.update_user(user["id"], password=body.new_password)
        db.delete_sessions_for(user["id"], keep_token=request.cookies.get(config.SESSION_COOKIE))
        return {"ok": True}

    # -- people ------------------------------------------------------------------------------
    @app.get("/api/users")
    def list_users(user: dict = Depends(current_user)):
        people = db.list_users()
        if not user["is_admin"]:  # colleagues only need names to assign tasks
            people = [{"id": p["id"], "display_name": p["display_name"], "username": p["username"]} for p in people]
        return people

    @app.post("/api/users", status_code=201)
    def create_user(body: UserCreateIn, _: dict = Depends(admin_user)):
        if db.get_user_by_username(body.username) is not None:
            raise HTTPException(status_code=409, detail="That username is taken.")
        return db.create_user(body.username, body.display_name, body.password, body.is_admin)

    @app.patch("/api/users/{user_id}")
    def update_user(user_id: int, body: UserUpdateIn, admin: dict = Depends(admin_user)):
        target = db.get_user(user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found.")
        if body.is_admin is False and target["is_admin"] and db.admin_count() <= 1:
            raise HTTPException(status_code=400, detail="There must be at least one admin.")
        updated = db.update_user(user_id, display_name=body.display_name, is_admin=body.is_admin,
                                 password=body.password)
        if body.password is not None and user_id != admin["id"]:
            db.delete_sessions_for(user_id)  # signs them out everywhere after a reset
        return updated

    @app.delete("/api/users/{user_id}")
    def delete_user(user_id: int, admin: dict = Depends(admin_user)):
        if user_id == admin["id"]:
            raise HTTPException(status_code=400, detail="You can't delete your own account.")
        if db.get_user(user_id) is None:
            raise HTTPException(status_code=404, detail="User not found.")
        db.delete_user(user_id)
        return {"ok": True}

    # -- tasks -------------------------------------------------------------------------------
    @app.get("/api/tasks")
    def list_tasks(user_id: Optional[int] = None, user: dict = Depends(current_user)):
        owner = user["id"] if user_id is None else user_id
        if owner != user["id"] and not user["is_admin"]:
            raise HTTPException(status_code=403, detail="You can only open your own board.")
        return db.list_tasks(owner)

    @app.post("/api/tasks", status_code=201)
    def create_task(body: TaskIn, user: dict = Depends(current_user)):
        owner = valid_owner(body.owner_id, user)
        return db.create_task(owner, user["id"], body.model_dump(exclude={"owner_id"}))

    @app.put("/api/tasks/{task_id}")
    def update_task(task_id: int, body: TaskUpdateIn, user: dict = Depends(current_user)):
        task_for(user, task_id)
        data = body.model_dump(exclude_none=True)
        if "owner_id" in data:
            data["owner_id"] = valid_owner(data["owner_id"], user)
        return db.update_task(task_id, data)

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: int, user: dict = Depends(current_user)):
        task_for(user, task_id)
        db.delete_task(task_id)
        return {"ok": True}

    # -- reports -----------------------------------------------------------------------------
    @app.post("/api/export")
    def export_report(body: ExportIn, user: dict = Depends(current_user)):
        """Save an Excel report in the exports folder and send it back for an optional download."""
        if body.user_id is None and user["is_admin"]:
            tasks, label, slug, team = db.list_all_tasks(), "Whole team", "team", True
        else:
            owner = db.get_user(user["id"] if body.user_id is None else body.user_id)
            if owner is None:
                raise HTTPException(status_code=404, detail="User not found.")
            if owner["id"] != user["id"] and not user["is_admin"]:
                raise HTTPException(status_code=403, detail="You can only export your own board.")
            tasks, label, slug, team = (db.list_tasks(owner["id"]), f"{owner['display_name']}'s board",
                                        owner["username"], False)
        try:
            saved = export.save_report(exports, tasks, scope_label=label, scope_slug=slug,
                                       generated_by=user["display_name"], team=team)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Couldn't write to {exports}: {exc.strerror or exc}")
        return Response(saved.data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(saved.path.name)}",
                                 "X-Export-Folder": quote(str(saved.folder)),
                                 "X-Export-File": quote(saved.path.name)})

    # -- admin -------------------------------------------------------------------------------
    @app.post("/api/admin/shutdown")
    def shutdown(_: dict = Depends(admin_user)):
        server = app.state.server
        if server is None:
            raise HTTPException(status_code=400, detail="Not running under the Gate Tasks launcher.")
        threading.Timer(0.5, lambda: setattr(server, "should_exit", True)).start()
        return {"ok": True}

    return app
