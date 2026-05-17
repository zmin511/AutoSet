import json
import mimetypes
import os
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qs, urlparse


APP_DIR = Path(__file__).resolve().parent
SSD_ROOT = APP_DIR.parent.parent
TOOLS_DIR = SSD_ROOT / "zmin_autoset" / "tools"
BUILDER = TOOLS_DIR / "engine_set_builder.py"
CONFIG_PATH = APP_DIR / "paths.json"
DEFAULT_MUSIC_ROOT = SSD_ROOT / "Music" if (SSD_ROOT / "Music").exists() else SSD_ROOT
DEFAULT_SETS_DIR = DEFAULT_MUSIC_ROOT / "Sets"
DEFAULT_DB_PATH = SSD_ROOT / "Engine Library" / "Database2" / "m.db"
MUSIC_ROOT = DEFAULT_MUSIC_ROOT
SETS_DIR = DEFAULT_SETS_DIR
DB_PATH = DEFAULT_DB_PATH
INDEX_HTML = APP_DIR / "index.html"
AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".aiff", ".aif"}
APP_NAME = "zmin_autoset"
APP_VERSION = "0.4.6"
APP_REPOSITORY_URL = "https://github.com/zmin511/zmin_autoset"
ACTIVE_LIBRARY_PROVIDER = "denon_engine"
APP_STATE = {"startup_refresh": "waiting"}


def _path_text(value):
    return str(value or "").strip().strip('"')


