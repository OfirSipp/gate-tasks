# Changelog

## Unreleased
- Deadline is optional; tasks without one show "No deadline" and are never marked overdue.
- Runs on a stand-alone Windows PC with no Python and no internet: the ZIP includes Python 3.13 and all requirements in `runtime\python`, and `Start_Gate_Tasks.bat` uses it automatically.
- The Inter font ships with the app, so pages no longer load anything from the internet.
- Export report: an Excel report (summary and charts, passed / failed / open sheets, notes and anomalies) plus a CSV, saved in the `data exports` folder.

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
