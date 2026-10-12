@echo off
REM ---------------------------------------------------------------------------
REM Build a double-clickable WalmartBot.exe from gui.py using PyInstaller.
REM
REM The Chromium browser is NOT inside the exe (it can't be), BUT the exe will
REM DOWNLOAD it automatically the first time it runs if it's missing. So on a
REM fresh PC the user just double-clicks the exe -> it fetches the browser once
REM (~150 MB) -> then runs. No manual "playwright install" needed.
REM
REM config.py is bundled INTO the exe, so edit config.py and rebuild if you
REM change saved defaults. (The GUI fields still let you override per run.)
REM ---------------------------------------------------------------------------

echo Installing PyInstaller...
pip install pyinstaller

echo Building WalmartBot.exe ...
REM --onedir + the Chromium browser bundled in, so it runs with NO download.
REM Result is a FOLDER (dist\WalmartBot) you zip and share.
pyinstaller --noconfirm --onedir --windowed ^
  --name WalmartBot ^
  --icon icon.ico ^
  --add-data "config.py;." ^
  --add-data "icon.ico;." ^
  --add-data "icon.png;." ^
  --add-data "%LOCALAPPDATA%\ms-playwright;ms-playwright" ^
  --collect-all playwright ^
  gui.py

echo.
echo Done. Your app folder is:  dist\WalmartBot\
echo Put service_account.json inside it, then zip the whole folder to share.
echo On the other PC: unzip, open the folder, double-click WalmartBot.exe.
pause
