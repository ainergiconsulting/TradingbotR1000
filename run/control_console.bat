@echo off
setlocal

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "BOT_DIR=%PROJECT_ROOT%\current_reference\PaperTradingR1000"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%BOT_DIR%\manual_control_console.py" (
    echo ERROR: Control Console not found: "%BOT_DIR%" 1>&2
    pause
    exit /b 64
)

if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

cd /d "%PROJECT_ROOT%"
if errorlevel 1 (
    echo ERROR: Could not enter "%PROJECT_ROOT%" 1>&2
    pause
    exit /b 64
)

"%PYTHON_EXE%" -X utf8 -B -c "import sys; sys.path.insert(0, r'%BOT_DIR%'); import ibkr_utils"
if errorlevel 1 (
    echo ERROR: ib_insync is not installed in the approved project venv. 1>&2
    pause
    exit /b 66
)

"%PYTHON_EXE%" -X utf8 -B "%~dp0check_ibkr_api_port.py"
if errorlevel 1 (
    echo.
    echo ERROR: IBKR Gateway/TWS API is not accepting connections on the configured endpoint.
    echo Start or fix IB Gateway Paper API first, then run this launcher again.
    pause
    exit /b 70
)

"%PYTHON_EXE%" -X utf8 -u "%BOT_DIR%\manual_control_console.py"
set "CONSOLE_EXIT_CODE=%ERRORLEVEL%"

echo.
echo Control Console exited with code %CONSOLE_EXIT_CODE%.
pause
exit /b %CONSOLE_EXIT_CODE%
