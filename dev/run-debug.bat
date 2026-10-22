@echo off
rem Runs from source with a console, debug logging and the window open.
set "UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\GestureRotary\venv"
cd /d "%~dp0.."
"%UV_PROJECT_ENVIRONMENT%\Scripts\python.exe" -m rotary --show --debug %*
