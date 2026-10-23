@echo off
cd /d "%~dp0\.."
where python >nul 2>nul || goto missing
where ffmpeg >nul 2>nul || goto missing
python -m venv .desktop-build
if errorlevel 1 goto failed
.desktop-build\Scripts\python -m pip install -e ".[build,local]"
if errorlevel 1 goto failed
.desktop-build\Scripts\python scripts\build_desktop.py
if errorlevel 1 goto failed
explorer dist
pause
exit /b 0
:missing
echo Install Python 3.12 and FFmpeg on this BUILD computer first.
:failed
echo Build failed. See the error above. No API key is required for building.
pause
exit /b 1
