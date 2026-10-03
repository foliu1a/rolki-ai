@echo off
title rolki-ai panel
cd /d "%~dp0"
echo Panel rolki-ai: http://localhost:5077   (to okno musi zostac otwarte; zamkniecie = wylaczenie panelu)
echo Na co dzien wygodniej: skrot "Rolki AI" na pulpicie (bez tego okna). Tutaj widac bledy, gdy cos nie gra.
python app.py --autopilot
pause
