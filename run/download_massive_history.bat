@echo off
setlocal
cd /d "%~dp0\.."

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" current_reference\PaperTradingR1000\massive_historical_downloader.py --full %*
exit /b %ERRORLEVEL%
