@echo off
setlocal
cd /d "%~dp0"
where pwsh.exe >nul 2>nul
if errorlevel 1 (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_env.ps1" %*
) else (
  pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_env.ps1" %*
)
set "setup_result=%errorlevel%"
if not "%setup_result%"=="0" (
  echo Setup encountered an error. Press any key to exit.
  pause
)
endlocal & exit /b %setup_result%
