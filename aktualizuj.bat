@echo off
title rolki-ai - aktualizacja
cd /d "%~dp0"
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
echo Gotowe. Uruchamiam panel...
call panel.bat
