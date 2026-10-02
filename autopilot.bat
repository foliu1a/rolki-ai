@echo off
title rolki-ai autopilot
cd /d "%~dp0"
echo Autopilot rolki-ai: skanuj -> generuj -> Media Tool -> lipsync -> zdjecia (co kilka minut, dla modelek z autopilot=true)
echo Ctrl+C konczy. Panel z przyciskiem Autopilot: panel.bat
python autopilot.py
pause
