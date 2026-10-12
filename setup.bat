@echo off
REM ============================================================
REM  One-time setup for the Walmart Order Tracker.
REM  Double-click this ONCE on a new PC. Then use run.bat.
REM ============================================================
cd /d "%~dp0"
echo.
echo ===== Walmart Order Tracker - setup =====
echo.

REM --- find Python ---
set "PYEXE="
where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

if not defined PYEXE (
  echo Python is not installed.
  echo.
  echo Please install Python 3.10 or newer from:
  echo     https://www.python.org/downloads/
  echo IMPORTANT: on the first screen, TICK "Add python.exe to PATH".
  echo.
  echo After installing, run this setup.bat again.
  echo.
  pause
  exit /b
)

echo Using Python: %PYEXE%
echo.
echo Installing the required libraries (this can take a minute)...
"%PYEXE%" -m pip install --upgrade pip
"%PYEXE%" -m pip install -r requirements.txt

echo.
echo ===== Setup complete! =====
echo.
echo Make sure "service_account.json" is in this folder,
echo then double-click  run.bat  to open the app.
echo.
echo (The web browser it uses downloads itself the first time you press Start.)
echo.
pause
