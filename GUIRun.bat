@echo off
chcp 65001 >nul
title ASMR Helper - Desktop GUI
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0"
set "VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "DESKTOP_DIR=%PROJECT_ROOT%desktop"
set "BACKEND_PORT=8000"
set "BACKEND_HEALTH_URL=http://127.0.0.1:%BACKEND_PORT%/health"
set "LOG_DIR=%PROJECT_ROOT%logs"
set "BACKEND_LOG=%LOG_DIR%\backend.log"
set "BACKEND_PID_FILE=%LOG_DIR%\backend.pid"
set "BACKEND_STARTER=%PROJECT_ROOT%scripts\start_backend.ps1"
set "FRESHNESS_CHECKER=%PROJECT_ROOT%scripts\check_runtime_freshness.ps1"
set "RELEASE_EXE=%DESKTOP_DIR%\src-tauri\target\release\asmr-helper.exe"
set "LAUNCH_MODE=%~1"
set "BACKEND_STARTED=0"
set "BACKEND_PID="
set "PORT_PID="
set "FRONTEND_STATE="
set "RUNNING_BACKEND_STATE="
set "APP_EXIT=0"

cd /d "%PROJECT_ROOT%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python virtual environment not found.
    echo         Run: powershell -ExecutionPolicy Bypass -File .\setup.ps1
    goto launch_failed
)
"%VENV_PYTHON%" --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Project Python exists but cannot start.
    echo         Repair it with setup.ps1 -CleanReinstall -PythonPath ^<python.exe^>.
    goto launch_failed
)

if not defined LAUNCH_MODE (
    if exist "%RELEASE_EXE%" (
        call :get_frontend_state
        if /I "!FRONTEND_STATE!"=="fresh" (
            set "LAUNCH_MODE=--installed"
        ) else (
            echo [INFO] Desktop sources are newer than the installed release. Rebuilding...
            set "LAUNCH_MODE=--release"
        )
    ) else (
        set "LAUNCH_MODE=--dev"
    )
)

if /I "%LAUNCH_MODE%"=="--installed" goto frontend_ready
if /I "%LAUNCH_MODE%"=="--dev" goto check_dev_tools
if /I "%LAUNCH_MODE%"=="--release" goto check_dev_tools
echo [ERROR] Unknown launch mode: %LAUNCH_MODE%
echo         Supported: --installed, --dev, --release
goto launch_failed

:check_dev_tools
call :add_node_to_path
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found. Set ASMR_HELPER_NODE_HOME or install Node.js.
    goto launch_failed
)
where npm.cmd >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm.cmd not found beside Node.js.
    goto launch_failed
)
where cargo >nul 2>nul
if errorlevel 1 if exist "%USERPROFILE%\.cargo\bin\cargo.exe" set "PATH=%USERPROFILE%\.cargo\bin;!PATH!"
where cargo >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Rust/Cargo not found. Tauri development and builds require Rust.
    goto launch_failed
)
if not exist "%DESKTOP_DIR%\node_modules" (
    echo [INFO] Installing desktop dependencies...
    pushd "%DESKTOP_DIR%"
    call npm.cmd ci
    set "NPM_EXIT=!ERRORLEVEL!"
    popd
    if not "!NPM_EXIT!"=="0" (
        echo [ERROR] npm ci failed with code !NPM_EXIT!.
        goto launch_failed
    )
)

:frontend_ready
if /I "%LAUNCH_MODE%"=="--installed" if not exist "%RELEASE_EXE%" (
    echo [ERROR] Release application not found: %RELEASE_EXE%
    echo         Build it once with: GUIRun.bat --release
    goto launch_failed
)

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%BACKEND_PORT% " ^| findstr "LISTENING"') do if not defined PORT_PID set "PORT_PID=%%P"
if defined PORT_PID (
    call :check_backend_health
    if errorlevel 1 (
        echo [ERROR] Port %BACKEND_PORT% is occupied by a different or unhealthy process.
        goto show_backend_log
    )
    call :get_backend_state !PORT_PID!
    if /I "!RUNNING_BACKEND_STATE!"=="stale" goto restart_stale_backend
    echo [INFO] Reusing healthy backend on port %BACKEND_PORT%.
    call :runapp
    exit /b !APP_EXIT!
)

