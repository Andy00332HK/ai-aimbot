@echo off
rem AI Aimbot 一鍵安裝：偵測 NVIDIA GPU 並安裝對應版本的 PyTorch 與套件
setlocal
echo ============================================
echo   AI Aimbot 安裝程式
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo [錯誤] 找不到 python，請先安裝 Python 3.10+ 並勾選 Add to PATH。
    pause
    exit /b 1
)

echo [1/3] 清除 pip 環境限制變數（避免第三方 constraints 干擾）...
set PIP_CONSTRAINT=

echo [2/3] 偵測 NVIDIA GPU...
nvidia-smi >nul 2>nul
if errorlevel 1 (
    echo   未偵測到 NVIDIA GPU - 安裝 CPU 版 PyTorch...
    python -m pip install torch torchvision
) else (
    for /f "tokens=1 delims=," %%a in ('nvidia-smi --query-gpu^=name --format^=csv^,noheader') do echo   偵測到 GPU: %%a
    echo   安裝 CUDA 12.6 版 PyTorch...
    python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
)

echo [3/3] 安裝其餘套件...
python -m pip install ultralytics opencv-python mss pynput dxcam lapx interception-python pywin32

echo.
echo ============================================
echo   安裝完成！執行 python main.py 啟動
echo ============================================
pause
