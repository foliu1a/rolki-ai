@echo off
title rolki-ai - aktualizacja
cd /d "%~dp0"
echo Zatrzymuje panel (jesli dziala)...
curl -s -m 3 -X POST http://127.0.0.1:5077/api/zamknij >nul 2>&1
timeout /t 2 /nobreak >nul
echo Pobieram najnowsza wersje programu...
git pull origin main-mj7alw
if errorlevel 1 (
  echo.
  echo Nie udalo sie pobrac. Zrob zrzut ekranu tego okna i wyslij go Claude'owi.
  pause
  exit /b 1
)
echo.
echo Sprawdzam biblioteki i testy (chwile to trwa)...
python -m pip install -q flask pytest
python -m pytest -q
echo.
echo Odswiezam skrot "Rolki AI" na pulpicie...
cscript.exe //nologo "%~dp0skroty.vbs" pulpit
echo.
echo Gotowe. Uruchamiam panel...
call panel.bat
