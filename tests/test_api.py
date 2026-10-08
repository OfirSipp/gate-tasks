import json

import pytest
from fastapi.testclient import TestClient

from gate_tasks.app import create_app

ADMIN = {"username": "ofir", "display_name": "Ofir", "password": "secret123"}


@pytest.fixture()
def client(tmp_path):
    legacy = tmp_path / "tasks_db.json"
    legacy.write_text(json.dumps([
        {"id": 1, "title": "Old task", "category": "QA", "priority": "Fail", "deadline": "2026-01-01",
         "status": "Completed", "notes": "from v1"},
    ]))
    app = create_app(db_path=tmp_path / "test.db", legacy_json=legacy)
    with TestClient(app) as c:
        yield c
    app.state.db.close()


def setup_admin(client):
    r = client.post("/api/setup", json=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def add_user(client, username, admin=False):
    r = client.post("/api/users", json={"username": username, "display_name": username.title(),
                                        "password": "password1", "is_admin": admin})
    assert r.status_code == 201, r.text
    return r.json()


def login(client, username, password="password1"):
    client.cookies.clear()
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def test_first_run_setup_imports_old_tasks(client):
    assert client.get("/api/auth/status").json()["needs_setup"] is True
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    body = setup_admin(client)
    assert body["imported"] == 1 and body["user"]["is_admin"] is True
    tasks = client.get("/api/tasks").json()
    assert tasks[0]["title"] == "Old task" and tasks[0]["status"] == "Completed"
    assert client.post("/api/setup", json=ADMIN).status_code == 409
    assert client.get("/").status_code == 200


def test_requires_login(client):
    setup_admin(client)
    client.cookies.clear()
    assert client.get("/api/tasks").status_code == 401
    assert client.post("/api/login", json={"username": "ofir", "password": "nope"}).status_code == 401


def test_boards_are_private_per_person(client):
    setup_admin(client)
    add_user(client, "dana")
    add_user(client, "yossi")
    login(client, "dana")
    mine = client.post("/api/tasks", json={"title": "Dana's task", "category": "Ops"}).json()
    assert mine["owner_id"] == mine["created_by"]
    login(client, "yossi")
    assert client.get("/api/tasks").json() == []
    assert client.put(f"/api/tasks/{mine['id']}", json={"status": "Completed"}).status_code == 404
    assert client.delete(f"/api/tasks/{mine['id']}").status_code == 404
    dana_id = mine["owner_id"]
    assert client.get(f"/api/tasks?user_id={dana_id}").status_code == 403


def test_assign_task_to_colleague(client):
    setup_admin(client)
    dana = add_user(client, "dana")
    add_user(client, "yossi")
    login(client, "yossi")
    sent = client.post("/api/tasks", json={"title": "Check gate 4", "owner_id": dana["id"]}).json()
    assert sent["owner_id"] == dana["id"] and sent["created_by_name"] == "Yossi"
    login(client, "dana")
    titles = [t["title"] for t in client.get("/api/tasks").json()]
    assert titles == ["Check gate 4"]
    updated = client.put(f"/api/tasks/{sent['id']}", json={"status": "In Progress", "notes": "on it"}).json()
    assert updated["status"] == "In Progress" and updated["notes"] == "on it" and updated["title"] == "Check gate 4"


def test_deadline_is_optional(client):
    setup_admin(client)
    task = client.post("/api/tasks", json={"title": "No rush"}).json()
    assert task["deadline"] == ""
    dated = client.put(f"/api/tasks/{task['id']}", json={"deadline": "2026-12-31"}).json()
    assert dated["deadline"] == "2026-12-31"
    cleared = client.put(f"/api/tasks/{task['id']}", json={"deadline": ""}).json()
    assert cleared["deadline"] == ""


def test_admin_manages_team(client):
    setup_admin(client)
    dana = add_user(client, "dana")
    assert client.post("/api/users", json={"username": "dana", "display_name": "x", "password": "password1"}).status_code == 409
    login(client, "dana")
    assert client.post("/api/users", json={"username": "x1", "display_name": "x", "password": "password1"}).status_code == 403
    assert "task_count" not in client.get("/api/users").json()[0]
    login(client, "ofir", "secret123")
    client.post("/api/tasks", json={"title": "for dana", "owner_id": dana["id"]})
    assert len(client.get(f"/api/tasks?user_id={dana['id']}").json()) == 1
    team = {u["username"]: u for u in client.get("/api/users").json()}
    assert team["dana"]["task_count"] == 1
    assert client.patch(f"/api/users/{dana['id']}", json={"password": "newpass1"}).status_code == 200
    me_id = client.get("/api/me").json()["id"]
    assert client.patch(f"/api/users/{me_id}", json={"is_admin": False}).status_code == 400
    assert client.delete(f"/api/users/{me_id}").status_code == 400
    assert client.delete(f"/api/users/{dana['id']}").status_code == 200
    login_fail = client.post("/api/login", json={"username": "dana", "password": "newpass1"})
    assert login_fail.status_code == 401


def test_change_password_and_logout(client):
    setup_admin(client)
    assert client.post("/api/me/password", json={"current_password": "bad", "new_password": "abcdef1"}).status_code == 400
    assert client.post("/api/me/password", json={"current_password": "secret123", "new_password": "abcdef1"}).status_code == 200
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401
    login(client, "ofir", "abcdef1")


def test_validation_and_lockout(client):
    setup_admin(client)
    assert client.post("/api/tasks", json={"title": ""}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "priority": "Maybe"}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "owner_id": 999}).status_code == 400
    client.cookies.clear()
    for _ in range(5):
        client.post("/api/login", json={"username": "ofir", "password": "wrong"})
    assert client.post("/api/login", json={"username": "ofir", "password": "secret123"}).status_code == 429


def test_pages_need_no_internet(client):
    setup_admin(client)
    for path in ("/login", "/", "/static/css/app.css"):
        body = client.get(path).text
        assert "https://" not in body and "fonts.googleapis" not in body, path
    font = client.get("/static/fonts/inter-latin.woff2")
    assert font.status_code == 200 and font.headers["content-type"] == "font/woff2"


def test_static_assets_have_js_mime(client):
    r = client.get("/static/pet/pet-core.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
