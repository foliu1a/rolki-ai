@echo off
title rolki-ai panel
cd /d "%~dp0"
start "" http://localhost:5077
python app.py
pause
