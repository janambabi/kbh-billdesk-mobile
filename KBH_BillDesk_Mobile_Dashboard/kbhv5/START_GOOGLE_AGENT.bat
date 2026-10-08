@echo off
title KBH BillDesk Google Auto Agent V5
cd /d "%~dp0"
echo ============================================================
echo KBH BILLDESK GOOGLE SHEET AUTO AGENT V5
echo ============================================================
echo.
echo Installing/checking required packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Package installation failed.
  pause
  exit /b 1
)
echo.
echo Starting agent...
echo.
python billdesk_google_agent.py
echo.
echo ============================================================
echo Agent stopped.
echo ============================================================
pause
