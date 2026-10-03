' Skrot "Rolki AI" na pulpicie uruchamia ten plik:
'   - panel juz dziala (np. z autostartu)  -> tylko otwiera http://localhost:5077 w przegladarce
'   - panel nie dziala                      -> uruchamia go w tle (python app.py --autopilot) i otwiera przegladarke, gdy odpowie
' Bez czarnego okna konsoli. Jesli panel nie wstanie w 30 s - komunikat, zeby kliknac panel.bat (tam widac blad).
Option Explicit
Dim sh, katalog, i
Set sh = CreateObject("WScript.Shell")
katalog = Replace(WScript.ScriptFullName, WScript.ScriptName, "")
sh.CurrentDirectory = katalog

Function PanelDziala()
  Dim h
  PanelDziala = False
  On Error Resume Next
  Set h = CreateObject("MSXML2.XMLHTTP")
  h.Open "GET", "http://127.0.0.1:5077/api/stan", False
  h.Send
  If Err.Number = 0 Then
    If h.Status = 200 Then PanelDziala = True
  End If
  On Error GoTo 0
End Function

If PanelDziala() Then
  sh.Run "http://localhost:5077", 1, False
Else
  sh.Run "python app.py --autopilot --bez-przegladarki", 0, False
  For i = 1 To 60
    WScript.Sleep 500
    If PanelDziala() Then Exit For
  Next
  If PanelDziala() Then
    sh.Run "http://localhost:5077", 1, False
  Else
    MsgBox "Panel nie wystartowal. Kliknij dwa razy w panel.bat (w folderze rolki-ai) - tam bedzie widac, co nie gra.", 48, "Rolki AI"
  End If
End If
