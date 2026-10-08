@echo off
cd /d "%~dp0"
rem Use the Python that ships in runtime\python: works offline, nothing to install.
if not exist "%~dp0runtime\python\python.exe" goto :installed_python
start "Gate Tasks" "%~dp0runtime\python\python.exe" "%~dp0Gate_Tasks.py"
exit /b 0

:installed_python
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
