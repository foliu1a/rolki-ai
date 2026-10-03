@echo off
title rolki-ai - wylacz autostart
schtasks /Delete /TN "rolki-ai" /F >nul 2>&1
echo Autostart wylaczony. Panel w tle (jesli dziala) zatrzymaj: zamknij procesy python w Menedzerze zadan albo uruchom ponownie komputer.
pause
