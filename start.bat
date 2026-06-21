@echo off
REM NetGraphX — Windows startup script
REM Starts both the Flask webhook server and the Streamlit dashboard.

title NetGraphX Launcher

echo.
echo ==================================================
echo   NetGraphX - Starting Services
echo ==================================================
echo.

REM Activate venv if present
IF EXIST ".venv\Scripts\activate.bat" (
    echo [1] Activating virtual environment...
    call .venv\Scripts\activate.bat
) ELSE (
    echo [1] No .venv found — using system Python.
)

REM Verify .env exists
IF NOT EXIST ".env" (
    echo [WARN] .env file not found. Copying from .env.example...
    copy .env.example .env
    echo       Please edit .env with your real credentials before continuing.
    pause
)

echo.
echo [2] Starting Flask webhook server (port %WEBHOOK_PORT% or 5001)...
start "NetGraphX Webhook Server" cmd /k "python -m src.webhook.server"

REM Small delay to let Flask start first
timeout /t 2 /nobreak >nul

echo.
echo [3] Starting Streamlit dashboard (port 8501)...
start "NetGraphX Dashboard" cmd /k "streamlit run app.py --server.port 8501"

echo.
echo ==================================================
echo   Services started:
echo     Webhook:   http://localhost:5001
echo     Dashboard: http://localhost:8501
echo ==================================================
echo.
echo Press any key to close this launcher window...
pause >nul
