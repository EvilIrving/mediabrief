@echo off
chcp 65001 >nul 2>&1
echo MediaBrief - Windows Installer
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
