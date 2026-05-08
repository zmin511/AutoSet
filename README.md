# zmin_autoset

Portable local web app for building harmonic DJ sets from an Engine DJ library.

Version: 0.1.0

## Layout

- `set_app/` - local web UI and Python server.
- `tools/` - Engine DB utilities and set-generation scripts.
- `install/` - portable setup notes.

Generated reports, tag backups, Python caches, and local Engine/music databases are intentionally ignored.

## Run

Windows:

```cmd
zmin_autoset\set_app\run_windows.cmd
```

The app starts a local server at `http://127.0.0.1:8765/`.
