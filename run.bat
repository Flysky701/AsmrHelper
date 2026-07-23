@echo off
chcp 65001 >nul
setlocal

set PROJECT_ROOT=%~dp0
set VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe

cd /d "%PROJECT_ROOT%"

if /I "%~1"=="api" goto api
if /I "%~1"=="test" goto test
if /I "%~1"=="desktop" goto desktop
if "%~1"=="" goto desktop

echo Usage:
echo   run.bat            Start the desktop application
echo   run.bat desktop    Start the desktop application
echo   run.bat api        Start only the HTTP API on port 8000
echo   run.bat test       Verify the Python startup environment
exit /b 1

:check_python
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Project environment not found.
    echo         Run: powershell -ExecutionPolicy Bypass -File .\setup.ps1
    exit /b 1
)
exit /b 0

:api
call :check_python || exit /b 1
"%VENV_PYTHON%" -m src.api.http --host 127.0.0.1 --port 8000
exit /b %errorlevel%

:test
call :check_python || exit /b 1
"%VENV_PYTHON%" scripts\verify_env.py
exit /b %errorlevel%

:desktop
call "%PROJECT_ROOT%GUIRun.bat"
exit /b %errorlevel%
