' GeminiImageTool silent launcher
' Runs pythonw.exe with app.py in the background (no console window)
Option Explicit
Dim fso, shell, scriptDir, pyExe, appPy, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pyExe = scriptDir & "\python\pythonw.exe"
appPy = scriptDir & "\app.py"
shell.CurrentDirectory = scriptDir
cmd = """" & pyExe & """ """ & appPy & """"
shell.Run cmd, 0, False
