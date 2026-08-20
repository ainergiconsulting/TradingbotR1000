@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "BOT_DIR=%PROJECT_ROOT%\current_reference\PaperTradingR1000"
cd /d "%BOT_DIR%"
python config_editor.py
