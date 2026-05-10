@echo off
set "PY=C:\Users\inasonov\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "SCRIPT=%~dp0engine_write_tags.py"
set "TARGET=%~1"

if "%TARGET%"=="" (
  "%PY%" -B "%SCRIPT%" --key-format camelot --write-bitrate-tag
) else (
  "%PY%" -B "%SCRIPT%" --key-format camelot --write-bitrate-tag "%TARGET%"
)
pause
