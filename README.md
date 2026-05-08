# zmin_autoset

Portable local app for building harmonic DJ sets from an Engine DJ library.

Version: `0.1.3`

- [Русское описание](README_RU.md)
- [English documentation](README_EN.md)

## Quick Start

Place the folder next to your Engine DJ library and music folder:

```text
<SSD or drive root>/
  zmin_autoset/
  Music/
  Engine Library/
    Database2/
      m.db
```

Run:

- Windows: `zmin_autoset\run_windows.cmd`
- macOS: `zmin_autoset/run_mac.command`

The app opens a local browser UI at:

```text
http://127.0.0.1:8765/
```

The HTML page is served by a small local Python server. Opening `index.html`
directly is not enough for set creation, because the browser needs the server
to read the Engine database and copy audio files.

Generated reports, tag backups, Python caches, and local Engine/music databases
are intentionally ignored by git.