def _find_engine_db(path):
    root = Path(_path_text(path))
    if root.is_file() and root.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        return root
    candidates = [
        root / "Database2" / "m.db",
        root / "Database" / "m.db",
        root / "Engine Library" / "Database2" / "m.db",
        root / "Engine" / "Database2" / "m.db",
        root / "m.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    try:
        matches = sorted(root.glob("**/m.db"))
    except OSError:
        matches = []
    return matches[0] if matches else root


def _default_config():
    music_root = DEFAULT_MUSIC_ROOT
    db_path = SSD_ROOT / "Engine Library" / "Database2" / "m.db"
    for candidate in (
        SSD_ROOT / "Engine Library" / "Database2" / "m.db",
        SSD_ROOT / "Engine" / "Database2" / "m.db",
        SSD_ROOT / "Engine Library" / "Database" / "m.db",
        SSD_ROOT / "Engine" / "Database" / "m.db",
        music_root / "Engine Library" / "Database2" / "m.db",
        music_root / "Engine" / "Database2" / "m.db",
    ):
        if candidate.exists():
            db_path = candidate
            break
    return {
        "music_root": str(music_root),
        "db_path": str(db_path),
        "sets_dir": str(music_root / "Sets"),
    }


def load_path_config():
    config = _default_config()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in config:
                    value = _path_text(data.get(key))
                    if value:
                        config[key] = value
        except Exception:
            pass
    return config


def apply_path_config(config):
    global MUSIC_ROOT, SETS_DIR, DB_PATH
    MUSIC_ROOT = Path(config["music_root"])
    DB_PATH = Path(config["db_path"])
    SETS_DIR = Path(config.get("sets_dir") or (MUSIC_ROOT / "Sets"))


def save_path_config(data):
    config = load_path_config()
    music_root = _path_text(data.get("music_root"))
    db_path = _path_text(data.get("db_path"))
    sets_dir = _path_text(data.get("sets_dir"))
    if music_root:
        config["music_root"] = str(Path(music_root))
    if db_path:
        config["db_path"] = str(_find_engine_db(db_path))
    if sets_dir:
        config["sets_dir"] = str(Path(sets_dir))
    elif music_root:
        config["sets_dir"] = str(Path(music_root) / "Sets")
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    apply_path_config(config)
    return config


apply_path_config(load_path_config())


def _safe_disk_path(value):
    text = _path_text(value)
    candidate = Path(text) if text else SSD_ROOT
    if not candidate.is_absolute():
        candidate = SSD_ROOT / candidate
    candidate = candidate.resolve()
    root = SSD_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path is outside the startup disk")
    return candidate


def browse_disk(path, kind):
    current = _safe_disk_path(path)
    if current.is_file():
        current = current.parent
    if not current.exists() or not current.is_dir():
        current = SSD_ROOT

    dirs = []
    files = []
    try:
        children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
    except OSError:
        children = []
    for child in children:
        if child.name.startswith("$") or child.name in {"System Volume Information", "Recovery"}:
            continue
        if child.is_dir():
            dirs.append({"name": child.name, "path": str(child)})
        elif kind == "db" and child.is_file() and child.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            files.append({"name": child.name, "path": str(child)})

    parent = ""
    root = SSD_ROOT.resolve()
    if current.resolve() != root:
        parent = str(current.parent)
    return {
        "root": str(SSD_ROOT),
        "path": str(current),
        "parent": parent,
        "dirs": dirs,
        "files": files,
    }


@dataclass(frozen=True)
class LibraryProviderCandidate:
    provider: str
    name: str
    path: Path
    status: str
    note: str

    def to_dict(self):
        return {
            "provider": self.provider,
            "name": self.name,
            "path": str(self.path),
            "status": self.status,
            "note": self.note,
        }


def _home_candidates(*parts):
    home = Path.home()
    return [home.joinpath(*parts)] if str(home) else []


def discover_library_candidates():
    candidates = [
        LibraryProviderCandidate(
            "denon_engine",
            "Denon Engine DJ",
            DB_PATH,
            "supported" if DB_PATH.exists() else "missing",
            "Active provider. Reads Engine Library/Database2/m.db.",
        )
    ]

    known = [
        (
            "rekordbox",
            "Pioneer rekordbox",
            "detected_not_supported",
            "Detected candidate only. A rekordbox adapter is not implemented yet.",
            [
                SSD_ROOT / "PIONEER" / "rekordbox" / "export.pdb",
                *(_home_candidates("AppData", "Roaming", "Pioneer", "rekordbox", "master.db")),
            ],
        ),
        (
            "traktor",
            "Native Instruments Traktor",
            "detected_not_supported",
            "Detected candidate only. A Traktor collection.nml adapter is not implemented yet.",
            [
                SSD_ROOT / "Traktor" / "collection.nml",
                *(_home_candidates("Documents", "Native Instruments")),
            ],
        ),
    ]

    for provider, name, status, note, paths in known:
        for path in paths:
            if path.is_file():
                candidates.append(LibraryProviderCandidate(provider, name, path, status, note))
            elif path.is_dir() and provider == "traktor":
                for nml in sorted(path.glob("Traktor*/collection.nml")):
                    candidates.append(LibraryProviderCandidate(provider, name, nml, status, note))
    return candidates


def active_library_provider():
    return {
        "provider": ACTIVE_LIBRARY_PROVIDER,
        "name": "Denon Engine DJ",
        "path": str(DB_PATH),
        "status": "ready" if DB_PATH.exists() else "missing",
        "note": "Current working adapter expects the Denon Engine Track table schema.",
    }


STYLE_GROUPS = [
    ("House", ["House", "Tech House", "Deep House", "Progressive House", "Afro House", "Disco House", "Funky House", "Funky", "Groove", "Club House", "Electro House", "Future House", "Jackin House", "Soulful House", "Jazz House", "Chill House", "Euro-House"]),
    ("Electronic / Dance", ["Electronic", "electronics", "Electronica", "Dance", "EDM", "Indie Dance", "Nu Disco", "Electro", "Eurodance", "Synth-pop"]),
    ("Techno", ["Techno", "techno", "Minimal", "Minimal / Deep Tech", "Deep Tech", "Melodic Techno"]),
    ("Bass / Breaks", ["Drum & Bass", "dnb", "Break Beat", "Breakbeat", "Garage", "UK Garage", "Trip-Hop", "Hip Hop", "Rap"]),
    ("Rock", ["Rock", "rock", "Alternative", "Alternative Rock", "Punk", "Punk Rock", "Folk Rock", "Hard Rock", "Horror Punk", "rusrock"]),
    ("Pop", ["Pop", "pop", "Europop", "RusPop", "ruspop", "Рор", "Shanson"]),
    ("Chill / Other", ["Chill Out", "Chillout", "chill", "Ambient", "Downtempo", "Lounge", "Jazz", "Funk", "Disco", "Soul", "Soul & Funk", "Reggae", "Blues", "Easy Listening", "Soundtrack", "Other"]),
]


STYLE_CANONICAL = {
    "breakbeat": "break_beat",
    "drum_bass": "drum_and_bass",
    "drum_n_bass": "drum_and_bass",
    "d_b": "dnb",
    "funky": "funky_house",
    "groove": "funky_house",
    "funky_groove": "funky_house",
    "funky_house": "funky_house",
    "jackin": "jackin_house",
    "jackin_house": "jackin_house",
    "chill_house": "chill_house",
    "deep_tech": "minimal_deep_tech",
    "minimal_deep_tech": "minimal_deep_tech",
    "euro_house": "euro_house",
    "soul_funk": "soul_and_funk",
    "soul_and_funk": "soul_and_funk",
}


NOTE_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
CAMELOT_MAJOR = {
    "C": "8B", "C#": "3B", "D": "10B", "D#": "5B", "E": "12B", "F": "7B",
    "F#": "2B", "G": "9B", "G#": "4B", "A": "11B", "A#": "6B", "B": "1B",
}
CAMELOT_MINOR = {
    "C": "5A", "C#": "12A", "D": "7A", "D#": "2A", "E": "9A", "F": "4A",
    "F#": "11A", "G": "6A", "G#": "1A", "A": "8A", "A#": "3A", "B": "10A",
}


def engine_key_to_camelot(key):
    if key is None or key < 0 or key > 23:
        return ""
    note = NOTE_SHARP[key] if key <= 11 else NOTE_SHARP[key - 12]
    return (CAMELOT_MAJOR if key <= 11 else CAMELOT_MINOR).get(note, "")


def normalize_style(value):
    value = (value or "").casefold().strip()
    value = re.sub(r"&", " and ", value)
    value = re.sub(r"[^a-zа-я0-9]+", "_", value, flags=re.I)
    normalized = re.sub(r"_+", "_", value).strip("_")
    return STYLE_CANONICAL.get(normalized, normalized)


def open_db():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def resolve_track_path(raw_path):
    if not raw_path:
        return ""
    original = str(raw_path).strip()
    raw = original.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", raw):
        win_path = PureWindowsPath(original)
        try:
            rel = win_path.relative_to(PureWindowsPath("G:/Music"))
            return str(MUSIC_ROOT.joinpath(*rel.parts).resolve())
        except ValueError:
            return original
    if os.path.isabs(original):
        return original
    for prefix in ("../Music/", "Music/"):
        if raw.startswith(prefix):
            rel = raw[len(prefix):]
            return str(MUSIC_ROOT.joinpath(*[p for p in rel.split("/") if p]).resolve())
    if raw.startswith("../"):
        raw = raw[3:]
    return str(MUSIC_ROOT.joinpath(*[p for p in raw.split("/") if p]).resolve())


def label(row):
    artist = (row["artist"] or "").strip()
    title = (row["title"] or "").strip()
    return " - ".join([p for p in (artist, title) if p]) or (row["filename"] or "")


def row_to_track(row):
    path = resolve_track_path(row["path"])
    return {
        "id": int(row["id"]),
        "label": label(row),
        "artist": row["artist"] or "",
        "title": row["title"] or row["filename"] or "",
        "filename": row["filename"] or "",
        "genre": row["genre"] or "",
        "bpm": None if row["bpmAnalyzed"] is None else round(float(row["bpmAnalyzed"]), 1),
        "camelot": engine_key_to_camelot(None if row["key"] is None else int(row["key"])),
        "bitrate": row["bitrate"] or "",
        "length": row["length"] or 0,
        "path": path,
        "rel": rel_to_music(path) if path else "",
    }


def norm_abs(path):
    try:
        return str(Path(path).resolve()).replace("\\", "/").casefold()
    except Exception:
        return str(path).replace("\\", "/").casefold()


def rel_to_music(path):
    try:
        return str(Path(path).resolve().relative_to(MUSIC_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return ""


def safe_music_path(rel):
    rel = (rel or "").replace("\\", "/").strip("/")
    target = (MUSIC_ROOT / rel).resolve()
    root = MUSIC_ROOT.resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path is outside Music")
    return target


def safe_media_path(value):
    value = (value or "").strip()
    if not value:
        raise ValueError("Empty media path")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = safe_music_path(value)
    else:
        candidate = candidate.resolve()
        root = MUSIC_ROOT.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("Media path is outside Music")
    if candidate.suffix.lower() not in AUDIO_EXTS:
        raise ValueError("Unsupported media type")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError("Media file does not exist")
    return candidate


def load_track_maps():
    by_path = {}
    by_name = {}
    sql = """
        SELECT id, filename, length, bitrate, bpmAnalyzed, key, genre, artist, title, path
        FROM Track
        WHERE isAvailable = 1
          AND path IS NOT NULL
    """
    with open_db() as con:
        for row in con.execute(sql):
            track = row_to_track(row)
            if track["path"]:
                by_path[norm_abs(track["path"])] = track
            by_name.setdefault((track["filename"] or "").casefold(), []).append(track)
    unique_name = {name: rows[0] for name, rows in by_name.items() if name and len(rows) == 1}
    return by_path, unique_name


def read_file_tags(path):
    item = {
        "id": None,
        "label": path.stem,
        "artist": "",
        "title": path.name,
        "filename": path.name,
        "genre": "",
        "bpm": None,
        "camelot": "",
        "bitrate": "",
        "length": 0,
        "path": str(path),
    }
    try:
        from mutagen import File

        audio = File(str(path), easy=True)
        if audio:
            item["title"] = (audio.get("title", [""])[0] or path.name)
            item["artist"] = audio.get("artist", [""])[0] or ""
            item["genre"] = audio.get("genre", [""])[0] or ""
            bpm = audio.get("bpm", [""])[0] or ""
            item["bpm"] = round(float(bpm), 1) if bpm else None
            item["camelot"] = audio.get("initialkey", [""])[0] or audio.get("key", [""])[0] or ""
            item["length"] = int(getattr(audio.info, "length", 0) or 0)
            br = int((getattr(audio.info, "bitrate", 0) or 0) / 1000)
            item["bitrate"] = br or ""
            item["label"] = " - ".join([p for p in (item["artist"], item["title"]) if p]) or path.name
    except Exception:
        pass
    return item


def track_for_file(path, by_path, unique_name):
    return by_path.get(norm_abs(path)) or unique_name.get(path.name.casefold()) or read_file_tags(path)


def browse_music(rel):
    current = safe_music_path(rel)
    if not current.exists() or not current.is_dir():
        raise ValueError("Folder does not exist")
    by_path, unique_name = load_track_maps()
    dirs = []
    tracks = []
    try:
        children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
    except OSError:
        children = []
    for child in children:
        if child.is_dir():
            dirs.append({"name": child.name, "rel": rel_to_music(child)})
        elif child.is_file() and child.suffix.lower() in AUDIO_EXTS:
            tr = track_for_file(child, by_path, unique_name)
            tr["rel"] = rel_to_music(child)
            tr["source"] = "engine" if tr.get("id") else "file"
            tracks.append(tr)
    parent = ""
    if current.resolve() != MUSIC_ROOT.resolve():
        parent = rel_to_music(current.parent)
    return {"rel": rel_to_music(current), "parent": parent, "dirs": dirs, "tracks": tracks}


def search_tracks(query, limit):
    terms = [t.casefold() for t in re.split(r"\s+", query or "") if t.strip()]
    sql = """
        SELECT id, filename, length, bitrate, bpmAnalyzed, key, genre, artist, title, path
        FROM Track
        WHERE isAvailable = 1
          AND bpmAnalyzed IS NOT NULL
          AND key IS NOT NULL
          AND length IS NOT NULL
          AND length BETWEEN 75 AND 720
          AND path IS NOT NULL
        ORDER BY artist, title, filename
    """
    out = []
    with open_db() as con:
        for row in con.execute(sql):
            p = resolve_track_path(row["path"]).replace("\\", "/").casefold()
            if "/music/set/" in p or "/music/sets/" in p:
                continue
            haystack = " ".join([
                row["artist"] or "", row["title"] or "", row["filename"] or "", row["genre"] or "", p
            ]).casefold()
            if terms and not all(t in haystack for t in terms):
                continue
            out.append(row_to_track(row))
            if len(out) >= limit:
                break
    return out


def genre_counts():
    counts = {}
    with open_db() as con:
        rows = con.execute(
            """
            SELECT genre, COUNT(*) AS n
            FROM Track
            WHERE genre IS NOT NULL AND trim(genre) != ''
            GROUP BY genre
            ORDER BY n DESC
            """
        ).fetchall()
    for genre, count in rows:
        for part in re.split(r"[,;/|<>]+", genre or ""):
            label = re.sub(r"\s+", " ", part).strip()
            norm = normalize_style(label)
            if not norm:
                continue
            current = counts.get(norm, {"label": label, "count": 0})
            current["count"] += int(count or 0)
            if len(label) < len(current["label"]) or current["label"].islower():
                current["label"] = label
            counts[norm] = current
    return counts


def style_groups():
    counts = genre_counts()
    used = set()
    groups = []
    for group_name, labels in STYLE_GROUPS:
        items = []
        for label in labels:
            norm = normalize_style(label)
            if norm in used:
                continue
            data = counts.get(norm, {"label": label, "count": 0})
            if data["count"] > 0 or label in {"House", "Electronic", "Dance", "Techno", "Drum & Bass", "Pop", "Rock"}:
                items.append({"value": norm, "label": data["label"], "count": data["count"]})
                used.add(norm)
        if items:
            groups.append({"name": group_name, "styles": items})
    other = [
        {"value": norm, "label": data["label"], "count": data["count"]}
        for norm, data in counts.items()
        if norm not in used and data["count"] >= 10
    ]
    other.sort(key=lambda x: (-x["count"], x["label"].casefold()))
    if other:
        groups.append({"name": "Other", "styles": other[:36]})
    return groups


def genre_options():
    seen = {}
    for group in style_groups():
        for style in group["styles"]:
            seen.setdefault(style["label"].casefold(), style["label"])
    return sorted(seen.values(), key=lambda s: s.casefold())


def update_file_genre(path, genre):
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        from mutagen.id3 import ID3, ID3NoHeaderError, TCON

        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("TCON")
        tags.add(TCON(encoding=3, text=[genre]))
        tags.save(str(path), v2_version=3)
        return True
    if suffix == ".flac":
        from mutagen.flac import FLAC

        audio = FLAC(str(path))
        audio["GENRE"] = [genre]
        audio.save()
        return True
    return False


def update_genre(track_id, genre):
    genre = re.sub(r"\s+", " ", str(genre or "")).strip()
    if not genre:
        raise ValueError("Genre is empty")
    with open_db() as con:
        row = con.execute(
            "SELECT id, filename, length, bitrate, bpmAnalyzed, key, genre, artist, title, path FROM Track WHERE id = ?",
            (int(track_id),),
        ).fetchone()
        if not row:
            raise ValueError("Track not found")
        con.execute("UPDATE Track SET genre = ? WHERE id = ?", (genre, int(track_id)))
        con.commit()
    track = row_to_track(row)
    path = safe_media_path(track["rel"] or track["path"])
    file_written = update_file_genre(path, genre)
    track["genre"] = genre
    return {"ok": True, "track": track, "file_written": file_written}


def build_set(track_id, role, minutes, max_key_step, bpm_window, style_filter):
    if role not in {"start", "peak"}:
        raise ValueError("role must be start or peak")
    minutes = max(15, min(360, int(minutes)))
    max_key_step = max(0, min(12, int(max_key_step)))
    bpm_window = max(0, min(80, float(bpm_window)))
    style_filter = ",".join(
        p.strip().lower()
        for p in (style_filter or [])
        if isinstance(p, str) and p.strip()
    )
    cmd = [
        sys.executable,
        "-B",
        str(BUILDER),
        ".",
        "--reference-id",
        str(int(track_id)),
        "--role",
        role,
        "--minutes",
        str(minutes),
        "--max-key-step",
        str(max_key_step),
        "--bpm-window",
        str(bpm_window),
        "--style-filter",
        style_filter,
        "--db-path",
        str(DB_PATH),
        "--library-provider",
        ACTIVE_LIBRARY_PROVIDER,
        "--music-root",
        str(MUSIC_ROOT),
        "--out-dir",
        str(SETS_DIR),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(TOOLS_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60 * 45,
    )
    output = result.stdout or ""
    set_folder = ""
    for line in output.splitlines():
        if line.startswith("Set folder:"):
            set_folder = line.split(":", 1)[1].strip()
            break
    return {"ok": result.returncode == 0, "code": result.returncode, "output": output, "set_folder": set_folder}


def _engine_now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _engine_slug(text):
    text = re.sub(r"[^\w\- ]+", "", str(text or ""), flags=re.U).strip()
    text = re.sub(r"\s+", "_", text)
    return (text[:80] or "playlist")


def _engine_reference_genre_slug(genre_text):
    parts = [p.strip() for p in re.split(r"[,;/|<>]+", str(genre_text or "")) if p.strip()]
    base = parts[0] if parts else str(genre_text or "")
    return (_engine_slug(base).lower() or "mixed")


def unified_set_or_playlist_name(reference_genre, reference_label):
    date_str = datetime.now().strftime("%d.%m.%y")
    genre_slug = _engine_reference_genre_slug(reference_genre)
    label_slug = _engine_slug(reference_label)
    # Требование: genre_dd.mm.yy_reference (одинаково для set/playlist/Engine)
    return f"{genre_slug}_{date_str}_{label_slug}"


def _get_engine_database_uuid(con):
    row = con.execute(
        """
        SELECT databaseUuid, COUNT(*) AS c
        FROM PlaylistEntity
        WHERE databaseUuid IS NOT NULL AND databaseUuid != ''
        GROUP BY databaseUuid
        ORDER BY c DESC
        LIMIT 1
        """
    ).fetchone()
    if row and row[0]:
        return str(row[0])
    row = con.execute("SELECT uuid FROM Information LIMIT 1").fetchone()
    if row and row[0]:
        return str(row[0])
    raise ValueError("Cannot determine Engine databaseUuid")


def _find_playlist(con, parent_list_id, title):
    return con.execute(
        "SELECT id, title, parentListId, nextListId FROM Playlist WHERE parentListId=? AND title=?",
        (int(parent_list_id), str(title)),
    ).fetchone()


def _find_last_child_list_id(con, parent_list_id):
    row = con.execute(
        "SELECT id FROM Playlist WHERE parentListId=? AND nextListId=0",
        (int(parent_list_id),),
    ).fetchone()
    return (None if not row else int(row[0]))


def _insert_playlist(con, parent_list_id, title):
    now = _engine_now_str()
    cur = con.execute(
        """
        INSERT INTO Playlist(title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported)
        VALUES (?, ?, 1, 0, ?, 1)
        """,
        (str(title), int(parent_list_id), now),
    )
    new_id = int(cur.lastrowid)
    last_child = _find_last_child_list_id(con, parent_list_id)
    if last_child is not None and last_child != new_id:
        con.execute("UPDATE Playlist SET nextListId=? WHERE id=?", (new_id, last_child))
    return new_id


def _ensure_folder_path(con, folder_path):
    parts = [p.strip() for p in str(folder_path).replace("\\", "/").split("/") if p.strip()]
    parent_id = 0
    for part in parts:
        row = _find_playlist(con, parent_id, part)
        if row:
            parent_id = int(row[0])
            continue
        parent_id = _insert_playlist(con, parent_id, part)
    return parent_id


def _engine_track_path_for_abs(abs_path):
    abs_path = Path(abs_path).resolve()
    rel = abs_path.relative_to(MUSIC_ROOT.resolve()).as_posix()
    return f"../Music/{rel}"


def _read_set_source_paths(set_folder):
    set_folder = Path(set_folder)
    csv_path = set_folder / "playlist.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"playlist.csv not found: {csv_path}")
    import csv

    paths = []
    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"playlist.csv has no header: {csv_path}")
        header = {h.strip() for h in reader.fieldnames if h}
        if "source_path" not in header:
            raise ValueError(f"playlist.csv missing 'source_path' column: {csv_path}")
        for row in reader:
            src = (row.get("source_path") or "").strip()
            if src:
                paths.append(src)
    seen = set()
    out = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def create_engine_playlist_from_set(set_folder, folder_path, title):
    set_folder = str(set_folder or "").strip()
    folder_path = str(folder_path or "").strip()
    title = str(title or "").strip()
    if not set_folder or not folder_path or not title:
        raise ValueError("set_folder, folder and title are required")

    source_paths = _read_set_source_paths(set_folder)
    if not source_paths:
        raise ValueError("No source tracks found in playlist.csv")

    con = sqlite3.connect(str(DB_PATH))
    try:
        con.execute("PRAGMA foreign_keys=ON;")
        database_uuid = _get_engine_database_uuid(con)
        with con:
            parent_id = _ensure_folder_path(con, folder_path)
            if _find_playlist(con, parent_id, title):
                raise ValueError(f"Playlist already exists: {folder_path}/{title}")

            list_id = _insert_playlist(con, parent_id, title)

            missing = []
            track_ids = []
            for p in source_paths:
                abs_path = str(Path(p).resolve())
                try:
                    engine_path = _engine_track_path_for_abs(abs_path)
                except Exception:
                    engine_path = abs_path
                row = con.execute("SELECT id FROM Track WHERE path=?", (engine_path,)).fetchone()
                if not row:
                    row = con.execute("SELECT id FROM Track WHERE path=?", (abs_path,)).fetchone()
                if not row:
                    missing.append((abs_path, engine_path))
                    continue
                track_ids.append(int(row[0]))

            if missing:
                lines = ["Some tracks are not imported in Engine DB (Track.path not found):"]
                for abs_path, engine_path in missing[:30]:
                    lines.append(f"- {abs_path} (expected: {engine_path})")
                if len(missing) > 30:
                    lines.append(f"... and {len(missing) - 30} more")
                raise ValueError("\n".join(lines))

            next_entity_id = 0
            for track_id in reversed(track_ids):
                cur = con.execute(
                    """
                    INSERT INTO PlaylistEntity(listId, trackId, databaseUuid, nextEntityId, membershipReference)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (int(list_id), int(track_id), database_uuid, int(next_entity_id)),
                )
                next_entity_id = int(cur.lastrowid)

            con.execute("UPDATE Playlist SET lastEditTime=? WHERE id=?", (_engine_now_str(), int(list_id)))

        return {
            "ok": True,
            "playlist_id": list_id,
            "track_count": len(source_paths),
            "output": f"Engine playlist created: {folder_path}/{title} (id={list_id}), tracks: {len(source_paths)}",
        }
    finally:
        con.close()


def _build_playlist_only(track_id, role, minutes, max_key_step, bpm_window, style_filter):
    minutes = max(15, min(360, int(minutes)))
    max_key_step = max(0, min(12, int(max_key_step)))
    bpm_window = max(0, min(80, float(bpm_window)))
    style_filter = ",".join(
        p.strip().lower()
        for p in (style_filter or [])
        if isinstance(p, str) and p.strip()
    )
    cmd = [
        sys.executable,
        "-B",
        str(BUILDER),
        ".",
        "--reference-id",
        str(int(track_id)),
        "--role",
        role,
        "--minutes",
        str(minutes),
        "--max-key-step",
        str(max_key_step),
        "--bpm-window",
        str(bpm_window),
        "--db-path",
        str(DB_PATH),
        "--library-provider",
        ACTIVE_LIBRARY_PROVIDER,
        "--music-root",
        str(MUSIC_ROOT),
        "--no-copy",
        "--emit-playlist-json",
    ]
    if style_filter:
        cmd += ["--style-filter", style_filter]
    result = subprocess.run(
        cmd,
        cwd=str(TOOLS_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60 * 20,
    )
    output = result.stdout or ""
    if result.returncode != 0:
        raise ValueError(output.strip() or "Failed to build playlist")
    try:
        return json.loads(output.strip().splitlines()[0])
    except Exception as exc:
        raise ValueError(f"Failed to parse playlist json: {exc}\n\nOutput:\n{output}") from exc


def _safe_slug(value, max_len=64):
    value = str(value or "").strip()
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"[^0-9A-Za-zА-Яа-я _\\-.,()\\[\\]]+", "", value)
    value = value.replace(" ", "_")
    return value[:max_len] if len(value) > max_len else value


def _engine_playlist_local_folder_name(playlist, role):
    ref_id = playlist.get("reference_id")
    ref = None
    for t in (playlist.get("tracks") or []):
        if isinstance(t, dict) and t.get("id") == ref_id:
            ref = t
            break
    if not ref:
        ref = next((t for t in (playlist.get("tracks") or []) if isinstance(t, dict)), {}) or {}
    ref_label = (
        f"{ref.get('artist') or ''} - {ref.get('title') or ref.get('filename') or ''}".strip(" -")
        or str(ref.get("filename") or "playlist")
    )
    name = unified_set_or_playlist_name(ref.get("genre") or "", ref_label)
    return _safe_slug(name, 120) or _safe_slug(f"engine_playlist_{datetime.now().strftime('%d.%m.%y')}", 96)


def write_local_playlist_no_copy(playlist, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    m3u_path = out_dir / "playlist.m3u"
    csv_path = out_dir / "playlist.csv"

    tracks = playlist.get("tracks") or []
    with m3u_path.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for t in tracks:
            if not isinstance(t, dict):
                continue
            length = int(t.get("length") or 0)
            artist = str(t.get("artist") or "").strip()
            title = str(t.get("title") or t.get("filename") or "").strip()
            label = f"{artist} - {title}".strip(" -") if (artist or title) else str(t.get("filename") or "")
            path = str(t.get("path") or "").strip()
            f.write(f"#EXTINF:{length},{label}\n")
            f.write(f"{path}\n")

    import csv
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "position",
            "artist",
            "title",
            "length",
            "bpm",
            "key",
            "genre",
            "track_id",
            "source_path",
        ])
        for i, t in enumerate(tracks, 1):
            if not isinstance(t, dict):
                continue
            w.writerow([
                i,
                t.get("artist") or "",
                t.get("title") or "",
                t.get("length") or "",
                t.get("bpm") or "",
                t.get("key") or "",
                t.get("genre") or "",
                t.get("id") or "",
                t.get("path") or "",
            ])

    methodology_path = out_dir / "methodology.txt"
    with methodology_path.open("w", encoding="utf-8") as f:
        f.write("Playlist (no-copy) methodology\n")
        f.write("- Uses Engine DJ metadata (BPM/key/genre/length/path).\n")
        f.write("- Builds a harmonic playlist with the same algorithm as set builder.\n")
        f.write("- Does NOT copy or rename files; playlist.m3u points to original tracks.\n")

    return {"folder": str(out_dir), "m3u": str(m3u_path), "csv": str(csv_path)}


def create_engine_playlist_from_paths(track_paths, folder_path, title):
    folder_path = str(folder_path or "").strip()
    title = str(title or "").strip()
    if not folder_path or not title:
        raise ValueError("folder and title are required")
    track_paths = [str(Path(p).resolve()) for p in (track_paths or []) if str(p).strip()]
    if not track_paths:
        raise ValueError("Empty track list")

    con = sqlite3.connect(str(DB_PATH))
    try:
        con.execute("PRAGMA foreign_keys=ON;")
        database_uuid = _get_engine_database_uuid(con)
        with con:
            parent_id = _ensure_folder_path(con, folder_path)
            if _find_playlist(con, parent_id, title):
                raise ValueError(f"Playlist already exists: {folder_path}/{title}")

            list_id = _insert_playlist(con, parent_id, title)

            missing = []
            track_ids = []
            for abs_path in track_paths:
                try:
                    engine_path = _engine_track_path_for_abs(abs_path)
                except Exception:
                    engine_path = abs_path
                row = con.execute("SELECT id FROM Track WHERE path=?", (engine_path,)).fetchone()
                if not row:
                    row = con.execute("SELECT id FROM Track WHERE path=?", (abs_path,)).fetchone()
                if not row:
                    missing.append((abs_path, engine_path))
                    continue
                track_ids.append(int(row[0]))

            if missing:
                lines = ["Some tracks are not imported in Engine DB (Track.path not found):"]
                for abs_path, engine_path in missing[:30]:
                    lines.append(f"- {abs_path} (expected: {engine_path})")
                if len(missing) > 30:
                    lines.append(f"... and {len(missing) - 30} more")
                raise ValueError("\n".join(lines))

            next_entity_id = 0
            for track_id in reversed(track_ids):
                cur = con.execute(
                    """
                    INSERT INTO PlaylistEntity(listId, trackId, databaseUuid, nextEntityId, membershipReference)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (int(list_id), int(track_id), database_uuid, int(next_entity_id)),
                )
                next_entity_id = int(cur.lastrowid)

            con.execute("UPDATE Playlist SET lastEditTime=? WHERE id=?", (_engine_now_str(), int(list_id)))

        return {
            "ok": True,
            "playlist_id": list_id,
            "track_count": len(track_ids),
            "output": f"Engine playlist created: {folder_path}/{title} (id={list_id}), tracks: {len(track_ids)}",
        }
    finally:
        con.close()


def refresh_tags(rel):
    target = safe_music_path(rel)
    rel_norm = rel_to_music(target).replace("\\", "/").casefold()
    if rel_norm in {"set", "sets"} or rel_norm.startswith("set/") or rel_norm.startswith("sets/"):
        raise ValueError("Set/Sets folders are protected from tag refresh")
    cmd = [
        sys.executable,
        "-B",
        str(TOOLS_DIR / "engine_write_tags.py"),
        "--db-path",
        str(DB_PATH),
        "--music-root",
        str(MUSIC_ROOT),
        "--report-dir",
        str(SSD_ROOT / "zmin_autoset" / "reports"),
        "--backup-dir",
        str(SSD_ROOT / "zmin_autoset" / "tag_backups"),
        "--key-format",
        "camelot",
        "--write-bitrate-tag",
        "--apply",
        str(target),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(TOOLS_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60 * 30,
    )
    return {"ok": result.returncode == 0, "code": result.returncode, "output": result.stdout or ""}


def refresh_genres(rel):
    target = safe_music_path(rel)
    cmd = [
        sys.executable,
        "-B",
        str(TOOLS_DIR / "review_new_genres.py"),
        str(target),
        "--db-path",
        str(DB_PATH),
        "--music-root",
        str(MUSIC_ROOT),
        "--report-dir",
        str(SSD_ROOT / "zmin_autoset" / "reports" / "genres"),
        "--backup-dir",
        str(SSD_ROOT / "zmin_autoset" / "tag_backups"),
        "--apply",
        "--no-backup",
        "--min-confidence",
        "medium",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(TOOLS_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60 * 30,
    )
    return {"ok": result.returncode == 0, "code": result.returncode, "output": result.stdout or ""}


def startup_refresh_new():
    target_rel = "New"
    try:
        target = safe_music_path(target_rel)
        if not target.exists():
            APP_STATE["startup_refresh"] = "New folder not found"
            return
        APP_STATE["startup_refresh"] = "refreshing New tags"
        tag_result = refresh_tags(target_rel)
        APP_STATE["startup_refresh"] = "refreshing New genres"
        genre_result = refresh_genres(target_rel)
        APP_STATE["startup_refresh"] = (
            f"New auto-refresh done: tags={'ok' if tag_result['ok'] else 'error'}, "
            f"genres={'ok' if genre_result['ok'] else 'error'}"
        )
    except Exception as exc:
        APP_STATE["startup_refresh"] = f"New auto-refresh error: {exc!r}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_media(self, path):
        size = path.stat().st_size
        start = 0
        end = size - 1
        status = 200
        range_header = self.headers.get("Range", "")
        if range_header.startswith("bytes="):
            status = 206
            spec = range_header.split("=", 1)[1].split(",", 1)[0]
            left, _, right = spec.partition("-")
            if left:
                start = max(0, int(left))
            if right:
                end = min(size - 1, int(right))
        if start > end:
            self.send_error(416)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(1024 * 512, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            data = INDEX_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/api/config":
            library_candidates = [c.to_dict() for c in discover_library_candidates()]
            self.send_json({
                "ssd_root": str(SSD_ROOT),
                "music_root": str(MUSIC_ROOT),
                "sets_dir": str(SETS_DIR),
                "db_path": str(DB_PATH),
                "config_path": str(CONFIG_PATH),
                "builder": str(BUILDER),
                "app_name": APP_NAME,
                "version": APP_VERSION,
                "repository_url": APP_REPOSITORY_URL,
                "library_provider": active_library_provider(),
                "library_candidates": library_candidates,
                "music_ready": MUSIC_ROOT.exists(),
                "db_ready": DB_PATH.exists(),
                "ready": DB_PATH.exists() and MUSIC_ROOT.exists() and BUILDER.exists(),
                "startup_refresh": APP_STATE.get("startup_refresh", ""),
            })
            return
        if parsed.path == "/api/search":
            qs = parse_qs(parsed.query)
            query = qs.get("q", [""])[0]
            limit = int(qs.get("limit", ["60"])[0])
            self.send_json({"tracks": search_tracks(query, max(1, min(200, limit)))})
            return
        if parsed.path == "/api/styles":
            self.send_json({"groups": style_groups()})
            return
        if parsed.path == "/api/genres":
            self.send_json({"genres": genre_options()})
            return
        if parsed.path == "/api/disk-tree":
            qs = parse_qs(parsed.query)
            kind = qs.get("kind", ["folder"])[0]
            path = qs.get("path", [""])[0]
            try:
                self.send_json(browse_disk(path, kind))
            except Exception as exc:
                self.send_json({"error": repr(exc)}, status=400)
            return
        if parsed.path == "/api/browse":
            qs = parse_qs(parsed.query)
            rel = qs.get("path", [""])[0]
            try:
                self.send_json(browse_music(rel))
            except Exception as exc:
                self.send_json({"error": repr(exc)}, status=400)
            return
        if parsed.path == "/media":
            qs = parse_qs(parsed.query)
            try:
                self.send_media(safe_media_path(qs.get("path", [""])[0]))
            except Exception as exc:
                self.send_json({"error": repr(exc)}, status=400)
            return
        self.send_error(404)

    def do_POST(self):
        parsed_path = urlparse(self.path).path
        if parsed_path not in {"/api/build", "/api/engine-playlist", "/api/refresh-tags", "/api/update-genre", "/api/config"}:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        try:
            if parsed_path == "/api/config":
                config = save_path_config(data)
                self.send_json({
                    "ok": True,
                    "config": config,
                    "music_ready": MUSIC_ROOT.exists(),
                    "db_ready": DB_PATH.exists(),
                    "ready": DB_PATH.exists() and MUSIC_ROOT.exists() and BUILDER.exists(),
                })
            elif parsed_path == "/api/build":
                self.send_json(build_set(data["track_id"], data.get("role", "start"), data.get("minutes", 90), data.get("max_key_step", 5), data.get("bpm_window", 5), data.get("style_filter", [])))
            elif parsed_path == "/api/engine-playlist":
                playlist = _build_playlist_only(
                    data["track_id"],
                    data.get("role", "start"),
                    data.get("minutes", 90),
                    data.get("max_key_step", 5),
                    data.get("bpm_window", 5),
                    data.get("style_filter", []),
                )
                local_name = _engine_playlist_local_folder_name(playlist, data.get("role", "start"))
                local_out = write_local_playlist_no_copy(playlist, SETS_DIR / local_name)
                paths = [t.get("path") for t in (playlist.get("tracks") or []) if isinstance(t, dict)]
                # Название плейлиста (и локальной папки) должно быть одинаковым для set/playlist/Engine.
                result = create_engine_playlist_from_paths(paths, data.get("folder", ""), local_name)
                result["local_playlist_folder"] = local_out["folder"]
                result["local_m3u"] = local_out["m3u"]
                result["local_csv"] = local_out["csv"]
                result["engine_playlist_title"] = local_name
                self.send_json(result)
            elif parsed_path == "/api/refresh-tags":
                self.send_json(refresh_tags(data.get("path", "")))
            else:
                self.send_json(update_genre(data["track_id"], data["genre"]))
        except Exception as exc:
            self.send_json({"ok": False, "error": repr(exc)}, status=500)


def main():
    if not DB_PATH.exists():
        print(f"Engine DB not found: {DB_PATH}")
    if not BUILDER.exists():
        print(f"Set builder not found: {BUILDER}")
    server = None
    port = 8765
    for candidate in range(8765, 8780):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", candidate)) == 0:
                continue
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("No free local port found in 8765..8779")
    url = f"http://127.0.0.1:{port}/"
    print(f"Set Builder UI: {url}")
    threading.Thread(target=startup_refresh_new, daemon=True).start()
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
