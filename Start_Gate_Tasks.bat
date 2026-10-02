@echo off
cd /d "%~dp0"
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY (
  echo Python was not found on PATH. Run install_requirements.bat first.
  pause
  exit /b 1
)
%PY% -c "import fastapi, uvicorn" >nul 2>nul || %PY% -m pip install -r requirements.txt
start "Gate Tasks" %PY% Gate_Tasks.py
