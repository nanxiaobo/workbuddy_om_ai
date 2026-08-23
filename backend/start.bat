@echo off
REM 一键启动后端并托管前端（Windows）
cd /d "%~dp0backend"
call python -m pip install -q -r requirements.txt 2>nul
python -m uvicorn main:app --host 127.0.0.1 --port 61050
pause
