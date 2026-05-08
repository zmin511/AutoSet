@echo off
set "PY=C:\Users\inasonov\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "SCRIPT=G:\zmin_autoset\tools\engine_set_builder.py"

if "%~1"=="" (
  echo Drag an analyzed audio file onto this command to build a 3-hour peak set.
  pause
  exit /b 1
)

"%PY%" -B "%SCRIPT%" "%~1" --role peak --minutes 180 --out-dir "G:\Music\Sets"
pause
