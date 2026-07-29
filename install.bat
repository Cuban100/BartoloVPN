@echo off
REM BartoloVPN bootstrap installer for Windows CMD.
REM This just hands off to install.ps1, which does the real work (detecting/
REM installing Python, then handing off to vpn-setup.py) - PowerShell is
REM needed for the download/silent-install steps that CMD can't do cleanly.
setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install.ps1" %*
exit /b %ERRORLEVEL%
