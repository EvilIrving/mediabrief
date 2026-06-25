@echo off
chcp 65001 >nul 2>&1
title MediaBrief

set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    echo Starting MediaBrief...
    echo.
    "%VENV_PYTHON%" "%SCRIPT_DIR%start.py" %*
) else (
    echo [Error] Virtual environment not found.
    echo Please run install.bat or install.ps1 first.
    echo.
    pause
)
