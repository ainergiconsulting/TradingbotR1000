@echo off
setlocal
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "BOT_DIR=%PROJECT_ROOT%\current_reference\PaperTradingR1000"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
cd /d "%PROJECT_ROOT%"

"%PYTHON_EXE%" -X utf8 -B "%PROJECT_ROOT%\run\stop_runtime.py"
exit /b %ERRORLEVEL%
