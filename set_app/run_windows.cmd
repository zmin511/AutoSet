@echo off
setlocal
cd /d "%~dp0"

set "LOCAL_PY=%~dp0..\python-windows\python.exe"
if exist "%LOCAL_PY%" (
  "%LOCAL_PY%" "%~dp0set_app.py"
  exit /b %errorlevel%
)

py -3 "%~dp0set_app.py"
if %errorlevel%==0 exit /b 0

python "%~dp0set_app.py"
