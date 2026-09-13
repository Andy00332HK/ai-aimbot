@echo off
rem AI Aimbot — 以系統管理員權限啟動（會彈出 UAC 確認視窗，按「是」）
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel%==0 (
    echo 已具有管理員權限，直接啟動...
    python main.py
) else (
    echo 正在要求管理員權限，請在 UAC 視窗按「是」...
    powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList 'main.py' -WorkingDirectory '%~dp0' -Verb RunAs"
)
