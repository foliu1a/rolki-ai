@echo off
setlocal
cd /d "%~dp0"
title Rolki AI - instalacja na nowym komputerze
echo ============================================================
echo   Rolki AI - instalacja na nowym komputerze
echo   (folder rolki-ai skopiowany do C:\claude programy\rolki-ai)
echo ============================================================
echo.
set BRAK=0

python --version >nul 2>nul
if errorlevel 1 (
  echo [Python] brak - instaluje...
  winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
  set BRAK=1
) else (
  echo [Python] jest
)

node --version >nul 2>nul
if errorlevel 1 (
  echo [Node.js] brak - instaluje...
  winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
  set BRAK=1
) else (
  echo [Node.js] jest
)

ffmpeg -version >nul 2>nul
if errorlevel 1 (
  echo [ffmpeg] brak - instaluje...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  set BRAK=1
) else (
  echo [ffmpeg] jest
)

if "%BRAK%"=="1" (
  echo.
  echo Doinstalowalem brakujace programy.
  echo ZAMKNIJ to okno i kliknij NOWY-KOMPUTER.bat JESZCZE RAZ ^(Windows musi odswiezyc sciezki^).
  echo Jesli winget nie dziala: Python z python.org ^(zaznacz "Add python.exe to PATH"^), Node.js LTS z nodejs.org.
  pause
  exit /b 0
)

echo.
echo [1/4] Biblioteki Pythona...
python -m pip install --upgrade flask pillow pytest
echo.
echo [2/4] CLI Higgsfield...
call npm install -g --allow-scripts=@higgsfield/cli @higgsfield/cli
echo.
echo [3/4] Autopilot na tym komputerze WYLACZONY (wlaczasz go w panelu, ale tylko na JEDNYM komputerze naraz)...
python -c "import baza; baza.zapisz_ustawienia_globalne(autopilot_przy_starcie=False)"
echo.
echo [4/4] Skrot "Rolki AI" na pulpicie...
cscript.exe //nologo "%~dp0skroty.vbs" pulpit
echo.
if exist "%~dp0klucze.json" (
  echo [Klucze API] klucze.json jest - klucze wczytane.
) else (
  echo [Klucze API] BRAK klucze.json - skopiuj go z pierwszego komputera do tego folderu albo wklej klucze w panelu: Ustawienia - Konta.
)
if exist "C:\claude programy\Media Tool\Media Tool.exe" (
  echo [Media Tool] jest - pranie rolek dziala.
) else (
  echo [Media Tool] brak - rozpakuj "Media Tool.zip" do C:\claude programy\Media Tool  ^(bez niego rolki zapisuja sie bez prania^).
)
echo.
echo Teraz logowanie do Higgsfield - otworzy sie przegladarka, zaloguj sie na SWOJE konto.
pause
call "%~dp0zaloguj-higgsfield.bat"
echo.
echo GOTOWE. Panel: skrot "Rolki AI" na pulpicie.
echo PAMIETAJ: autopilot wlaczony tylko na JEDNYM komputerze (inaczej podwojne rolki i podwojne wydatki).
pause
