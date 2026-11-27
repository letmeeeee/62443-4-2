@echo off
setlocal
cd /d "%~dp0"
call build_windows.bat %1
if errorlevel 1 exit /b 1
if defined ISCC_EXE set "GOOSE_ISCC=%ISCC_EXE%"
if not defined GOOSE_ISCC for %%I in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe") do if exist "%%~I" set "GOOSE_ISCC=%%~I"
if not defined GOOSE_ISCC (
    echo Install Inno Setup 6 or set ISCC_EXE to its compiler path.
    pause
    exit /b 1
)
"%GOOSE_ISCC%" GoosePublisher.iss
if errorlevel 1 exit /b 1
if not exist "dist\GoosePublisher-Setup-2026.11.26.exe" exit /b 1
echo Built: %~dp0dist\GoosePublisher-Setup-2026.11.26.exe
pause
