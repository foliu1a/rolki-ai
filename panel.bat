@echo off
title rolki-ai panel
cd /d "%~dp0"
echo Panel rolki-ai: http://localhost:5077   (to okno musi zostac otwarte; zamkniecie = wylaczenie panelu)
python app.py
pause
