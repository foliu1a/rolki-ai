@echo off
title rolki-ai panel
cd /d "%~dp0"
echo Panel rolki-ai: http://localhost:5077   (to okno musi zostac otwarte; zamkniecie = wylaczenie panelu)
echo Na co dzien wygodniej: skrot "Rolki AI" na pulpicie (bez tego okna). Tutaj widac bledy, gdy cos nie gra.

rem Panel ma sie otwierac w Firefoksie: szukamy firefox.exe (App Paths w rejestrze, potem typowe foldery) i podajemy go
rem Pythonowi przez BROWSER (app.py otwiera przegladarke modulem webbrowser). "cmd /c start" - zeby Python nie czekal na Firefoksa.
set "FF="
for %%k in (HKCU HKLM) do if not defined FF (
  for /f "tokens=2,*" %%a in ('reg query "%%k\Software\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe" /ve 2^>nul ^| find "REG_SZ"') do if exist "%%~b" set "FF=%%~b"
)
for %%p in ("%ProgramFiles%\Mozilla Firefox\firefox.exe" "%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe" "%LOCALAPPDATA%\Mozilla Firefox\firefox.exe") do if not defined FF if exist "%%~p" set "FF=%%~p"
if defined FF (
  set "BROWSER=cmd /c start "" "%FF%" -new-tab %%s"
  echo Panel otworzy sie w Firefoksie.
) else (
  echo Firefox nie znaleziony - panel otworzy sie w domyslnej przegladarce.
)
python app.py --autopilot
pause
