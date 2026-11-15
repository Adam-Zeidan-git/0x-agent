@echo off
setlocal
REM One-click start for Windows: creates the environment on first run, then opens the 0x web interface.
cd /d "%~dp0"
set PYTHONUTF8=1

REM Find Python: the "py" launcher first (installed by python.org), then "python".
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (python --version >nul 2>nul && set "PY=python")
if not defined PY goto nopython

if not exist ".venv\Scripts\python.exe" (
  echo First run: installing, this takes about a minute...
  %PY% -m venv .venv
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -c "import autoclose_ui" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -q -e .
  if errorlevel 1 goto fail
)
echo.
echo Starting 0x. If the browser does not open, go to http://127.0.0.1:8080
echo Close this window (or press Ctrl+C) to stop.
".venv\Scripts\python.exe" -m autoclose_ui --open %*
goto end

:nopython
echo Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run this again.
goto end

:fail
echo.
echo Something went wrong during setup. Copy the message above and send it to the developer.

:end
pause
