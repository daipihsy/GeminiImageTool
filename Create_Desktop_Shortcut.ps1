# Create a Desktop shortcut for GeminiImageTool.
# Launched by the user from the Start Menu (via Explorer), so it runs OUTSIDE the
# installer's RedirectionGuard and works even when the Desktop is redirected (OneDrive).
try {
    $appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $desktop = [Environment]::GetFolderPath('Desktop')
    if ([string]::IsNullOrWhiteSpace($desktop)) { $desktop = Join-Path $env:USERPROFILE 'Desktop' }
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $desktop 'GeminiImageTool.lnk'))
    $lnk.TargetPath = Join-Path $appDir 'python\pythonw.exe'
    $lnk.Arguments = '"app.py"'
    $lnk.WorkingDirectory = $appDir
    $lnk.IconLocation = Join-Path $appDir 'python\pythonw.exe'
    $lnk.Description = 'GeminiImageTool'
    $lnk.Save()
} catch {
    # Desktop may be redirected/protected; ignore silently.
}
