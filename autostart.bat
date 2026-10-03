@echo off
title rolki-ai - autostart
cd /d "%~dp0"
echo Wlaczam autostart: panel + autopilot beda sie uruchamiac same po zalogowaniu do Windows (w tle, bez okna).
echo (bez praw administratora - skrot w folderze Autostart)
cscript.exe //nologo "%~dp0skroty.vbs" autostart
if errorlevel 1 (
  echo.
  echo Nie udalo sie. Zrob zrzut ekranu tego okna i wyslij go Claude'owi.
  pause
  exit /b 1
)
cscript.exe //nologo "%~dp0skroty.vbs" pulpit
echo Gotowe. Uruchamiam panel juz teraz (w tle). Panel: http://localhost:5077  (albo skrot "Rolki AI" na pulpicie)
wscript.exe "%~dp0start-cicho.vbs"
echo.
echo Zeby wylaczyc autostart: autostart-usun.bat
pause