:start_backend
echo [INFO] Starting backend. Persistent log: %BACKEND_LOG%
for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%BACKEND_STARTER%" -ProjectRoot "%PROJECT_ROOT%." -PythonPath "%VENV_PYTHON%" -Port %BACKEND_PORT% -LogDir "%LOG_DIR%"`) do set "BACKEND_PID=%%P"
if not defined BACKEND_PID (
    echo [ERROR] Backend process could not be created.
    goto show_backend_log
)
set "BACKEND_STARTED=1"

echo [INFO] Waiting for backend PID !BACKEND_PID!...
set /a RETRIES=0
:wait_backend
powershell.exe -NoProfile -Command "Start-Sleep -Seconds 1" >nul 2>nul
set /a RETRIES+=1
"%VENV_PYTHON%" -c "import json,urllib.request; data=json.load(urllib.request.urlopen('%BACKEND_HEALTH_URL%',timeout=2)); raise SystemExit(0 if data.get('status') == 'ok' else 1)" >nul 2>nul
if not errorlevel 1 (
    call :runapp
    exit /b !APP_EXIT!
)
tasklist /FI "PID eq !BACKEND_PID!" /NH 2>nul | findstr /C:"!BACKEND_PID!" >nul
if errorlevel 1 (
    echo [ERROR] Backend exited before becoming healthy.
    goto show_backend_log
)
if !RETRIES! GEQ 30 (
    echo [ERROR] Backend did not become healthy within 30 seconds.
    goto show_backend_log
)
goto wait_backend

:restart_stale_backend
tasklist /FI "IMAGENAME eq asmr-helper.exe" /NH 2>nul | findstr /I /C:"asmr-helper.exe" >nul
if not errorlevel 1 (
    echo [ERROR] The running ASMR Helper uses an older backend.
    echo         Close the desktop window, then start it again to apply the update.
    set "APP_EXIT=1"
    goto cleanup
)
echo [INFO] Restarting the project backend because its sources changed after it started...
taskkill /PID !PORT_PID! /T /F >nul 2>nul
call :wait_for_process_exit !PORT_PID!
if errorlevel 1 (
    echo [ERROR] The outdated project backend could not be stopped.
    set "APP_EXIT=1"
    goto cleanup
)
call :remove_owned_pid_file !PORT_PID!
set "PORT_PID="
goto start_backend

:app_failed
echo [ERROR] Desktop build or launch failed with code !APP_EXIT!.

:cleanup
if "%BACKEND_STARTED%"=="1" if defined BACKEND_PID (
    echo [INFO] Stopping backend PID !BACKEND_PID!...
    taskkill /PID !BACKEND_PID! /T /F >nul 2>nul
    call :wait_for_process_exit !BACKEND_PID!
    if not errorlevel 1 call :remove_owned_pid_file !BACKEND_PID!
)
if not "!APP_EXIT!"=="0" (
    echo [INFO] Backend log: %BACKEND_LOG%
    pause
)
exit /b !APP_EXIT!

:show_backend_log
echo [INFO] Backend log: %BACKEND_LOG%
if exist "%BACKEND_LOG%" powershell.exe -NoProfile -Command "Get-Content -LiteralPath '%BACKEND_LOG%' -Tail 40"
set "APP_EXIT=1"
goto cleanup

:launch_failed
set "APP_EXIT=1"
goto cleanup

:check_backend_health
"%VENV_PYTHON%" -c "import json,urllib.request; data=json.load(urllib.request.urlopen('%BACKEND_HEALTH_URL%',timeout=2)); raise SystemExit(0 if data.get('status') == 'ok' else 1)" >nul 2>nul
exit /b %ERRORLEVEL%

