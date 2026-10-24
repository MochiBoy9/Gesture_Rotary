@echo off
rem Builds "Gesture Rotary.exe" and installs it for the current user:
rem   %USERPROFILE%\Apps\Gesture Rotary\Gesture Rotary.exe  (+ a Desktop shortcut; the app adds its Start menu entry)
rem Settings live in %APPDATA%\GestureRotary\config.json
setlocal
set "UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\GestureRotary\venv"
set "OUT=%LOCALAPPDATA%\GestureRotary\dist"
set "WORK=%LOCALAPPDATA%\GestureRotary\build"
cd /d "%~dp0"
uv sync || exit /b 1
uv run python tools\make_icon.py || exit /b 1
uv run pyinstaller --noconfirm --clean --distpath "%OUT%" --workpath "%WORK%" "Gesture Rotary.spec" || exit /b 1
uv run python tools\install.py "%OUT%\Gesture Rotary" || exit /b 1
echo.
echo Done. Start "RotaryUI" from your Desktop or the Start menu.
