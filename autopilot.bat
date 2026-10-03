@echo off
title rolki-ai autopilot
cd /d "%~dp0"
echo Autopilot rolki-ai (bez panelu): telefon -> skanuj -> generuj (Higgsfield / yapper) -> Media Tool -> zdjecia -> podpisy
echo Co kilka minut, dla person z wlaczonym autopilotem. Lipsyncu NIE robi (to tylko recznie w panelu). Ctrl+C konczy.
echo Panel z przelacznikiem Autopilot: panel.bat albo skrot "Rolki AI" na pulpicie.
python autopilot.py
pause
