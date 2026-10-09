@echo off
setlocal
"%~dp0.venv\Scripts\python.exe" -B "%~dp0scripts\desktop_local.py" %*
set "APP_EXIT=%errorlevel%"
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%
