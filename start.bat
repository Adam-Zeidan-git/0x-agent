@echo off
REM One-click start for Windows: creates the environment on first run, then opens the 0x web interface.
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv (echo First run: installing, about a minute... & python -m venv .venv)
call .venv\Scripts\activate.bat
python -c "import autoclose_ui" 2>nul || pip install -q -e .
0x-ui --open %*
pause
