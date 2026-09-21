Option Explicit

Dim fileSystem, shell, projectRoot, command

Set fileSystem = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
projectRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)

command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " & Quote(projectRoot & "\scripts\start_desktop_app.ps1")
shell.Run command, 0, False

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
