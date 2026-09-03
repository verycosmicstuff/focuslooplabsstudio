@echo off
title SaveSpace Pro Launcher
cd /d "%~dp0"
echo Starting SaveSpace Pro Desktop App...
"C:\Users\Sunny\AppData\Local\Programs\Python\Python311\python.exe" main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application stopped or encountered an error.
    pause
)
