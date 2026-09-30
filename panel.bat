@echo off
cd /d "%~dp0"
start "" http://localhost:5077
python app.py
pause
