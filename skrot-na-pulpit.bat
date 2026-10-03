@echo off
title rolki-ai - skrot na pulpit
cd /d "%~dp0"
wscript.exe //nologo "%~dp0skroty.vbs" pulpit
echo Gotowe: na pulpicie jest skrot "Rolki AI" (dwa kliki = panel).
pause
