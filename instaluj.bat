@echo off
echo [1/3] Biblioteki Pythona dla panelu...
python -m pip install flask requests
echo.
echo [2/3] CLI Higgsfield (wymaga Node.js / npm)...
call npm install -g --allow-scripts=@higgsfield/cli @higgsfield/cli
echo.
echo [3/3] Skille Higgsfield dla Claude Code (opcjonalne)...
call npx -y skills add higgsfield-ai/skills -g -a claude-code -s higgsfield-generate -s higgsfield-soul-id -y --copy
echo.
echo Gotowe. Teraz zaloguj CLI (otworzy sie przegladarka):
echo     higgsfield auth login
echo Panel odpalasz przez: panel.bat     Fabryka: python fabryka.py status
pause
