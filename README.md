# zmin_autoset

Version: `1.5.2` | Changelog: `CHANGELOG.md`

`zmin_autoset` is a local portable companion app for **Denon Engine DJ**.
It helps build harmonic DJ sets from a reference track, inspect tracks through
Engine-like waveform/cue/loop data, and create playlists directly inside the
Engine database. The app works offline: no cloud, no account, no external service
is required for the main workflow.

Русская документация: `README_RU.md`

English documentation: `README_EN.md`

## What It Does

- Builds a DJ set around a selected reference track.
- Scores transitions by BPM, Camelot key, genre/style, duration, bitrate, and waveform-derived energy.
- Supports two reference roles: opener (`Start`) or peak point (`Peak`).
- Shows a browser UI with search, folder browsing, player, waveform, cue, and loop markers.
- Exports a copied set folder with `playlist.m3u`, `playlist.csv`, and `methodology.txt`.
- Can create an Engine DB playlist with links to existing tracks, without copying files.
- Includes maintenance tools for writing Engine metadata back into audio tags and reviewing genres/styles.

## How It Works

The main data source is the Denon Engine SQLite database:

```text
Engine Library/Database2/m.db
```

The app reads:

- `Track` - file path, artist/title/genre, BPM, key, length, bitrate, availability;
- `PerformanceData.overviewWaveFormData` - RGB overview waveform;
- `PerformanceData.quickCues` - Cue 1..8 positions and labels;
- `PerformanceData.loops` - Loop 1..8 start/end positions and labels.

The set builder filters and scores candidates using:

- `BPM +/-` window around the reference track;
- maximum adjacent BPM step;
- `Camelot +/-` wheel distance;
- genre families and selected style filters;
- estimated energy from Engine waveform data;
- duplicate/version pressure to avoid crowding the set with near-identical tracks.

## Interface

The app runs as a local Python HTTP server and opens a browser UI, usually at:

```text
http://127.0.0.1:8765/
```

Main UI areas:

- path setup for `Music/` and `Engine Library`/`m.db`;
- music-folder browser and Engine library search;
- track table with genre, Camelot, BPM, duration, cue/loop indicators;
- audio player with waveform scrubbing;
- Engine-like waveform rendering with cues on top and loops on bottom;
- set controls: role, duration, Camelot range, BPM range, style filters;
- actions: create copied set, create Engine playlist, refresh tags.

## Project Structure

```text
zmin_autoset/
  run_windows.cmd
  run_mac.command
  set_app/
    set_app.py        # local server, REST API, Engine DB integration
    index.html        # browser UI
  tools/
    engine_set_builder.py   # main harmonic set builder
    engine_config.py        # shared path configuration
    engine_write_tags.py    # write BPM/key/bitrate tags from Engine data
    review_new_genres.py    # genre/style normalization helper
    engine_db_playlist.py   # CLI helper for Engine DB scans/playlists
    tag_from_musicbrainz.py # optional MusicBrainz/iTunes tagger
  reports/
  tag_backups/
```

## Quick Start

Recommended drive layout:

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

Do not open `set_app/index.html` directly for real work; the local Python server is required.

## Outputs

**Create set** writes a copied set folder:

```text
Music/Sets/<set_name>/
  01 - ...
  02 - ...
  playlist.m3u
  playlist.csv
  methodology.txt
```

**Create playlist** writes a playlist into the Engine DB using links to existing
tracks and also exports local `m3u/csv` files for checking. The `Event` field in
the UI controls the target Engine folder path, for example `Event` or
`Event/Afro house`.
