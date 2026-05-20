# zmin_autoset

Version: `1.5.2`

`zmin_autoset` is a local (browser UI) companion app for **Denon Engine DJ**:

- build a harmonic DJ set from a reference track;
- create Engine playlists (links only, no file copying);
- visually verify tracks using an Engine-like waveform with cue/loop markers.

## How it works

Engine stores its library in SQLite:

```text
Engine Library/Database2/m.db
```

`zmin_autoset` reads `Track` + `PerformanceData`:
- `overviewWaveFormData` — RGB overview waveform (Engine-like);
- `quickCues` — Cue 1..8 labels and positions;
- `loops` — Loop 1..8 (start/end + label).

## Features

**1) Track browser**
- browse `Music/` folders and search through the Engine library;
- table view with BPM, Camelot, duration;
- cue/loop presence indicators per track.

**2) Player + waveform**
- play/pause, volume;
- mouse scrubbing on the waveform;
- cues (top) and loops (bottom) with labels and timestamps.

**3) Set / playlist creation**
- set building by BPM/Camelot/genre/duration;
- track “energy” is derived from `overviewWaveFormData` and used in transition scoring;
- create an Engine DB playlist and also export local `playlist.m3u` / `playlist.csv`.

## Quick start

Recommended layout:

```text
<drive root>/
  zmin_autoset/
  Music/
  Engine Library/
    Database2/
      m.db
```

Run:
- Windows: `zmin_autoset\run_windows.cmd`
- macOS: `zmin_autoset/run_mac.command`

Open UI (typically):

```text
http://127.0.0.1:8765/
```

Outputs go to `Music/Sets` (one folder per run).

