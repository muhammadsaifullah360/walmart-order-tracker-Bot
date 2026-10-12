@echo off
REM Double-click this to open the Walmart Bot window (no terminal needed).
cd /d "%~dp0"
where python >nul 2>nul && (python gui.py) || ("%LOCALAPPDATA%\Programs\Python\Python312\python.exe" gui.py)
