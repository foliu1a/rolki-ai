@echo off
rem Male okno z saldem i kolejka (panel musi byc wlaczony - panel.bat). Dziala w Chrome/Edge jako "aplikacja".
cd /d "%~dp0"
set CHROME="%ProgramFiles%\Google\Chrome\Application\chrome.exe"
set EDGE="%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if exist %CHROME% (
  start "" %CHROME% --app=http://localhost:5077/widget --window-size=360,300
) else if exist %EDGE% (
  start "" %EDGE% --app=http://localhost:5077/widget --window-size=360,300
) else (
  start "" http://localhost:5077/widget
)
