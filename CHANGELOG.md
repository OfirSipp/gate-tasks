# Changelog

## Unreleased
- Deadline is optional; tasks without one show "No deadline" and are never marked overdue.

## 2.0.0 — 2026-10-02
- Accounts: sign-in, first-run admin setup, a private board per person.
- Assign tasks to colleagues; admins can open any board and manage the team.
- SQLite storage (`data/gate_tasks.db`), with a one-time import of v1 `tasks_db.json`.
- Change password, admin password reset, sign-in rate limiting, stop server from the UI.
- Overdue highlighting; all user content is HTML-escaped.
- Desktop pet with three skins: Clawd, Amir Latex and Earl Grey (British Shorthair).
- Split into a package with static files, tests and CI.

## 1.0.0
- Single-user kanban board in one file (`Gate_Tasks.py` + `tasks_db.json`).
