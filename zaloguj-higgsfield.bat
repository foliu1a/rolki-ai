@echo off
title Logowanie Higgsfield
echo Otwieram logowanie w przegladarce (Firefox, a jak go nie ma - domyslna). Zatwierdz tam i wroc tutaj.
echo.
python "%~dp0zaloguj_firefox.py"
echo.
echo --- sprawdzam konto ---
"%APPDATA%\npm\node_modules\@higgsfield\cli\vendor\hf.exe" account status
echo.
echo Jesli widzisz wyzej email i kredyty - gotowe. Mozesz zamknac to okno.
pause
