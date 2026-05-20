@echo off
chcp 65001 >nul
title ASMR Helper - Desktop GUI

set PROJECT_ROOT=%~dp0
set VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe
set DESKTOP_DIR=%PROJECT_ROOT%desktop
set BACKEND_PORT=8000

cd /d "%PROJECT_ROOT%"

:: ── Check Python environment ──
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python virtual environment not found.
    echo         Please run setup.ps1 first.
    pause
    exit /b 1
)

:: ── Check Node.js ──
where node >nul 2>nul
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js first.
    pause
    exit /b 1
)

:: ── Check if backend port is already in use ──
netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [INFO] Backend already running on port %BACKEND_PORT%.
    goto launch_frontend
)

:: ── Start Python backend in a separate window ──
echo.
echo ========================================
echo   Starting backend server...
echo ========================================
start "ASMR Helper Backend" /D "%PROJECT_ROOT%" "%VENV_PYTHON%" -m src.api.http --port %BACKEND_PORT%

:: ── Wait for backend to be ready ──
echo [INFO] Waiting for backend to start...
set RETRIES=0
:wait_backend
    timeout /t 1 /nobreak >nul
    set /a RETRIES+=1
    if %RETRIES% gtr 30 (
        echo [ERROR] Backend failed to start within 30 seconds.
        pause
        exit /b 1
    )
    curl -s http://localhost:%BACKEND_PORT%/health >nul 2>nul
    if errorlevel 1 goto wait_backend

echo [OK] Backend is ready.

:launch_frontend
:: ── Launch desktop app ──
echo.
echo ========================================
echo   Launching ASMR Helper Desktop...
echo ========================================
echo.

:: Try built exe first, fallback to dev mode
set EXE_PATH=%DESKTOP_DIR%\src-tauri\target\debug\asmr-helper.exe
if exist "%EXE_PATH%" (
    echo [INFO] Launching built application...
    start "" "%EXE_PATH%"
) else (
    echo [INFO] No built app found, starting dev mode...
    echo [INFO] This may take a moment on first run.
    cd /d "%DESKTOP_DIR%"
    npx tauri dev
)

exit /b 0
