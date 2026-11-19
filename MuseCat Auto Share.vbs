Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = appDir & "\.venv\Scripts\pythonw.exe"
mainPy = appDir & "\main.py"

shell.CurrentDirectory = appDir

If fso.FileExists(pythonw) Then
    shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & mainPy & Chr(34), 0, False
Else
    ' Ilk kurulum yapilmadiysa run.bat ile kurulumu baslat
    shell.Run Chr(34) & appDir & "\run.bat" & Chr(34), 1, False
End If
