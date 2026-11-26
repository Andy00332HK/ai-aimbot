@echo off
rem AI Aimbot launcher - double-click to run.
rem For in-game input, right-click this file > Run as administrator.
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH. Install Python 3.10+ and retry.
    pause
    exit /b 1
)
echo Starting AI Aimbot...
python main.py
if errorlevel 1 (
    echo.
    echo Exited with error code %errorlevel%.
    pause
)
