@echo off
title rolki-ai - wylacz autostart
cd /d "%~dp0"
cscript.exe //nologo "%~dp0skroty.vbs" autostart-usun
schtasks /Delete /TN "rolki-ai" /F >nul 2>&1
echo Autostart wylaczony. Panel w tle (jesli dziala) zatrzymaj: aktualizuj.bat go zamyka, albo uruchom ponownie komputer.
pause
