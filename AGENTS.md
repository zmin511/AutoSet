# AGENTS.md - AutoSet

## Project Overview

AutoSet is a local portable companion app for Denon Engine DJ. It reads the Engine DJ SQLite database, shows tracks with waveform/cue/loop data, helps prepare harmonic DJ sets by BPM, Camelot key, genre/style, duration, and energy, creates local set folders and Engine playlists, and manages genre/tag metadata.

The core workflow is local-first. AutoSet should work from a portable folder without cloud accounts or hosted services.

## Main Code Layout

- set_app/set_app.py - local Python HTTP server, API endpoints, path configuration, Engine DB access, waveform/cue/loop handling, playlist and export logic.
- set_app/index.html - browser UI shell. Do not edit this blindly; prefer changing the split CSS/JS modules when possible.
- set_app/static/app-*.js - frontend modules for UI, playback, prep, rendering, storage, suggestions, and batch preview.
- set_app/static/app.css - frontend styling.
- tools/engine_set_builder.py - DJ set building/scoring algorithm.
- tools/engine_config.py - shared path configuration helpers.
- tools/engine_write_tags.py - tag writing through mutagen.
- tools/review_new_genres.py - genre/style normalization helpers.
- requirements.txt - runtime Python dependencies.
- requirements-dev.txt - development and CI dependencies.

## What Can Be Changed

- Python application code in set_app/ and tools/.
- Frontend modules in set_app/static/.
- Documentation, CI, tests, and small maintenance scripts.
- UI text/layout, if the requested behavior is preserved and checked in the browser.

Keep changes small and traceable. Prefer focused commits and a short explanation of what was verified.

## What Must Not Be Changed Or Committed

- Do not commit Engine DJ databases: *.db, *.sqlite, WAL/SHM files, or local Engine Library data.
- Do not commit music/audio files such as *.mp3, *.flac, *.wav, *.aiff, *.aif, *.m4a, *.ogg.
- Do not commit local path config such as set_app/paths.json or generated set_app/track_marks/ data.
- Do not commit portable runtimes such as python-windows/.
- Do not commit backup archives, generated backup folders, cache folders, or local Codex artifacts.
- Do not write to Engine DB or audio files during documentation/CI work.
- Do not move or reorganize the user music folders.

When touching Engine DB export or audio-tag code, keep backup behavior intact and document the risk clearly.

## Local Checks

Minimum syntax check:
python -m compileall set_app tools

If development dependencies are installed:
python -m ruff check set_app tools
python -m pytest

pytest may report that no tests were collected if the repository still has no test suite. In that case, document the absence of tests instead of inventing coverage.

## Branches And Pull Requests

- Work on a feature/chore branch, not directly on main.
- Keep main stable and merge only after review/checks.
- For Codex maintenance work, use descriptive branches such as chore/codex-agent-ci-setup.
- Do not merge your own setup branch into main unless the user explicitly asks.
- In PR notes, include changed files, checks run, skipped checks, and any known risk.

## Notes For Future Assistants

- The user treats F:/Music as a music library only. Project work belongs in F:/AutoSet.
- Make a backup in F:/AutoSet/backups before risky edits.
- Preserve the current playback behavior unless the user asks to change it: Play/Pause starts quickly, Cue starts from the beginning/cue point, and paused waveform seeking should stay fixed.
- Keep the Track Prep and batch preview UI stable unless the user explicitly requests layout changes.
