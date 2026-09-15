@echo off
title Focusloop Labs Launcher
cd /d "%~dp0"
echo Starting Focusloop Labs Desktop App...

set "PYTHON_EXE="
if exist "%~dp0python\python.exe" set "PYTHON_EXE=%~dp0python\python.exe"
if not defined PYTHON_EXE if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON_EXE where python >nul 2>nul && set "PYTHON_EXE=python"

if not defined PYTHON_EXE (
    echo.
    echo [ERROR] Python 3.11 runtime could not be located.
    echo Please make sure the 'python' folder is included or Python is installed on your PATH.
    pause
    exit /b 1
)

"%PYTHON_EXE%" main.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application stopped or encountered an error.
    pause
)