:get_frontend_state
set "FRONTEND_STATE=unknown"
if not exist "%FRESHNESS_CHECKER%" exit /b 0
for /f "usebackq delims=" %%S in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%FRESHNESS_CHECKER%" -Mode Frontend -ProjectRoot "%PROJECT_ROOT%." -ArtifactPath "%RELEASE_EXE%"`) do set "FRONTEND_STATE=%%S"
exit /b 0

:get_backend_state
set "RUNNING_BACKEND_STATE=unknown"
if not exist "%FRESHNESS_CHECKER%" exit /b 0
for /f "usebackq delims=" %%S in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%FRESHNESS_CHECKER%" -Mode Backend -ProjectRoot "%PROJECT_ROOT%." -BackendProcessId %~1 -PidFile "%BACKEND_PID_FILE%"`) do set "RUNNING_BACKEND_STATE=%%S"
exit /b 0

:wait_for_process_exit
set /a EXIT_RETRIES=0
:wait_for_process_exit_loop
tasklist /FI "PID eq %~1" /NH 2>nul | findstr /C:"%~1" >nul
if errorlevel 1 exit /b 0
set /a EXIT_RETRIES+=1
if !EXIT_RETRIES! GEQ 20 exit /b 1
powershell.exe -NoProfile -Command "Start-Sleep -Milliseconds 250" >nul 2>nul
goto wait_for_process_exit_loop

:remove_owned_pid_file
if not exist "%BACKEND_PID_FILE%" exit /b 0
for /f "usebackq delims=" %%P in ("%BACKEND_PID_FILE%") do if "%%P"=="%~1" del /q "%BACKEND_PID_FILE%" >nul 2>nul
exit /b 0

:add_node_to_path
if defined ASMR_HELPER_NODE_HOME if exist "%ASMR_HELPER_NODE_HOME%\node.exe" set "PATH=%ASMR_HELPER_NODE_HOME%;!PATH!"
where node >nul 2>nul
if not errorlevel 1 exit /b 0
for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\Node.js" /v InstallPath 2^>nul ^| findstr InstallPath') do set "NODE_HOME=%%B"
if defined NODE_HOME if exist "!NODE_HOME!\node.exe" set "PATH=!NODE_HOME!;!PATH!"
if exist "E:\Dependencies\nodejs\node.exe" set "PATH=E:\Dependencies\nodejs;!PATH!"
exit /b 0

:runapp
echo [OK] Backend is ready.
if /I "%LAUNCH_MODE%"=="--release" (
    tasklist /FI "IMAGENAME eq asmr-helper.exe" /NH 2>nul | findstr /I /C:"asmr-helper.exe" >nul
    if not errorlevel 1 (
        echo [ERROR] Close the running ASMR Helper before rebuilding it.
        set "APP_EXIT=1"
        goto cleanup
    )
    echo [INFO] Building release application...
    pushd "%DESKTOP_DIR%"
    call npm.cmd run tauri -- build
    set "APP_EXIT=!ERRORLEVEL!"
    popd
    if not "!APP_EXIT!"=="0" goto app_failed
    echo [INFO] Launching release application...
    "%RELEASE_EXE%"
    set "APP_EXIT=!ERRORLEVEL!"
    goto cleanup
)

if /I "%LAUNCH_MODE%"=="--installed" (
    echo [INFO] Launching installed release application...
    "%RELEASE_EXE%"
    set "APP_EXIT=!ERRORLEVEL!"
    goto cleanup
)

echo [INFO] Starting Tauri development mode...
pushd "%DESKTOP_DIR%"
set "VITE_API_BASE=http://127.0.0.1:%BACKEND_PORT%/api/v1"
call npm.cmd run tauri -- dev
set "APP_EXIT=!ERRORLEVEL!"
popd
goto cleanup
