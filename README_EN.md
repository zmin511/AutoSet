# zmin_autoset

Version: `1.5.3`

`zmin_autoset` is a local portable companion app for **Denon Engine DJ**. It
helps build a harmonic DJ set from a selected reference track, inspect tracks
with waveform/cue/loop data, and create playlists directly inside the Engine
database without cloud services, accounts, or external services.

## Purpose

The project supports a practical DJ preparation workflow:

- pick a reference track;
- find musically compatible tracks;
- arrange the set by BPM, Camelot key, genre/style, and energy;
- export a ready-to-play set folder or create an Engine DJ playlist.

## How It Works

The main data source is the Engine SQLite database:

```text
Engine Library/Database2/m.db
```

The app reads:

- `Track` - file path, artist/title/genre, BPM, key, length, bitrate;
- `PerformanceData.overviewWaveFormData` - RGB overview waveform;
- `PerformanceData.quickCues` - Cue 1..8 positions and labels;
- `PerformanceData.loops` - Loop 1..8 start/end positions and labels.

The builder scores adjacent transitions by:

- BPM delta;
- Camelot number distance: `+/-3` from `5A/5B` allows 5, 6, 7, 8 and 4, 3, 2; A/B does not increase distance;
- genre and selected style similarity;
- estimated waveform energy;
- track length and bitrate;
- near-duplicate versions of the same song.

## Interface

The UI opens in a browser through a local Python server. It includes:

- path setup for `Music/` and `Engine Library`/`m.db`;
- music-folder browser;
- Engine library search;
- track table with genre, energy stars, Camelot, BPM, and duration;
- cue and loop indicators;
- built-in audio player;
- waveform with cues on top and loops on bottom;
- role, duration, `Camelot +/-`, and `BPM +/-` controls;
- style filter;
- create set and create playlist actions;
- tag refresh for the selected folder;
- writing estimated waveform energy into Engine DJ `Track.rating` stars for the current folder or the whole `Music` library.

## Output Modes

**Create set** copies tracks into a separate folder:

```text
Music/Sets/<set_name>/
  01 - ...
  02 - ...
  playlist.m3u
  playlist.csv
  methodology.txt
```

**Create playlist** creates an Engine DB playlist using links to existing
tracks. Local `m3u/csv` files are also saved for checking.

The `Event` field controls the target folder inside Engine, for example:

```text
Event
Event/Afro house
```

## Main Files

- `set_app/set_app.py` - local server, API, and Engine DB integration.
- `set_app/index.html` - browser interface.
- `tools/engine_set_builder.py` - set-building algorithm.
- `tools/engine_config.py` - shared path configuration.
- `tools/engine_write_tags.py` - writes Engine BPM/key/bitrate into ID3 tags.
- `tools/review_new_genres.py` - normalizes genres, families, and DJ tags.

## Quick Start

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

The UI usually opens at:

```text
http://127.0.0.1:8765/
```

Do not open `set_app/index.html` directly; the local Python server is required.
