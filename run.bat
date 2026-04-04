@echo off
chcp 65001 >nul
title ASMR Helper

set PROJECT_ROOT=%~dp0
set VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe

cd /d "%PROJECT_ROOT%"

if "%~1"=="" goto gui
if /i "%~1"=="gui" goto gui
if /i "%~1"=="single" goto single
if /i "%~1"=="batch" goto batch
if /i "%~1"=="test" goto test
goto usage

:gui
echo.
echo ========================================
echo   ASMR Helper - GUI Mode
echo ========================================
"%VENV_PYTHON%" -m src.gui
goto end

:single
if "%~2"=="" (
    powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $dialog = New-Object System.Windows.Forms.OpenFileDialog; $dialog.Filter = 'Audio files|*.wav;*.mp3;*.m4a;*.flac|All files|*.*'; $dialog.Title = 'Select audio file'; if ($dialog.ShowDialog() -eq 'OK') { Write-Output $dialog.FileName }"
    set /p INPUT_FILE=
    if "%INPUT_FILE%"=="" goto end
    echo Processing: %INPUT_FILE%
    "%VENV_PYTHON%" scripts/asmr_bilingual.py --input "%INPUT_FILE%"
) else (
    echo Processing: %~2
    "%VENV_PYTHON%" scripts/asmr_bilingual.py --input "%~2"
)
goto end

:batch
if "%~2"=="" (
    powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $dialog = New-Object System.Windows.Forms.FolderBrowserDialog; $dialog.Description = 'Select audio folder'; if ($dialog.ShowDialog() -eq 'OK') { Write-Output $dialog.SelectedPath }"
    set /p INPUT_DIR=
    if "%INPUT_DIR%"=="" goto end
    echo Batch folder: %INPUT_DIR%
    "%VENV_PYTHON%" scripts/batch_process.py --input-dir "%INPUT_DIR%"
) else (
    echo Batch folder: %~2
    "%VENV_PYTHON%" scripts/batch_process.py --input-dir "%~2"
)
goto end

:test
echo.
echo ========================================
echo   ASMR Helper - Environment Test
echo ========================================
echo.
echo [1] Python version:
"%VENV_PYTHON%" --version
echo.
echo [2] Core modules:
"%VENV_PYTHON%" -c "import demucs; print('  - Demucs:', demucs.__version__)"
"%VENV_PYTHON%" -c "import faster_whisper; print('  - Faster-Whisper: OK')"
echo.
echo Environment test complete!
goto end

:usage
echo.
echo ASMR Helper Launcher
echo.
echo Usage:
echo   run.bat              - Launch GUI
echo   run.bat gui          - Launch GUI
echo   run.bat single       - Single file (with dialog)
echo   run.bat single file  - Single file processing
echo   run.bat batch        - Batch processing (with dialog)
echo   run.bat batch folder - Batch processing
echo   run.bat test         - Test environment
echo.

:end
pause
