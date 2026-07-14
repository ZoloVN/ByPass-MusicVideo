@echo off
chcp 65001 >nul
title Setup - Tach Nhac Nen
color 0B

echo.
echo  ============================================
echo   TACH NHAC NEN - Cai dat lan dau (~900MB)
echo  ============================================
echo.

py -3.11 --version >nul 2>&1
if %errorlevel%==0 (
    echo [1/6] Python 3.11: OK
    goto :clean
)

echo [1/6] Tai Python 3.11 (~25MB)...
set PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
set PY_INST=%TEMP%\py311.exe
powershell -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest '%PY_URL%' -OutFile '%PY_INST%' -UseBasicParsing"
if not exist "%PY_INST%" (
    echo [LOI] Tai that bai. Kiem tra ket noi mang.
    pause & exit /b 1
)
echo     Dang cai Python 3.11...
"%PY_INST%" /quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1
del "%PY_INST%"
echo     Python 3.11: OK

:clean
echo [2/6] Xoa xung dot...
py -3.11 -m pip uninstall torchaudio torchvision audio-separator -y >nul 2>&1
echo     OK

echo [3/6] Cai PyTorch CPU (~500MB)...
echo     Dang tai, vui long cho...
py -3.11 -m pip install torch==2.3.1+cpu torchaudio==2.3.1+cpu --index-url https://download.pytorch.org/whl/cpu -q
echo     PyTorch: OK

echo [4/6] Cai Demucs + thu vien...
py -3.11 -m pip install demucs soundfile "numpy<2.0" -q
echo     Demucs: OK

echo [5/6] Cai Librosa + SciPy (xu ly am thanh)...
py -3.11 -m pip install librosa scipy -q
echo     Librosa + SciPy: OK

echo [6/6] Kiem tra ffmpeg...
ffmpeg -version >nul 2>&1
if %errorlevel%==0 (
    echo     ffmpeg: OK
) else (
    echo     ffmpeg: CHUA CAI - can de xu ly video .mp4
    echo     Cai bang lenh: winget install ffmpeg
)

echo.
echo  ============================================
echo   Cai dat hoan tat!
echo   Chay run.bat de mo chuong trinh.
echo  ============================================
echo.
pause
