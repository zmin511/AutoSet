# zmin_autoset

Version: `1.5.2`

`zmin_autoset` is a local portable companion app for **Denon Engine DJ**.
It helps build a harmonic DJ set from a reference track, inspect tracks with
Engine-like waveform/cue/loop data, and create playlists directly inside the
Engine database without cloud services or external accounts.

## Purpose

The project is built for a practical DJ preparation workflow:

- pick a reference track;
- find compatible tracks by BPM, Camelot key, genre/style, and duration;
- estimate track energy from Engine waveform data;
- export a ready-to-play set folder or create an Engine playlist;
- save `playlist.m3u`, `playlist.csv`, and a short selection methodology.

## How It Works

Engine stores its library in SQLite:

```text
Engine Library/Database2/m.db
```

`zmin_autoset` reads `Track` and `PerformanceData`:

- `Track` - file path, artist/title/genre, BPM, key, length, bitrate, availability;
- `PerformanceData.overviewWaveFormData` - RGB overview waveform, similar to Engine;
- `PerformanceData.quickCues` - Cue 1..8 positions and labels;
- `PerformanceData.loops` - Loop 1..8 start/end positions and labels.

Set building is a transition-scoring process. The algorithm considers:

- BPM window around the reference track and maximum adjacent BPM step;
- Camelot wheel distance and A/B mode changes;
- genre families and selected style filters;
- estimated energy derived from `overviewWaveFormData`;
- track length, bitrate, and duplicate versions of the same song.

The reference track can play two roles:

- `Start` - the reference is the opener, then BPM/energy gradually rise;
- `Peak` - the reference is the peak point, with a buildup before it and release after it.

## Interface

The app runs a local Python server and opens a browser UI.

The UI includes:

- path setup for `Music/` and `Engine Library`/`m.db`;
- music-folder browser;
- Engine library search;
- track table with genre, Camelot, BPM, and duration;
- cue/loop presence indicators;
- built-in audio player;
- Engine-like waveform with cues on top and loops on bottom;
- role, duration, `Camelot +/-`, and `BPM +/-` controls;
- style filters;
- set creation with file copying;
- Engine DB playlist creation;
- tag/genre refresh for a selected folder.

## Main Tools

- `set_app/set_app.py` - local HTTP server, REST API, browser launch, UI integration.
- `set_app/index.html` - browser interface.
- `tools/engine_set_builder.py` - main set-building algorithm.
- `tools/engine_config.py` - shared path configuration.
- `tools/engine_write_tags.py` - writes Engine BPM/key/bitrate into ID3 tags.
- `tools/review_new_genres.py` - normalizes genres, families, DJ styles, and service tags.
- `tools/engine_db_playlist.py` - CLI helper for Engine DB reading and simple playlists.
- `tools/tag_from_musicbrainz.py` - optional MusicBrainz/iTunes tagger.

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

The UI usually opens at:

```text
http://127.0.0.1:8765/
```

## Outputs

**Create set**:

```text
Music/Sets/<set_name>/
  01 - ...
  02 - ...
  playlist.m3u
  playlist.csv
  methodology.txt
```

**Create playlist**:

- creates an Engine playlist using links to existing tracks;
- also writes local `m3u/csv` files for checking and previewing.

The `Event` field in the UI controls the target folder path inside Engine, for example:

```text
Event
Event/Afro house
```

## Notes

- Do not open `set_app/index.html` directly for real work; the local Python server is required.
- Before writing playlists into Engine, it is safer to close Engine DJ or make sure the database is not in use.
- `Set`/`Sets` folders are protected from automatic tag refresh.
- Denon Engine DJ is the current supported library provider; rekordbox/Traktor are only detected as future candidates.
