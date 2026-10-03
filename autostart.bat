@echo off
title rolki-ai - autostart
cd /d "%~dp0"
echo Wlaczam autostart: panel + autopilot beda sie uruchamiac same po zalogowaniu do Windows (w tle, bez okna).
schtasks /Create /SC ONLOGON /TN "rolki-ai" /TR "wscript.exe \"%~dp0start-cicho.vbs\"" /F >nul
if errorlevel 1 (
  echo.
  echo Nie udalo sie dodac zadania. Zrob zrzut ekranu tego okna i wyslij go Claude'owi.
  pause
  exit /b 1
)
echo Gotowe. Uruchamiam panel juz teraz (w tle). Panel: http://localhost:5077
wscript.exe "%~dp0start-cicho.vbs"
echo.
echo Zeby wylaczyc autostart: autostart-usun.bat
pause
