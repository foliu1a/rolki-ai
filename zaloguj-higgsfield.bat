@echo off
title Logowanie Higgsfield (Firefox)
echo Otwieram logowanie w Firefoksie - zatwierdz tam i wroc tutaj.
echo.
python "%~dp0zaloguj_firefox.py"
echo.
echo --- sprawdzam konto ---
"%APPDATA%\npm\node_modules\@higgsfield\cli\vendor\hf.exe" account status
echo.
echo Jesli widzisz wyzej email i kredyty - gotowe. Mozesz zamknac to okno.
pause
