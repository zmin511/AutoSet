@echo off
set "PY=C:\Users\inasonov\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "SCRIPT=G:\zmin_autoset\tools\review_new_genres.py"
set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=G:\Music\New"

"%PY%" -B "%SCRIPT%" "%TARGET%" --db-path "G:\Engine Library\Database2\m.db" --music-root "G:\Music" --report-dir "G:\zmin_autoset\reports\genres" --backup-dir "G:\zmin_autoset\tag_backups" --apply --no-backup --min-confidence medium
pause
