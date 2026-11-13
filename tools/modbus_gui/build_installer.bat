@echo off
setlocal
cd /d "%~dp0"
set "MODBUS_ISCC="
if defined ISCC_EXE if exist "%ISCC_EXE%" set "MODBUS_ISCC=%ISCC_EXE%"
if not defined MODBUS_ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "MODBUS_ISCC=%%I"
if not defined MODBUS_ISCC for %%I in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe") do if exist "%%~I" set "MODBUS_ISCC=%%~I"
if not defined MODBUS_ISCC (
    echo Inno Setup 6 is required to create the installer.
    echo Install from https://jrsoftware.org/isdl.php then run this script again.
    echo Or set ISCC_EXE to the full path to ISCC.exe.
    pause
    exit /b 1
)
call build_windows.bat %*
if errorlevel 1 exit /b 1
"%MODBUS_ISCC%" ModbusTLS.iss
if errorlevel 1 goto failed
if not exist "dist\ModbusTLS-Setup-2026.11.06.exe" goto failed
echo Installer created: %~dp0dist\ModbusTLS-Setup-2026.11.06.exe
pause
exit /b 0
:failed
echo Installer build failed. Do not distribute an older installer as this build.
pause
exit /b 1
