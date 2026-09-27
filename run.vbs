Option Explicit
Dim fso, sh, base, py
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
If fso.FileExists(base & "\.venv\Scripts\pythonw.exe") Then
  py = base & "\.venv\Scripts\pythonw.exe"
Else
  py = "pythonw.exe"
End If
sh.Run """" & py & """ -m endfieldmodcontroller", 0, False
