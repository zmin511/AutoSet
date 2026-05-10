@echo off
set "PY=C:\Users\inasonov\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "SCRIPT=%~dp0engine_set_builder.py"

if "%~1"=="" (
  echo Drag an analyzed audio file onto this command to build a 3-hour opening set.
  pause
  exit /b 1
)

"%PY%" -B "%SCRIPT%" "%~1" --role start --minutes 180
pause
