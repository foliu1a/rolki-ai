@echo off
cd /d "%~dp0"
echo [1/4] Biblioteki Pythona dla panelu...
python -m pip install flask pytest
echo.
echo [2/4] CLI Higgsfield (wymaga Node.js / npm)...
call npm install -g --allow-scripts=@higgsfield/cli @higgsfield/cli
echo.
echo [3/4] Skille Higgsfield dla Claude Code (opcjonalne)...
call npx -y skills add higgsfield-ai/skills -g -a claude-code -s higgsfield-generate -s higgsfield-soul-id -y --copy
echo.
echo [4/4] Szybki test kodu (bez kredytow) + skrot "Rolki AI" na pulpicie...
python -m pytest -q
cscript.exe //nologo "%~dp0skroty.vbs" pulpit
echo.
echo Gotowe. Teraz zaloguj CLI Higgsfield (otworzy sie przegladarka):
echo     zaloguj-higgsfield.bat
echo Klucze yapper.so / sync.so wpiszesz w panelu (zakladka Konta).
echo Panel: skrot "Rolki AI" na pulpicie (albo panel.bat)   Autostart z Windows: autostart.bat   Male okno: http://localhost:5077/widget
pause
