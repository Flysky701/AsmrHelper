@echo off
chcp 65001 >nul
title Build Frontend - ASMR Helper
setlocal

set PROJECT_ROOT=%~dp0..
set DESKTOP_DIR=%PROJECT_ROOT%\desktop

echo.
echo ========================================
echo   Building ASMR Helper Desktop Frontend
echo ========================================
echo.

:: Check Node.js
where node >nul 2>nul
if errorlevel 1 (
    for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\Node.js" /v InstallPath 2^>nul ^| findstr InstallPath') do set NODE_HOME=%%B
    if defined NODE_HOME set PATH=%NODE_HOME%;%PATH%
)
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js first.
    pause
    exit /b 1
)

:: Install dependencies if needed
if not exist "%DESKTOP_DIR%\node_modules" (
    echo [INFO] Installing dependencies...
    cd /d "%DESKTOP_DIR%"
    call npm ci
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
)

:: Build Tauri app
echo [INFO] Building Tauri app (this may take a moment)...
cd /d "%DESKTOP_DIR%"
call npx tauri build
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the output above for details.
    pause
    exit /b 1
)

echo.
echo [OK] Build complete.
echo     Exe: %DESKTOP_DIR%\src-tauri\target\release\asmr-helper.exe
echo.
pause
