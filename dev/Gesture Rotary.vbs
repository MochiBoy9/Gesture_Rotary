' Runs RotaryUI from source without a console window (runs setup on first launch).
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
here = fs.GetParentFolderName(fs.GetParentFolderName(WScript.ScriptFullName))
venv = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\GestureRotary\venv"
If Not fs.FileExists(venv & "\Scripts\pythonw.exe") Then
  sh.Run """" & here & "\dev\setup.bat""", 1, True
End If
sh.CurrentDirectory = here
sh.Run """" & venv & "\Scripts\pythonw.exe"" -m rotary", 0, False
