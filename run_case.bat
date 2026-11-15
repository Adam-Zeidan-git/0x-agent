@echo off
REM Run 0x on a case folder (Windows).  usage: run_case.bat samples\mycase [extra flags]
cd /d "%~dp0"
set PYTHONUTF8=1
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
if "%~1"=="" (echo usage: run_case.bat ^<case_folder^> [extra flags] & exit /b 1)
set CASE=%~1
shift
0x --case "%CASE%" --full --no-nim --data "%CASE%\.out" %1 %2 %3 %4 %5 %6 %7 %8 %9
