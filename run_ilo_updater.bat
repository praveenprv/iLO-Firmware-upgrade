@echo off
setlocal enabledelayedexpansion
title HPE iLO Firmware Upgrade Automation Suite

echo ===============================================================================
echo            HPE iLO FIRMWARE UPGRADE AUTOMATION SUITE
echo            Redfish RESTful API - Windows Administrator Launcher
echo ===============================================================================
echo.

:: 1. Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 3 was not found in your system PATH.
    echo Please install Python 3.8 or higher from https://www.python.org/
    echo Make sure to check the option: "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: 2. Setup Virtual Environment
if not exist "venv\Scripts\python.exe" (
    echo [INFO] Virtual environment not found. Creating 'venv'...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create Python virtual environment.
        pause
        exit /b 1
    )
    echo [INFO] Installing required dependencies...
    venv\Scripts\pip install --upgrade pip
    venv\Scripts\pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies from requirements.txt.
        pause
        exit /b 1
    )
)

:: 3. Launch the Application
echo.
echo [INFO] Starting HPE iLO Firmware Upgrade Tool...
echo.

venv\Scripts\python.exe main.py %*

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Application exited with error code %errorlevel%.
)

echo.
echo ===============================================================================
echo Execution finished. Press any key to close this window.
echo ===============================================================================
pause >nul
