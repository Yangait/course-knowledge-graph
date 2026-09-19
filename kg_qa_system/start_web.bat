@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python virtual environment was not found: .venv
    echo Follow the installation steps in the project README first.
    pause
    exit /b 1
)

if not exist ".env" (
    echo Configuration file was not found: .env
    echo Copy .env.example to .env and fill in the required settings.
    pause
    exit /b 1
)

echo Open http://127.0.0.1:8000 in your browser.
".venv\Scripts\python.exe" -m uvicorn api:app --host 127.0.0.1 --port 8000

if errorlevel 1 (
    echo.
    echo The web application exited with an error. Review the message above.
)

pause

