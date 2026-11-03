@echo off
setlocal
cd /d "%~dp0"
echo Looking for Windows Python 3.10+ with Tcl/Tk...
if not "%~1"=="" (
    call :try_python "%~1"
    if errorlevel 1 goto missing
    goto create_venv
)
if defined MODBUS_PYTHON_EXE (
    call :try_python "%MODBUS_PYTHON_EXE%"
    if errorlevel 1 goto missing
    goto create_venv
)
call :try_python ".venv-windows\Scripts\python.exe"
if not errorlevel 1 goto install
py -3.12 -c "import sys, tkinter, venv, ensurepip; assert sys.platform == 'win32'" >nul 2>nul
if not errorlevel 1 (
    py -3.12 -m venv .venv-windows
    if errorlevel 1 goto failed
    goto install
)
py -3 -c "import sys, tkinter, venv, ensurepip; assert sys.platform == 'win32'; assert sys.version_info >= (3,10)" >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv .venv-windows
    if errorlevel 1 goto failed
    goto install
)
call :try_python python
if not errorlevel 1 goto create_venv
call :try_python python3
if not errorlevel 1 goto create_venv
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "%ProgramFiles(x86)%\Python3*") do (
    call :try_python "%%~fD\python.exe"
    if not errorlevel 1 goto create_venv
)
:missing
echo.
echo No usable Python was detected. This is not an EXE build success.
echo If Python is installed, enter its full python.exe path below.
echo Otherwise install Python 3.12 x64 from https://www.python.org/downloads/windows/
echo Include Tcl/Tk and pip. Then run this script again.
set "MODBUS_PYTHON_INPUT="
set /p "MODBUS_PYTHON_INPUT=Full path to python.exe (Enter to exit): "
if not defined MODBUS_PYTHON_INPUT exit /b 1
set "MODBUS_PYTHON_INPUT=%MODBUS_PYTHON_INPUT:"=%"
call :try_python "%MODBUS_PYTHON_INPUT%"
if errorlevel 1 (
    echo That interpreter is unavailable, older than 3.10, or missing Tcl/Tk or venv.
    pause
    exit /b 1
)
:create_venv
echo Using: "%MODBUS_BUILD_PYTHON%"
"%MODBUS_BUILD_PYTHON%" -m venv .venv-windows
if errorlevel 1 goto failed
:install
".venv-windows\Scripts\python.exe" -m pip install --log build-windows-pip.log -r requirements-windows.txt
if errorlevel 1 goto failed
".venv-windows\Scripts\python.exe" build_windows.py
if errorlevel 1 goto failed
if not exist "dist\ModbusTLS.exe" goto failed
echo.
echo Success: %~dp0dist\ModbusTLS.exe
pause
exit /b 0
:failed
echo Build failed. See the error above.
echo Dependency log: %~dp0build-windows-pip.log
pause
exit /b 1
:try_python
"%~1" -c "import sys, tkinter, venv, ensurepip; assert sys.platform == 'win32'; assert sys.version_info >= (3,10)" >nul 2>nul
if errorlevel 1 exit /b 1
set "MODBUS_BUILD_PYTHON=%~1"
exit /b 0
