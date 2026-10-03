' Uruchamia panel rolki-ai z autopilotem w tle (bez okna). Uzywane przez autostart.bat (Harmonogram zadan Windows).
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = Replace(WScript.ScriptFullName, WScript.ScriptName, "")
sh.Run "python app.py --autopilot --bez-przegladarki", 0, False
