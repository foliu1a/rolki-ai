@echo off
title rolki-ai - aktualizacja
cd /d "%~dp0"
echo Zatrzymuje panel (jesli dziala)...
curl -s -m 5 -X POST http://127.0.0.1:5077/api/zamknij >nul 2>&1
rem Panel zamyka sie dopiero w bezpiecznym miejscu - NIGDY w trakcie wysylania rolki do Higgsfield/yapper (osierocony job
rem = druga oplata). Rolka, ktora juz sie generuje, dokonczy sie sama po ponownym uruchomieniu (ten sam job, bez doplaty).
rem Czekamy, az panel przestanie odpowiadac - inaczej nowy panel by nie wstal (port zajety).
set /a CZEKAM=0
:czekaj
"%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul
curl -s -m 2 -o nul http://127.0.0.1:5077/api/stan >nul 2>&1
if errorlevel 1 goto zamkniety
set /a CZEKAM+=1
if %CZEKAM%==1 echo Panel konczy biezacy krok (np. wysyla rolke do Higgsfield) - czekam, nie zamykaj tego okna...
if %CZEKAM% GEQ 900 goto za_dlugo
goto czekaj
:za_dlugo
echo.
echo Panel nie zamknal sie przez 30 minut. Zrob zrzut ekranu tego okna i wyslij go Claude'owi.
pause
exit /b 1
:zamkniety
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
python -m pip install -q flask pytest pillow
python -m pytest -q
echo.
echo Odswiezam skrot "Rolki AI" na pulpicie...
cscript.exe //nologo "%~dp0skroty.vbs" pulpit
echo.
echo Gotowe. Uruchamiam panel...
call panel.bat
