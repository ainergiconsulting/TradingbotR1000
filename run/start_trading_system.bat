@echo off
setlocal
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "TRADINGBOTR1000_ENABLE_AUTOMATED_PAPER_EXECUTION=1"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
cd /d "%PROJECT_ROOT%"

"%PYTHON_EXE%" -X utf8 -B "%PROJECT_ROOT%\run\start_detached_controller.py"
exit /b %errorlevel%
