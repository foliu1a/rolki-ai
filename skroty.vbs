' Skroty dla rolki-ai (bez praw administratora):
'   wscript skroty.vbs pulpit          -> skrot "Rolki AI" na pulpicie (ikona static\rolki.ico; klik = panel w przegladarce)
'   wscript skroty.vbs autostart       -> skrot w folderze Autostart Windows: panel + autopilot startuja w tle po zalogowaniu
'   wscript skroty.vbs autostart-usun  -> usuwa skrot z Autostartu
' Uzywane przez: skrot-na-pulpit.bat, autostart.bat, autostart-usun.bat, aktualizuj.bat, instaluj.bat.
Option Explicit
Dim sh, fso, katalog, ikona, co, pulpit, autostart, wscriptExe
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
katalog = fso.GetParentFolderName(WScript.ScriptFullName)
ikona = katalog & "\static\rolki.ico"
co = "pulpit"
If WScript.Arguments.Count > 0 Then co = LCase(WScript.Arguments(0))
pulpit = sh.SpecialFolders("Desktop")
autostart = sh.SpecialFolders("Startup")
wscriptExe = fso.BuildPath(fso.GetSpecialFolder(1), "wscript.exe")

Sub Skrot(sciezka, cel, argumenty, opis)
  Dim s
  Set s = sh.CreateShortcut(sciezka)
  s.TargetPath = cel
  s.Arguments = argumenty
  s.WorkingDirectory = katalog
  If fso.FileExists(ikona) Then s.IconLocation = ikona & ",0"
  s.Description = opis
  s.Save
End Sub

Select Case co
  Case "pulpit"
    Skrot pulpit & "\Rolki AI.lnk", wscriptExe, """" & katalog & "\rolki.vbs""", "Rolki AI - panel (fabryka rolek)"
    WScript.Echo "Skrot 'Rolki AI' jest na pulpicie."
  Case "autostart"
    Skrot autostart & "\Rolki AI (autostart).lnk", wscriptExe, """" & katalog & "\start-cicho.vbs""", "Rolki AI - panel + autopilot w tle po zalogowaniu"
    WScript.Echo "Autostart wlaczony: " & autostart & "\Rolki AI (autostart).lnk"
  Case "autostart-usun"
    If fso.FileExists(autostart & "\Rolki AI (autostart).lnk") Then fso.DeleteFile autostart & "\Rolki AI (autostart).lnk"
    WScript.Echo "Autostart wylaczony."
  Case Else
    WScript.Echo "Nieznane: " & co & " (pulpit | autostart | autostart-usun)"
    WScript.Quit 1
End Select
