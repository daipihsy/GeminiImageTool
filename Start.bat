@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PATH=%~dp0python;%PATH%"
echo Starting GeminiImageTool ...
echo Browser will open automatically at http://127.0.0.1:7860
echo Close this window to stop the app.
echo.
"%~dp0python\python.exe" "%~dp0app.py"
if errorlevel 1 (
  echo.
  echo ERROR: App crashed. See message above.
  pause
)