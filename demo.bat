@echo off
REM Full review of the Piazza 1140 sample case (Windows)
cd /d "%~dp0"
set PYTHONUTF8=1
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
0x --case samples\piazza1140 --full --no-nim --data samples\piazza1140\.out %*
