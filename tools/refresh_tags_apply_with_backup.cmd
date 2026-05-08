@echo off
set "PY=C:\Users\inasonov\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "SCRIPT=G:\zmin_autoset\tools\engine_write_tags.py"
set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=G:\Music"

"%PY%" -B "%SCRIPT%" --db-path "G:\Engine Library\Database2\m.db" --music-root "G:\Music" --report-dir "G:\zmin_autoset\reports" --backup-dir "G:\zmin_autoset\tag_backups" --key-format camelot --write-bitrate-tag --apply --backup-files "%TARGET%"
pause
