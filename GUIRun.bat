@echo off
chcp 65001 >nul
title ASMR Helper - Desktop GUI
setlocal

set PROJECT_ROOT=%~dp0
set VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe
set DESKTOP_DIR=%PROJECT_ROOT%desktop
set BACKEND_PORT=8000
set BACKEND_HEALTH_URL=http://127.0.0.1:%BACKEND_PORT%/health
set EXE_PATH=%DESKTOP_DIR%\src-tauri\target\debug\asmr-helper.exe
set DIST_INDEX=%DESKTOP_DIR%\dist\index.html

cd /d "%PROJECT_ROOT%"

:: Check Python environment
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python virtual environment not found.
    echo         Please run setup.ps1 first.
    pause
    exit /b 1
)

:: Check Node.js
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js first.
    pause
    exit /b 1
)

:: If port is already occupied, make sure it is really our backend.
netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
    call :check_backend_health
    if errorlevel 1 (
        echo [ERROR] Port %BACKEND_PORT% is already in use, but ASMR Helper backend is not healthy.
        echo         Please free the port or stop the conflicting process, then try again.
        pause
        exit /b 1
    )
    echo [INFO] Backend already running and healthy on port %BACKEND_PORT%.
    goto launch_frontend
)

:: Start Python backend in a separate window
echo.
echo ========================================
echo   Starting backend server...
echo ========================================
start "ASMR Helper Backend" /D "%PROJECT_ROOT%" "%VENV_PYTHON%" -m src.api.http --host 127.0.0.1 --port %BACKEND_PORT%

:: Wait for backend to be ready
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
    call :check_backend_health
    if errorlevel 1 goto wait_backend

echo [OK] Backend is ready.

:launch_frontend
echo.
echo ========================================
echo   Launching ASMR Helper Desktop...
echo ========================================
echo.

:: Try built exe first, fallback to dev mode only when dist is unavailable.
if exist "%EXE_PATH%" if exist "%DIST_INDEX%" (
    echo [INFO] Launching built application...
    start "" "%EXE_PATH%"
    exit /b 0
)

if not exist "%EXE_PATH%" (
    echo [INFO] No built app found, starting dev mode...
) else (
    echo [INFO] Built app found but frontend dist is missing, starting dev mode...
)
echo [INFO] This may take a moment on first run.
cd /d "%DESKTOP_DIR%"
set VITE_API_BASE=http://127.0.0.1:%BACKEND_PORT%/api/v1
npx tauri dev
exit /b %errorlevel%

:check_backend_health
curl -s "%BACKEND_HEALTH_URL%" | findstr /C:"\"status\":\"ok\"" >nul 2>nul
exit /b %errorlevel%
