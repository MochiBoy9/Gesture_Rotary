@echo off
rem Developer setup: installs Python + dependencies into a short path (avoids Windows' 260-char limit).
set "UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\GestureRotary\venv"
cd /d "%~dp0.."
where uv >nul 2>nul || (
  echo Installing uv...
  powershell -NoProfile -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
uv sync --frozen || uv sync
echo.
echo Setup complete. Run dev\run-debug.bat, or build the app with build_exe.bat.
pause
