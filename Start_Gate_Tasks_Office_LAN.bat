@echo off
rem Serve Gate Tasks to the whole office network (colleagues open http://THIS-PC-NAME:8000)
cd /d "%~dp0"
set "GATE_TASKS_HOST=0.0.0.0"
call "%~dp0Start_Gate_Tasks.bat"
