@echo off
chcp 65001 >nul
title Tach Nhac Nen v5

py -3.11 --version >nul 2>&1
if %errorlevel%==0 goto :run

echo Python 3.11 not found! Run setup_full.bat first.
pause
exit /b 1

:run
py -3.11 "%~dp0tach_nhac_nen_ui.py"
if errorlevel 1 (
    echo.
    echo Crash! Run setup_full.bat first.
    pause
)
