@echo off
setlocal
where pwsh.exe >nul 2>&1
if %errorlevel%==0 (
  pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-SwitchFleet.ps1" %*
) else (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-SwitchFleet.ps1" %*
)
exit /b %errorlevel%
