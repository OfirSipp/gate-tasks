@echo off
title Gate Tasks - install requirements
cd /d "%~dp0"
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY (
  echo Python was not found on PATH. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
echo Using:
%PY% --version
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Install FAILED - see the messages above.
) else (
  echo.
  %PY% -c "import fastapi, uvicorn, pydantic; print('OK: fastapi', fastapi.__version__, '/ uvicorn', uvicorn.__version__, '/ pydantic', pydantic.VERSION)"
  echo All requirements installed. Start the app with Start_Gate_Tasks.bat
)
pause
