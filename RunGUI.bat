@echo off
setlocal

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

echo [AsmrHelper] Preparing desktop development GUI...

if not exist "%ROOT_DIR%desktop\package.json" (
  echo [ERROR] desktop\package.json not found.
  exit /b 1
)

if not exist "%ROOT_DIR%.venv\Scripts\python.exe" (
  echo [ERROR] Python virtual environment not found: .venv\Scripts\python.exe
  echo         Please create the project venv before launching the desktop app.
  exit /b 1
)

if not exist "%ROOT_DIR%desktop\node_modules" (
  echo [ERROR] desktop\node_modules not found.
  echo         Run "cd desktop && npm install" first.
  exit /b 1
)

set "ASMR_PROJECT_DIR=%ROOT_DIR%"

echo [AsmrHelper] Project root: %ASMR_PROJECT_DIR%
echo [AsmrHelper] Launching Tauri desktop dev app...

cd /d "%ROOT_DIR%desktop"
call npm run tauri dev
set "EXIT_CODE=%ERRORLEVEL%"

cd /d "%ROOT_DIR%"
exit /b %EXIT_CODE%
