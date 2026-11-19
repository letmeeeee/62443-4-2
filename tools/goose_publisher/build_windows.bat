@echo off
setlocal
cd /d "%~dp0"
if not "%~1"=="" (
    set "GOOSE_BUILD_PYTHON=%~1"
    goto specified
)
if exist ".venv-windows\Scripts\python.exe" goto install
py -3.12 -c "import tkinter, struct; assert struct.calcsize('P') == 8" >nul 2>nul
if not errorlevel 1 (
    py -3.12 -m venv .venv-windows
    if errorlevel 1 goto failed
    goto install
)
py -3 -c "import sys, tkinter, struct; assert sys.version_info >= (3,10); assert struct.calcsize('P') == 8" >nul 2>nul
if errorlevel 1 goto missing
py -3 -m venv .venv-windows
if errorlevel 1 goto failed
goto install
:specified
"%GOOSE_BUILD_PYTHON%" -c "import sys, tkinter, struct; assert sys.version_info >= (3,10); assert struct.calcsize('P') == 8" >nul 2>nul
if errorlevel 1 goto missing
"%GOOSE_BUILD_PYTHON%" -m venv .venv-windows
if errorlevel 1 goto failed
:install
".venv-windows\Scripts\python.exe" -m pip install --log build-windows-pip.log -r requirements-windows.txt
if errorlevel 1 goto failed
".venv-windows\Scripts\python.exe" build_windows.py
if errorlevel 1 goto failed
if not exist "dist\GoosePublisher.exe" goto failed
echo Built: %~dp0dist\GoosePublisher.exe
exit /b 0
:missing
echo Install Windows Python 3.12 x64 with Tcl/Tk and pip.
echo Or run: build_windows.bat "C:\path\to\python.exe"
pause
exit /b 1
:failed
echo Build failed. See the output and build-windows-pip.log.
pause
exit /b 1
