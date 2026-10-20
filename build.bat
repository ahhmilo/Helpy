@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 exit /b 1

set "CLEAN_FLAG="
set "CHECK_ONLY="
:args
if "%~1"=="" goto :find_python
if /i "%~1"=="--help" goto :help
if /i "%~1"=="--clean" (
  set "CLEAN_FLAG=--clean"
  shift
  goto :args
)
if /i "%~1"=="--check" (
  set "CHECK_ONLY=1"
  shift
  goto :args
)
echo Unknown option: %~1
exit /b 2

:find_python
rem Reuse our isolated environment; do not modify globally installed packages.
if exist ".venv-build\Scripts\python.exe" (
  set PYTHON_CMD=".venv-build\Scripts\python.exe"
  goto :preflight
)
py -3 -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
  goto :preflight
)
python -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto :preflight
)
echo Python 3.10 or newer was not found. Install Python with Tcl/Tk support.
goto :fail

:preflight
echo Checking Python and Tcl/Tk...
%PYTHON_CMD% -c "import sys, tkinter; assert sys.version_info[:2] >= (3, 10), 'Python 3.10+ required'; t = tkinter.Tcl(); print('Python:', sys.executable); print('Tcl:', t.eval('info patchlevel')); print('Tk:', tkinter.TkVersion)"
if errorlevel 1 (
  echo Python or Tcl/Tk is unavailable. Repair the Python installation before building.
  goto :fail
)
if defined CHECK_ONLY (
  echo Preflight passed. No dependencies installed and no executable built.
  exit /b 0
)
if exist ".venv-build\Scripts\python.exe" goto :dependencies
echo Creating isolated build environment...
%PYTHON_CMD% -m venv .venv-build
if errorlevel 1 goto :fail
set PYTHON_CMD=".venv-build\Scripts\python.exe"

:dependencies
echo Checking build requirements...
%PYTHON_CMD% -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail
%PYTHON_CMD% -m pip check
if errorlevel 1 goto :fail
echo Generating icons...
%PYTHON_CMD% tools\build_icons.py
if errorlevel 1 goto :fail
echo Building Helpy... Close any running dist\Helpy.exe before rebuilding.
rem Keep the cache for faster repeat builds; use --clean to rebuild from scratch.
%PYTHON_CMD% -m PyInstaller --noconfirm %CLEAN_FLAG% --noupx --windowed --onefile --name Helpy --icon assets\helpy.ico ^
  --add-data "assets\helpy-icon.png;assets" --add-data "assets\helpy.ico;assets" ^
  --add-data "assets\vendor;assets\vendor" --add-data "assets\notepad.js;assets" --add-data "assets\notepad.css;assets" ^
  --collect-all webview --collect-all pythonnet --collect-all clr_loader ^
  --collect-all dxcam --collect-all sounddevice --collect-submodules comtypes ^
  --hidden-import pystray._win32 --hidden-import PIL.ImageTk --hidden-import PIL._tkinter_finder --hidden-import tkinter ^
  helpy.pyw
if errorlevel 1 goto :fail
echo.
echo Done. Your app is in dist\Helpy.exe
pause
exit /b 0
:fail
echo Build failed. Scroll up for the error.
if defined CHECK_ONLY exit /b 1
pause
exit /b 1

:help
echo Usage: build.bat [--clean] [--check] [--help]
echo   No options: build dist\Helpy.exe using an isolated .venv-build environment.
echo   --clean: clear PyInstaller's cache before building.
echo   --check: check Python and Tcl/Tk only; do not install or build anything.
echo   --help: show this help without making changes.
exit /b 0
