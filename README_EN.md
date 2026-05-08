# zmin_autoset

`zmin_autoset` is a portable local app for building DJ sets from an Engine DJ library.

Version: `0.2.0`

The app reads the Engine DJ database, shows your music in a browser, lets you choose a reference track, and builds a harmonic set using BPM, Camelot/key, genre, bitrate, and track length. The finished set is copied into a dedicated output folder with `playlist.m3u` and `playlist.csv`.

Current working provider: Denon Engine DJ.

The app now includes a discovery layer for multiple DJ libraries. It can detect likely rekordbox and Traktor library files, but it fully parses and uses only Denon Engine DJ today. Pioneer rekordbox and Native Instruments Traktor need separate adapters because their files, schemas, and key/BPM/path fields are different.

## How It Works

Engine DJ stores the main track metadata in this SQLite database:

```text
Engine Library/Database2/m.db
```

`zmin_autoset` reads:

- file path;
- artist/title/filename;
- BPM;
- Engine key, converted to Camelot;
- genre;
- bitrate;
- length;
- track availability.

## Other DJ Libraries

Current supported setup:

```text
Provider: Denon Engine DJ
Database: Engine Library/Database2/m.db
Status: supported
```

The app also checks common locations for other libraries:

- Pioneer rekordbox: USB/export candidates such as `PIONEER/rekordbox/export.pdb`, plus local `master.db` candidates;
- Native Instruments Traktor: `collection.nml` files in Traktor folders.

If those files are found, the app can report them as `detected_not_supported`. That means the library was detected, but sets cannot be built from it directly yet.

Why another database cannot simply be swapped in:

- each product uses different table and field names;
- Traktor often stores the collection as XML/NML rather than SQLite;
- rekordbox may use different local and USB/export formats;
- key/Camelot, path, availability, rating, and analysis values are stored differently.

The right long-term design is an adapter layer:

```text
Denon Engine DB  -> common Track model -> zmin_autoset algorithm
rekordbox DB/PDB -> common Track model -> zmin_autoset algorithm
Traktor NML      -> common Track model -> zmin_autoset algorithm
```

This layer has been started: the UI and API now know which provider is active and can show detected library candidates. The next step is to implement dedicated rekordbox and Traktor parser/adapters.

The actual audio files are touched only when the app needs to:

- play a browser preview;
- refresh file tags;
- copy selected tracks into a generated set.

## Where To Put The Folder

Recommended drive layout:

```text
G:/
  zmin_autoset/
  Music/
  Engine Library/
    Database2/
      m.db
```

Important: `zmin_autoset`, `Music`, and `Engine Library` must be siblings at the same drive/folder level. The app calculates the drive root from its own location and expects this structure.

The drive name can be different. On another Windows drive or on macOS, keep the same relative layout:

```text
<drive root>/
  zmin_autoset/
  Music/
  Engine Library/
```

## How To Copy It To Another Computer

Copy these folders to the target SSD or external drive:

```text
zmin_autoset/
Music/
Engine Library/
```

After copying, open Engine DJ and make sure it can see and analyze the tracks. If Engine DJ updates paths or analysis data, wait for it to finish before using `zmin_autoset`.

## Run On Windows

Recommended launcher:

```cmd
zmin_autoset\run_windows.cmd
```

You can also run the internal launcher:

```cmd
zmin_autoset\set_app\run_windows.cmd
```

The script tries:

1. local Python at `zmin_autoset\python-windows\python.exe`, if you bundled one;
2. system `py -3`;
3. system `python`.

The browser opens at:

```text
http://127.0.0.1:8765/
```

## Run On macOS

In Terminal, make the launchers executable once:

```sh
chmod +x /Volumes/<SSD_NAME>/zmin_autoset/run_mac.command
chmod +x /Volumes/<SSD_NAME>/zmin_autoset/set_app/run_mac.command
```

Then run:

```sh
/Volumes/<SSD_NAME>/zmin_autoset/run_mac.command
```

or double-click `run_mac.command`.

Python 3.11+ is required. If `python3` is not available, install Python from https://www.python.org/downloads/macos/.

## Can I Open The HTML File Directly?

Only for layout preview. Real set creation requires the local Python server.

Reasons:

- the browser cannot read the Engine SQLite database by itself;
- the browser cannot safely copy audio files into `Music/Sets`;
- the set builder runs as a local Python process.

Always start the app with:

```text
run_windows.cmd
run_mac.command
```

## Main Folders

`set_app/`

Local web app:

- `index.html` - browser interface;
- `set_app.py` - local HTTP server;
- `run_windows.cmd` - Windows launcher;
- `run_mac.command` - macOS launcher.

`tools/`

Engine DJ and file utilities:

- `engine_set_builder.py` - main set generator;
- `engine_db_playlist.py` - Engine DB reader and simple playlist helper;
- `engine_write_tags.py` - writes BPM/key/bitrate from Engine into file tags;
- `review_new_genres.py` - reviews and classifies new tracks by genre/style/family;
- `tag_from_musicbrainz.py` - optional genre enrichment via MusicBrainz/iTunes;
- `make_start_set*.cmd` and `make_peak_set*.cmd` - quick set-generation launchers;
- `refresh_tags_*.cmd` - tag refresh launchers;
- `review_new_genres_*.cmd` - genre review/apply launchers.

`reports/`

CSV reports from tag and genre refresh runs. This folder is not committed to git.

`tag_backups/`

Backup copies of audio files before tag writes. This folder is not committed to git.

`Music/Sets/`

Generated sets are written here. This folder lives next to `zmin_autoset`, inside your music library.

## Typical Workflow

1. Put new tracks into `Music/New` or another folder inside `Music`.
2. Import and analyze the tracks in Engine DJ.
3. Start `zmin_autoset`.
4. Browse a folder or search for a track.
5. Select a reference track.
6. Choose whether it should be the opener or the peak track.
7. Set duration, Camelot step, and BPM window.
8. Click “Create set”.
9. Take the result from `Music/Sets/...`.

## Output

Each set gets its own folder:

```text
Music/Sets/<timestamp>_<role>_<track-name>/
  01 - Track Name (124BPM-8A).mp3
  02 - Track Name (125BPM-9A).mp3
  playlist.m3u
  playlist.csv
```

The copied filename includes BPM and Camelot key in parentheses. This is intentional, so you can quickly inspect whether tempo and harmonic movement look correct.

`playlist.m3u` can be opened in a player.

`playlist.csv` is useful as a table: order, artist, title, length, BPM, Camelot, genre, bitrate, and source path.

## Library Maintenance

The UI includes a tag-refresh action for the current folder. It runs tools scripts and can write these values into audio files:

- BPM;
- key/Camelot;
- helper bitrate tag;
- genre decisions, depending on the workflow used.

Keep backups when doing bulk tag writes. The app uses `tag_backups/` for that.

## What Should Not Be Committed

The repository should contain code and documentation only.

Do not commit:

- `reports/`;
- `tag_backups/`;
- `__pycache__/`;
- local `.db` and `.sqlite` files;
- `Music/`;
- `Engine Library/`;
- large bundled portable Python runtimes.

This is already covered by `.gitignore`.

## Minimum Requirements

- Python 3.11+.
- Engine DJ library with `Engine Library/Database2/m.db`.
- Music folder named `Music`.
- A modern browser.

No internet is required after Python is installed, except when you explicitly use `tag_from_musicbrainz.py`.
