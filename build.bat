@echo off
cd /d "%~dp0"
echo Installing build requirements...
py -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo Building Helpy...
py -m PyInstaller --noconfirm --clean --windowed --onefile --name Helpy --icon helpy.ico ^
  --collect-all webview --collect-all pythonnet --collect-all clr_loader ^
  --collect-all dxcam --collect-submodules comtypes ^
  --hidden-import pystray._win32 --hidden-import PIL.ImageTk --hidden-import PIL._tkinter_finder --hidden-import tkinter ^
  helpy.pyw
if errorlevel 1 goto :fail
echo.
echo Done. Your app is in dist\Helpy.exe
pause
exit /b 0
:fail
echo Build failed. Scroll up for the error.
pause
exit /b 1
