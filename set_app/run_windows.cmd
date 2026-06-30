@echo off
setlocal
cd /d "%~dp0"

set "APP_PY=%~dp0set_app.py"
set "REQ_FILE=%~dp0..\requirements.txt"
set "LOCAL_PY=%~dp0..\python-windows\python.exe"

if exist "%LOCAL_PY%" goto use_local_python
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto use_py_launcher
python -c "import sys" >nul 2>nul
if not errorlevel 1 goto use_python_path

echo Python 3 was not found. Install Python 3 or copy portable Python to python-windows.
exit /b 1

:use_local_python
call :ensure_requirements "%LOCAL_PY%"
if errorlevel 1 exit /b %errorlevel%
"%LOCAL_PY%" "%APP_PY%"
exit /b %errorlevel%

:use_py_launcher
call :ensure_requirements py -3
if errorlevel 1 exit /b %errorlevel%
py -3 "%APP_PY%"
exit /b %errorlevel%

:use_python_path
call :ensure_requirements python
if errorlevel 1 exit /b %errorlevel%
python "%APP_PY%"
exit /b %errorlevel%

:ensure_requirements
%* -c "import mutagen" >nul 2>nul
if not errorlevel 1 exit /b 0

if not exist "%REQ_FILE%" (
  echo AutoSet requirements file was not found: "%REQ_FILE%"
  exit /b 1
)

echo Installing AutoSet Python requirements...
%* -m pip install -r "%REQ_FILE%"
if errorlevel 1 (
  echo Failed to install AutoSet Python requirements.
  exit /b %errorlevel%
)
%* -c "import mutagen" >nul 2>nul
if errorlevel 1 (
  echo AutoSet requirements were installed, but mutagen is still unavailable.
  exit /b 1
)
exit /b 0
