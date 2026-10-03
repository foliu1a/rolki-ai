' Skrot "Rolki AI" na pulpicie uruchamia ten plik:
'   - panel juz dziala (np. z autostartu)  -> tylko otwiera http://localhost:5077 w Firefoksie
'   - panel nie dziala                      -> uruchamia go w tle (python app.py --autopilot) i otwiera Firefoksa, gdy odpowie
' Firefox szukany w: App Paths (HKCU, HKLM), %ProgramFiles%, %ProgramFiles(x86)%, %LOCALAPPDATA%\Mozilla Firefox.
' Bez Firefoksa - domyslna przegladarka. Bez czarnego okna konsoli. Jesli panel nie wstanie w 30 s - komunikat (panel.bat pokaze blad).
Option Explicit
Dim sh, fso, katalog, i
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
katalog = Replace(WScript.ScriptFullName, WScript.ScriptName, "")
sh.CurrentDirectory = katalog
Const PANEL = "http://localhost:5077"

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

Function Firefox()
  ' Sciezka do firefox.exe albo "" (rejestr App Paths, potem typowe foldery instalacji).
  Dim k, p, kand
  Firefox = ""
  On Error Resume Next
  For Each k In Array("HKCU", "HKLM")
    Err.Clear
    p = sh.RegRead(k & "\Software\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe\")
    If Err.Number = 0 Then
      p = Trim(Replace(p, """", ""))
      If p <> "" Then
        If fso.FileExists(p) Then
          Firefox = p
          Exit Function
        End If
      End If
    End If
  Next
  On Error GoTo 0
  For Each kand In Array(sh.ExpandEnvironmentStrings("%ProgramFiles%") & "\Mozilla Firefox\firefox.exe", _
                         sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Mozilla Firefox\firefox.exe", _
                         sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Mozilla Firefox\firefox.exe")
    If fso.FileExists(kand) Then
      Firefox = kand
      Exit Function
    End If
  Next
End Function

Sub OtworzPanel()
  Dim ff
  ff = Firefox()
  If ff <> "" Then
    sh.Run """" & ff & """ -new-tab " & PANEL, 1, False
  Else
    sh.Run PANEL, 1, False
  End If
End Sub

If PanelDziala() Then
  OtworzPanel
Else
  sh.Run "python app.py --autopilot --bez-przegladarki", 0, False
  For i = 1 To 60
    WScript.Sleep 500
    If PanelDziala() Then Exit For
  Next
  If PanelDziala() Then
    OtworzPanel
  Else
    MsgBox "Panel nie wystartowal. Kliknij dwa razy w panel.bat (w folderze rolki-ai) - tam bedzie widac, co nie gra.", 48, "Rolki AI"
  End If
End If
