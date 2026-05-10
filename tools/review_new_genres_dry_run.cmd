@echo off
set "PY=C:\Users\inasonov\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "SCRIPT=%~dp0review_new_genres.py"
set "TARGET=%~1"

if "%TARGET%"=="" (
  "%PY%" -B "%SCRIPT%"
) else (
  "%PY%" -B "%SCRIPT%" "%TARGET%"
)
pause
