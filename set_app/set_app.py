import hashlib
import json
import mimetypes
import os
import re
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import webbrowser
import zlib
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
SSD_ROOT = PROJECT_DIR.parent
TOOLS_DIR = PROJECT_DIR / "tools"
BUILDER = TOOLS_DIR / "engine_set_builder.py"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
from engine_write_tags import write_audio_tags
from engine_cue_loop_codec import (
    build_loops,
    build_quick_cues,
    empty_loops,
    empty_quick_cues,
    parse_loops,
    parse_quick_cues,
)
CONFIG_PATH = APP_DIR / "paths.json"
DEFAULT_MUSIC_ROOT = SSD_ROOT / "Music" if (SSD_ROOT / "Music").exists() else SSD_ROOT
DEFAULT_SETS_DIR = DEFAULT_MUSIC_ROOT / "Sets"
DEFAULT_DB_PATH = SSD_ROOT / "Engine Library" / "Database2" / "m.db"
MUSIC_ROOT = DEFAULT_MUSIC_ROOT
SETS_DIR = DEFAULT_SETS_DIR
DB_PATH = DEFAULT_DB_PATH
INDEX_HTML = APP_DIR / "index.html"
TRACK_MARKS_DIR = APP_DIR / "track_marks"
ENGINE_DB_BACKUP_DIR = APP_DIR / "backups" / "engine_db"
# Engine cue/loop raw positions are stored as frames at 44100 Hz based on diff diagnostics.
ENGINE_CUE_TIME_SCALE = 44100.0
ENGINE_MARK_TO_CUE_SLOT = {
    "MIX_IN": 1,
    "VOCAL_IN": 2,
    "DROP": 3,
    "BREAK": 4,
    "MIX_OUT": 5,
    "OUTRO": 6,
}
ENGINE_CUE_SLOT_LABELS = {
    "MIX_IN": "MIX IN",
    "VOCAL_IN": "VOCAL",
    "DROP": "DROP",
    "BREAK": "BREAK",
    "MIX_OUT": "MIX OUT",
    "OUTRO": "OUTRO",
}
ENGINE_LOOP_TYPE_TO_SLOT = {"OUTRO_LOOP": 1, "EMERGENCY_LOOP": 2}
ENGINE_LOOP_TYPE_LABELS = {"OUTRO_LOOP": "OUTRO LOOP", "EMERGENCY_LOOP": "EMERGENCY"}
ENGINE_CUE_SLOT_COLORS = {
    1: 0xFFF4D338,
    2: 0xFF4FC3F7,
    3: 0xFF5AD66F,
    4: 0xFFAA55C4,
    5: 0xFFEF6B73,
    6: 0xFFFF8A3D,
}
ENGINE_LOOP_SLOT_COLORS = {1: 0xFFF4D338, 2: 0xFFEF8130}
AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".aiff", ".aif"}
SYSTEM_FILE_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}
SYSTEM_DIR_NAMES = {"__macosx", ".trashes", ".spotlight-v100", ".fseventsd", "$recycle.bin", "system volume information"}
APP_NAME = "AutoSet"
APP_VERSION = "1.5.22"
APP_REPOSITORY_URL = "https://github.com/zmin511/AutoSet"
ACTIVE_LIBRARY_PROVIDER = "denon_engine"
APP_STATE = {"startup_refresh": "waiting"}


def is_hidden_or_system_path(path):
    path = Path(path)
    parts = [part.casefold() for part in path.parts]
    if any(part in SYSTEM_DIR_NAMES for part in parts):
        return True
    name = path.name
    name_cf = name.casefold()
    if name_cf in SYSTEM_FILE_NAMES or name.startswith("._") or name.startswith("."):
        return True
    try:
        attrs = getattr(path.stat(), "st_file_attributes", 0)
        if attrs & 0x2:
            return True
    except OSError:
        return False
    return False


def is_audio_file(path):
    path = Path(path)
    return path.is_file() and path.suffix.lower() in AUDIO_EXTS and not is_hidden_or_system_path(path)


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
        if child.name.startswith("$") or child.name in {"System Volume Information", "Recovery"} or is_hidden_or_system_path(child):
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


def active_library_provider():
    return {
        "provider": ACTIVE_LIBRARY_PROVIDER,
        "name": "Denon Engine DJ",
        "path": str(DB_PATH),
        "status": "ready" if DB_PATH.exists() else "missing",
        "note": "Current working adapter expects the Denon Engine Track table schema.",
    }


STYLE_GROUPS = [
    ("House: основа и поджанры", ["House", "Deep House", "Tech House", "Progressive House", "Afro House", "Disco House", "Funky House", "Soulful House", "Jackin House", "Electro House", "Future House", "Club House", "Chill House", "Jazz House", "Euro-House"]),
    ("Techno / Deep Tech", ["Techno", "Melodic Techno", "Minimal", "Minimal / Deep Tech", "Deep Tech"]),
    ("Disco / Dance / Electronic", ["Disco", "Nu Disco", "Indie Dance", "Electro", "Electronic", "electronics", "Electronica", "Eurodance", "Synth-pop", "Dance", "EDM"]),
    ("Trance / Progressive", ["Trance", "Progressive Trance", "Psy-Trance", "Uplifting Trance"]),
    ("Bass / Breaks / Garage", ["Drum & Bass", "dnb", "Break Beat", "Breakbeat", "Garage", "UK Garage", "Trip-Hop", "Hip Hop", "Rap"]),
    ("Chill / Lounge / Downtempo", ["Chill Out", "Chillout", "chill", "Ambient", "Downtempo", "Lounge", "Easy Listening"]),
    ("Pop / Rock / Other", ["Pop", "pop", "Europop", "RusPop", "ruspop", "Shanson", "Rock", "rock", "Alternative", "Alternative Rock", "Punk", "Punk Rock", "Folk Rock", "Hard Rock", "Horror Punk", "rusrock", "Jazz", "Funk", "Soul", "Soul & Funk", "Reggae", "Blues", "Soundtrack", "Other"]),
]

RUS_ALLOW_DESCRIPTION = "Допускает в подбор треки с тегом Rus/рус вместе с выбранными стилями, BPM и Camelot."
DETAIL_CONFIDENCE_ORDER = {"low": 1, "medium": 2, "high": 3}
MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2"
DISCOGS_BASE_URL = "https://api.discogs.com"
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "").strip()
LASTFM_API_KEY_PATH = APP_DIR / "lastfm_api_key.txt"
if not LASTFM_API_KEY and LASTFM_API_KEY_PATH.exists():
    try:
        LASTFM_API_KEY = LASTFM_API_KEY_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        LASTFM_API_KEY = ""
ONLINE_STYLE_CACHE = {}
ONLINE_STYLE_CACHE_LOCK = threading.Lock()
ONLINE_STYLE_LAST_REQUEST = {"musicbrainz": 0.0, "lastfm": 0.0, "discogs": 0.0}


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
    "russian": "rus",
    "рус": "rus",
}

ONLINE_BROAD_STYLE_NORMS = {
    "club",
    "dance",
    "electronic",
    "electronics",
    "electronica",
    "edm",
    "other",
}

ONLINE_STYLE_ALIASES = {
    "drum and bass": "Drum & Bass",
    "drum n bass": "Drum & Bass",
    "dnb": "Drum & Bass",
    "break beat": "Breakbeat",
    "breaks": "Breakbeat",
    "minimal techno": "Minimal / Deep Tech",
    "minimal deep tech": "Minimal / Deep Tech",
    "deep tech": "Minimal / Deep Tech",
    "techhouse": "Tech House",
    "nudisco": "Nu Disco",
    "synth pop": "Synth-pop",
    "trip hop": "Trip-Hop",
    "hiphop": "Hip Hop",
    "russian pop": "RusPop",
    "rus pop": "RusPop",
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


def _known_online_styles():
    styles = {}
    for _, labels in STYLE_GROUPS:
        for label in labels:
            norm = normalize_style(label)
            if norm in ONLINE_BROAD_STYLE_NORMS or norm == "rus":
                continue
            styles.setdefault(norm, label)
    for alias, label in ONLINE_STYLE_ALIASES.items():
        norm = normalize_style(alias)
        if normalize_style(label) not in ONLINE_BROAD_STYLE_NORMS:
            styles[norm] = label
    return styles


def _canonical_online_style(tag):
    raw = re.sub(r"\s+", " ", str(tag or "")).strip()
    if not raw:
        return ""
    alias = ONLINE_STYLE_ALIASES.get(raw.casefold())
    if alias:
        raw = alias
    known = _known_online_styles()
    norm = normalize_style(raw)
    if norm in ONLINE_BROAD_STYLE_NORMS:
        return ""
    if norm in known:
        return known[norm]
    return ""


def _http_json(url, source, min_interval=0.25, timeout=8):
    if source == "musicbrainz":
        min_interval = 1.05
    elif source == "discogs":
        min_interval = 1.0
    with ONLINE_STYLE_CACHE_LOCK:
        elapsed = time.monotonic() - ONLINE_STYLE_LAST_REQUEST.get(source, 0.0)
        wait = max(0.0, min_interval - elapsed)
    if wait:
        time.sleep(wait)
    req = Request(
        url,
        headers={
            "User-Agent": f"{APP_NAME}/{APP_VERSION} ({APP_REPOSITORY_URL})",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    with ONLINE_STYLE_CACHE_LOCK:
        ONLINE_STYLE_LAST_REQUEST[source] = time.monotonic()
    return data


def _clean_lookup_text(value):
    value = re.sub(r"\[[^\]]+\]|\([^\)]*(?:mix|remix|edit|version|radio|extended|original)[^\)]*\)", " ", str(value or ""), flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def _track_lookup_terms(track):
    artist = _clean_lookup_text(track.get("artist") or "")
    title = _clean_lookup_text(track.get("title") or "")
    if (not artist or not title) and track.get("label"):
        parts = re.split(r"\s+-\s+", str(track.get("label") or ""), maxsplit=1)
        if len(parts) == 2:
            artist = artist or _clean_lookup_text(parts[0])
            title = title or _clean_lookup_text(parts[1])
    if not title:
        title = _clean_lookup_text(Path(str(track.get("filename") or "")).stem)
    return artist, title


def _style_decision_from_tags(track, candidates, source):
    current_tags = split_genre_tags(track.get("genre") or "")
    existing_norms = {normalize_style(tag) for tag in current_tags}
    additions = []
    seen = set()
    source_tags = []
    for tag in candidates or []:
        name = tag.get("name") if isinstance(tag, dict) else str(tag or "")
        label = _canonical_online_style(name)
        if not label:
            continue
        norm = normalize_style(label)
        source_tags.append(name)
        if norm in existing_norms or norm in seen:
            continue
        additions.append(label)
        seen.add(norm)
    if not additions:
        return None
    confidence = "high" if len(additions) == 1 else "medium"
    return {
        "additions": additions[:4],
        "new_genre": join_genre_tags(current_tags + additions[:4]),
        "confidence": confidence,
        "reason": f"online source tags: {', '.join(source_tags[:6])}",
        "source": source,
    }


def _lastfm_style_details(track):
    if not LASTFM_API_KEY:
        return None
    artist, title = _track_lookup_terms(track)
    if not artist or not title:
        return None
    cache_key = ("lastfm", artist.casefold(), title.casefold())
    with ONLINE_STYLE_CACHE_LOCK:
        if cache_key in ONLINE_STYLE_CACHE:
            return ONLINE_STYLE_CACHE[cache_key]
    url = "https://ws.audioscrobbler.com/2.0/?" + urlencode({
        "method": "track.getInfo",
        "artist": artist,
        "track": title,
        "api_key": LASTFM_API_KEY,
        "format": "json",
        "autocorrect": "1",
    })
    try:
        data = _http_json(url, "lastfm")
        tags = (((data.get("track") or {}).get("toptags") or {}).get("tag") or [])
        result = _style_decision_from_tags(track, tags, "Last.fm")
    except Exception:
        result = None
    with ONLINE_STYLE_CACHE_LOCK:
        ONLINE_STYLE_CACHE[cache_key] = result
    return result


def _discogs_style_details(track):
    artist, title = _track_lookup_terms(track)
    if not artist or not title:
        return None
    cache_key = ("discogs", artist.casefold(), title.casefold())
    with ONLINE_STYLE_CACHE_LOCK:
        if cache_key in ONLINE_STYLE_CACHE:
            return ONLINE_STYLE_CACHE[cache_key]
    url = f"{DISCOGS_BASE_URL}/database/search?" + urlencode({
        "artist": artist,
        "track": title,
        "type": "release",
        "per_page": "5",
    })
    try:
        data = _http_json(url, "discogs")
        collected = []
        for item in data.get("results") or []:
            collected.extend(item.get("style") or [])
        if not collected:
            for item in data.get("results") or []:
                collected.extend(item.get("genre") or [])
        result = _style_decision_from_tags(track, [{"name": tag} for tag in collected], "Discogs")
    except Exception:
        result = None
    with ONLINE_STYLE_CACHE_LOCK:
        ONLINE_STYLE_CACHE[cache_key] = result
    return result


def _musicbrainz_style_details(track):
    artist, title = _track_lookup_terms(track)
    if not artist or not title:
        return None
    cache_key = ("musicbrainz", artist.casefold(), title.casefold())
    with ONLINE_STYLE_CACHE_LOCK:
        if cache_key in ONLINE_STYLE_CACHE:
            return ONLINE_STYLE_CACHE[cache_key]
    query = f'recording:"{title}" AND artist:"{artist}"'
    url = f"{MUSICBRAINZ_BASE_URL}/recording?fmt=json&limit=5&inc=genres+tags+releases&query={quote(query)}"
    try:
        data = _http_json(url, "musicbrainz")
        recordings = data.get("recordings") or []
        result = None
        release_group_ids = []
        for recording in recordings:
            tags = list(recording.get("genres") or []) + list(recording.get("tags") or [])
            result = _style_decision_from_tags(track, tags, "MusicBrainz")
            if result:
                break
            for release in recording.get("releases") or []:
                group = release.get("release-group") or {}
                secondary = {str(item).casefold() for item in group.get("secondary-types") or []}
                if "compilation" in secondary:
                    continue
                gid = group.get("id")
                if gid and gid not in release_group_ids:
                    release_group_ids.append(gid)
        if not result:
            for gid in release_group_ids[:4]:
                group_url = f"{MUSICBRAINZ_BASE_URL}/release-group/{quote(gid)}?fmt=json&inc=genres+tags"
                group_data = _http_json(group_url, "musicbrainz")
                tags = list(group_data.get("genres") or []) + list(group_data.get("tags") or [])
                result = _style_decision_from_tags(track, tags, "MusicBrainz")
                if result:
                    break
    except Exception:
        result = None
    with ONLINE_STYLE_CACHE_LOCK:
        ONLINE_STYLE_CACHE[cache_key] = result
    return result


def suggest_online_style_details(track):
    return _lastfm_style_details(track) or _discogs_style_details(track) or _musicbrainz_style_details(track)


def open_db():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def _decode_engine_zlib_blob(blob):
    if not blob:
        return None
    if len(blob) < 6:
        return None
    try:
        expected = struct.unpack(">I", blob[:4])[0]
        raw = zlib.decompress(blob[4:])
        if expected != len(raw):
            pass
        return raw
    except Exception:
        return None


def _parse_overview_waveform(raw):
    if not raw or len(raw) < 16:
        return None
    try:
        a, points, c, d = struct.unpack(">4I", raw[:16])
    except Exception:
        return None
    if not points or points > 8192:
        return None
    payload = raw[16:]
    need = points * 3
    if len(payload) < need:
        return None
    peaks = []
    r_vals = []
    g_vals = []
    b_vals = []
    for i in range(0, need, 3):
        r = payload[i]
        g = payload[i + 1]
        b = payload[i + 2]
        peaks.append(max(r, g, b))
        r_vals.append(r)
        g_vals.append(g)
        b_vals.append(b)
    avg = sum(peaks) / (len(peaks) * 255.0) if peaks else 0.0
    energy = max(0.05, min(0.98, float(avg ** 0.85)))
    return {
        "header": {"u32be_0": a, "points": points, "u32be_2": c, "u32be_3": d},
        "points": points,
        "peaks": peaks,
        "rgb": {"r": r_vals, "g": g_vals, "b": b_vals},
        "energy": round(energy, 4),
    }


def _energy_rating_from_energy(energy):
    try:
        value = float(energy)
    except Exception:
        return 0
    if value <= 0:
        return 0
    return max(1, min(5, int(value * 5 + 0.999)))


def _energy_from_overview_blob(blob):
    overview = _parse_overview_waveform(_decode_engine_zlib_blob(blob))
    if not overview:
        return None, 0
    energy = overview.get("energy")
    return energy, _energy_rating_from_energy(energy)


def _engine_rating_to_stars(raw_rating):
    try:
        raw = int(raw_rating or 0)
    except Exception:
        return 0
    if raw <= 0:
        return 0
    if raw < 20:
        return 0
    return max(1, min(5, int((raw + 10) / 20)))


def _stars_to_engine_rating(stars):
    try:
        value = int(stars or 0)
    except Exception:
        return 0
    return max(0, min(5, value)) * 20


def _row_value(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def _finite_number(value):
    try:
        return value is not None and not (value != value) and value not in (float("inf"), float("-inf"))
    except Exception:
        return False


def _extract_aligned_doubles(raw, *, offset=0, endian=">"):
    if not raw:
        return []
    data = bytes(raw)
    out = []
    fmt = f"{endian}d"
    for off in range(int(offset), max(0, len(data) - 7), 8):
        try:
            v = struct.unpack(fmt, data[off : off + 8])[0]
        except Exception:
            continue
        if not _finite_number(v):
            continue
        out.append(float(v))
    return out


def _best_time_scaler(values, track_len_s):
    # Pick scaler that yields most plausible timestamps in seconds.
    # Engine can store positions as seconds, ms, or sample frames (44100/48000).
    if not values:
        return None
    track_len_s = float(track_len_s or 0) or 0.0
    if track_len_s <= 0:
        return None
    candidates = [
        (1.0, "sec"),
        (1.0 / 1000.0, "ms"),
        (1.0 / 44100.0, "frames44100"),
        (1.0 / 48000.0, "frames48000"),
    ]
    best = None
    best_hits = -1
    for scale, _name in candidates:
        hits = 0
        for v in values:
            if not _finite_number(v):
                continue
            if v <= 0:
                continue
            t = v * scale
            if 0.05 <= t <= track_len_s * 1.05:
                hits += 1
        if hits > best_hits:
            best_hits = hits
            best = scale
    return best if best_hits > 0 else None


def _extract_positions_seconds(raw, track_len_s, *, endian=">", aligned_offset=8):
    values = _extract_aligned_doubles(raw, offset=aligned_offset, endian=endian)
    # Remove obvious sentinels/noise.
    cleaned = []
    for v in values:
        if abs(v - 0.0) < 1e-12:
            continue
        if abs(v + 1.0) < 1e-12:
            continue
        if abs(v - 1.0) < 1e-12:
            continue
        # Drop extreme garbage.
        if not _finite_number(v) or abs(v) > 1e12:
            continue
        cleaned.append(v)
    scale = _best_time_scaler(cleaned, track_len_s)
    if scale is None:
        return []
    out = set()
    for v in cleaned:
        t = v * scale
        if 0.05 <= t <= float(track_len_s) * 1.05:
            out.add(round(float(t), 3))
    return sorted(out)


def _parse_quick_cues(raw, track_len_s):
    # Observed format (zlib-decoded):
    # u64be slots (usually 8)
    # for each slot:
    #   u8 label_len
    #   label bytes (utf-8)
    #   f64be position (often stored as frames@44100/48000, sometimes seconds)
    #   u32be color/flags (optional but present in observed data)
    if not raw or len(raw) < 8:
        return []
    data = bytes(raw)
    try:
        slots = int(struct.unpack(">Q", data[:8])[0])
    except Exception:
        return []
    if slots <= 0 or slots > 16:
        return []
    off = 8
    items = []
    for slot in range(1, slots + 1):
        if off >= len(data):
            break
        label_len = data[off]
        off += 1
        if label_len:
            label = data[off : off + label_len].decode("utf-8", "replace")
            off += label_len
        else:
            label = ""
        if off + 8 > len(data):
            break
        try:
            pos = float(struct.unpack(">d", data[off : off + 8])[0])
        except Exception:
            break
        off += 8
        color = None
        if off + 4 <= len(data):
            try:
                color = int(struct.unpack(">I", data[off : off + 4])[0])
            except Exception:
                color = None
            off += 4
        items.append({"slot": slot, "label": label, "pos_raw": pos, "color": color})

    raw_positions = [i["pos_raw"] for i in items if _finite_number(i["pos_raw"]) and i["pos_raw"] > 0]
    scale = _best_time_scaler(raw_positions, track_len_s)
    if scale is None:
        return []
    cues = []
    for i in items:
        pos = i.get("pos_raw")
        if not _finite_number(pos) or pos is None:
            continue
        if abs(float(pos) + 1.0) < 1e-12:
            continue
        t = float(pos) * scale
        if t < 0.05 or t > float(track_len_s or 0) * 1.05:
            continue
        cues.append({
            "slot": int(i["slot"]),
            "label": str(i.get("label") or ""),
            "pos_s": round(t, 3),
            "color": i.get("color"),
        })
    return cues


def _has_any_quick_cue_blob(blob, track_len_s):
    raw = _decode_engine_zlib_blob(blob)
    cues = _parse_quick_cues(raw, track_len_s)
    return bool(cues)


def _loops_blob_has_any_loop(blob):
    loops = _parse_loops(blob, 0)
    return bool(loops)


def _parse_loops(blob, track_len_s):
    # Observed format (raw, not zlib):
    # u32le slots (usually 8)
    # u32le unknown (often 0)
    # for each slot:
    #   u8 label_len
    #   label bytes (utf-8)
    #   f64le start
    #   f64le end
    #   u8 enabled?
    #   u8 enabled2?
    #   u32be color
    if not blob or len(blob) < 8:
        return []
    data = bytes(blob)
    try:
        slots = int(struct.unpack("<I", data[:4])[0])
    except Exception:
        return []
    if slots <= 0 or slots > 16:
        return []
    off = 8
    items = []
    for slot in range(1, slots + 1):
        if off >= len(data):
            break
        label_len = data[off]
        off += 1
        if off + label_len > len(data):
            break
        label = data[off : off + label_len].decode("utf-8", "replace") if label_len else ""
        off += label_len
        if off + 16 > len(data):
            break
        start = float(struct.unpack("<d", data[off : off + 8])[0])
        end = float(struct.unpack("<d", data[off + 8 : off + 16])[0])
        off += 16
        if off + 6 > len(data):
            break
        en1 = int(data[off])
        en2 = int(data[off + 1])
        off += 2
        try:
            color = int(struct.unpack(">I", data[off : off + 4])[0])
        except Exception:
            color = None
        off += 4
        items.append({"slot": slot, "label": label, "start_raw": start, "end_raw": end, "en1": en1, "en2": en2, "color": color})

    raw_positions = []
    for i in items:
        for v in (i["start_raw"], i["end_raw"]):
            if _finite_number(v) and v > 0 and abs(v) < 1e12:
                raw_positions.append(v)
    scale = _best_time_scaler(raw_positions, track_len_s) if track_len_s else None
    if scale is None:
        # If we don't know track length, return only presence via raw sentinel checks.
        loops = []
        for i in items:
            s = i["start_raw"]
            e = i["end_raw"]
            if not _finite_number(s) or not _finite_number(e):
                continue
            if s <= 0 or e <= 0:
                continue
            if abs(s + 1.0) < 1e-12 or abs(e + 1.0) < 1e-12:
                continue
            loops.append({"slot": i["slot"], "label": i["label"], "color": i["color"]})
        return loops

    loops = []
    track_len = float(track_len_s or 0) or 0.0
    for i in items:
        s = i["start_raw"]
        e = i["end_raw"]
        if not _finite_number(s) or not _finite_number(e):
            continue
        if abs(s + 1.0) < 1e-12 or abs(e + 1.0) < 1e-12:
            continue
        if s <= 0 or e <= 0:
            continue
        start_s = float(s) * scale
        end_s = float(e) * scale
        if end_s < start_s:
            start_s, end_s = end_s, start_s
        if track_len:
            if end_s < 0.05 or start_s > track_len * 1.05:
                continue
            start_s = max(0.0, min(track_len, start_s))
            end_s = max(0.0, min(track_len, end_s))
        if end_s - start_s < 0.2:
            continue
        loops.append({
            "slot": int(i["slot"]),
            "label": str(i.get("label") or ""),
            "start_s": round(start_s, 3),
            "end_s": round(end_s, 3),
            "color": i.get("color"),
            "enabled": bool(i.get("en1") or i.get("en2")),
        })
    return loops


def _positions_to_markers(positions, *, kind, track_len_s):
    markers = []
    max_s = max(1.0, float(track_len_s or 0) or 0.0)
    for p in positions:
        if p <= 0.0 or p >= max_s + 5.0:
            continue
        frac = max(0.0, min(1.0, p / max_s))
        markers.append({"kind": kind, "pos_s": p, "pos_frac": round(frac, 6)})
    return markers


def _beat_grid_from_positions(positions):
    out = []
    for idx, pos in enumerate(sorted({round(float(p), 3) for p in positions if _finite_number(p) and p >= 0.0}), start=1):
        out.append({
            "time_sec": round(pos, 3),
            "beat": idx,
            "bar": int((idx - 1) // 4) + 1,
            "is_bar_start": ((idx - 1) % 4) == 0,
            "is_phrase_start": ((idx - 1) % 16) == 0,
        })
    return out


def _beat_grid_from_bpm(bpm, duration_sec, offset_sec=0.0):
    try:
        bpm = float(bpm or 0)
        duration_sec = float(duration_sec or 0)
        offset_sec = float(offset_sec or 0)
    except Exception:
        return []
    if bpm <= 0 or duration_sec <= 0:
        return []
    interval = 60.0 / bpm
    if interval <= 0:
        return []
    out = []
    beat = 1
    t = max(0.0, offset_sec)
    while t <= duration_sec + 0.001 and beat <= 20000:
        out.append({
            "time_sec": round(t, 3),
            "beat": beat,
            "bar": int((beat - 1) // 4) + 1,
            "is_bar_start": ((beat - 1) % 4) == 0,
            "is_phrase_start": ((beat - 1) % 16) == 0,
        })
        beat += 1
        t += interval
    return out


def _cue_color_hex(value):
    if value is None:
        return ""
    try:
        n = int(value) & 0xFFFFFF
        return f"#{n:06x}"
    except Exception:
        return ""


def engine_db_diagnostics(limit=2):
    limit = max(0, min(10, int(limit or 0)))
    out = {"ok": True, "db_path": str(DB_PATH), "tables": []}
    with open_db() as con:
        rows = con.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
        ).fetchall()
        for row in rows:
            name = row["name"]
            item = {
                "name": name,
                "type": row["type"],
                "columns": [dict(c) for c in con.execute(f"PRAGMA table_info({name})")],
                "samples": [],
            }
            if row["type"] == "table" and limit:
                try:
                    for sample in con.execute(f"SELECT * FROM {name} LIMIT ?", (limit,)):
                        item["samples"].append({
                            k: (f"BLOB {len(v)} bytes" if isinstance(v, bytes) else v)
                            for k, v in dict(sample).items()
                        })
                except Exception as exc:
                    item["sample_error"] = repr(exc)
            out["tables"].append(item)
    return out


def get_track_waveform_detail(track_id):
    track_id = int(track_id)
    checked = ["Track", "PerformanceData"]
    with open_db() as con:
        row = con.execute(
            """
            SELECT
              Track.id, Track.title, Track.artist, Track.filename, Track.length,
              Track.bpmAnalyzed, Track.bpm, Track.path,
              PerformanceData.overviewWaveFormData,
              PerformanceData.beatData,
              PerformanceData.quickCues,
              PerformanceData.loops
            FROM Track
            LEFT JOIN PerformanceData ON PerformanceData.trackId = Track.id
            WHERE Track.id = ?
            """,
            (track_id,),
        ).fetchone()
    if not row:
        raise ValueError("Track not found")

    duration_sec = int(row["length"] or 0)
    bpm = row["bpmAnalyzed"] if row["bpmAnalyzed"] is not None else row["bpm"]
    overview_raw = _decode_engine_zlib_blob(row["overviewWaveFormData"])
    overview = _parse_overview_waveform(overview_raw)
    beat_raw = _decode_engine_zlib_blob(row["beatData"])
    beat_positions = _extract_positions_seconds(beat_raw, duration_sec, endian=">", aligned_offset=8)
    beat_grid = _beat_grid_from_positions(beat_positions)
    beat_source = "engine_db" if beat_grid else "not_found"
    if len(beat_grid) < 4:
        beat_grid = _beat_grid_from_bpm(bpm, duration_sec, 0.0)
        beat_source = "bpm_fallback" if beat_grid else "not_found"

    qc_raw = _decode_engine_zlib_blob(row["quickCues"])
    cues_raw = _parse_quick_cues(qc_raw, duration_sec)
    cues = [{
        "time_sec": c["pos_s"],
        "name": c.get("label") or (f"Cue {c.get('slot')}" if c.get("slot") else "Cue"),
        "color": _cue_color_hex(c.get("color")),
        "type": "cue",
        "slot": c.get("slot"),
    } for c in cues_raw]
    loops_raw = _parse_loops(row["loops"], duration_sec)
    loops = [{
        "start_sec": l["start_s"],
        "end_sec": l["end_s"],
        "name": l.get("label") or (f"Loop {l.get('slot')}" if l.get("slot") else "Loop"),
        "type": "loop",
        "slot": l.get("slot"),
        "color": _cue_color_hex(l.get("color")),
    } for l in loops_raw if "start_s" in l and "end_s" in l]

    source = {
        "waveform": "engine_db" if overview else "not_found",
        "beat_grid": beat_source,
        "cues": "engine_db" if cues else "not_found",
        "loops": "engine_db" if loops else "not_found",
        "checked_tables": checked,
    }
    return {
        "ok": True,
        "track_id": track_id,
        "title": row["title"] or row["filename"] or "",
        "artist": row["artist"] or "",
        "filename": row["filename"] or "",
        "path": resolve_track_path(row["path"]),
        "duration_sec": duration_sec,
        "bpm": None if bpm is None else round(float(bpm), 3),
        # TODO: add optional backend cache for hi-res waveform:
        # set_app/cache/waveforms/<track_id>.json
        "waveform_resolution": "engine_overview_1024",
        "waveform": (overview or {}).get("peaks") or [],
        "waveform_rgb": (overview or {}).get("rgb") or None,
        "waveform_energy": (overview or {}).get("energy"),
        "beat_grid": beat_grid,
        "cues": cues,
        "loops": loops,
        "source": source,
        "diagnostics": {
            "performance_fields_present": {
                "overviewWaveFormData": row["overviewWaveFormData"] is not None,
                "beatData": row["beatData"] is not None,
                "quickCues": row["quickCues"] is not None,
                "loops": row["loops"] is not None,
            },
            "engine_beat_count": len(beat_positions),
            "checked_tables": checked,
        },
    }


def _suggest_percentile(values, pct, default=0.0):
    clean = sorted(float(v) for v in values if _finite_number(v))
    if not clean:
        return default
    if len(clean) == 1:
        return clean[0]
    pos = max(0.0, min(1.0, float(pct))) * (len(clean) - 1)
    lo = int(pos)
    hi = min(len(clean) - 1, lo + 1)
    frac = pos - lo
    return clean[lo] * (1.0 - frac) + clean[hi] * frac


def _suggest_beat_seconds(bpm, beat_grid):
    if bpm:
        try:
            bpm = float(bpm)
            if bpm > 0:
                return 60.0 / bpm
        except Exception:
            pass
    times = [float(b.get("time_sec")) for b in beat_grid or [] if _finite_number(b.get("time_sec"))]
    times = sorted(times)
    diffs = [b - a for a, b in zip(times, times[1:]) if 0.15 <= (b - a) <= 2.5]
    return _suggest_percentile(diffs, 0.5, 0.5)


def _suggest_snap_time(time_sec, beat_grid, bpm, duration_sec, unit_beats=16):
    duration = max(0.0, float(duration_sec or 0.0))
    time_sec = max(0.0, min(duration or 24 * 60 * 60, float(time_sec or 0.0)))
    unit = max(1, int(unit_beats or 1))
    candidates = []
    for idx, beat in enumerate(beat_grid or [], start=1):
        t = beat.get("time_sec")
        if not _finite_number(t):
            continue
        beat_no = beat.get("beat") or idx
        try:
            beat_no = int(beat_no)
        except Exception:
            beat_no = idx
        is_bar = bool(beat.get("is_bar_start")) or ((beat_no - 1) % 4 == 0)
        is_16 = bool(beat.get("is_phrase_start")) or ((beat_no - 1) % 16 == 0)
        is_32 = ((beat_no - 1) % 32 == 0)
        if unit >= 32 and is_32:
            candidates.append(float(t))
        elif unit >= 16 and is_16:
            candidates.append(float(t))
        elif unit >= 4 and is_bar:
            candidates.append(float(t))
        elif unit <= 1:
            candidates.append(float(t))
    if candidates:
        return round(max(0.0, min(duration or max(candidates), min(candidates, key=lambda v: abs(v - time_sec)))), 3)
    beat_sec = _suggest_beat_seconds(bpm, beat_grid)
    step = max(0.001, beat_sec * unit)
    return round(max(0.0, min(duration or time_sec, round(time_sec / step) * step)), 3)


def _suggest_energy_curve(detail):
    peaks = detail.get("waveform") or []
    duration = float(detail.get("duration_sec") or 0.0)
    if not isinstance(peaks, list) or len(peaks) < 8 or duration <= 0:
        return []
    values = []
    for value in peaks:
        try:
            values.append(max(0.0, min(1.0, float(value) / 255.0)))
        except Exception:
            values.append(0.0)
    radius = max(1, min(8, len(values) // 96))
    smoothed = []
    for i in range(len(values)):
        lo = max(0, i - radius)
        hi = min(len(values), i + radius + 1)
        smoothed.append(sum(values[lo:hi]) / max(1, hi - lo))
    return [(duration * (i / max(1, len(smoothed) - 1)), v) for i, v in enumerate(smoothed)]


def _suggest_first_stable_time(curve, duration_sec):
    if not curve:
        return max(0.0, min(float(duration_sec or 0), 16.0)), 0.35, "BPM fallback intro position"
    vals = [v for _t, v in curve]
    floor = _suggest_percentile(vals[: max(8, len(vals) // 12)], 0.35, 0.04)
    body = _suggest_percentile(vals, 0.68, 0.25)
    threshold = max(0.10, floor + 0.08, body * 0.48)
    need = max(3, len(vals) // 80)
    run = 0
    first = None
    for t, v in curve:
        if t < 2.0:
            continue
        if v >= threshold:
            run += 1
            if run >= need:
                first = t
                break
        else:
            run = 0
    if first is None:
        first = float(duration_sec or 0) * 0.08
        return first, 0.42, "fallback early phrase from track duration"
    confidence = 0.55 + min(0.28, max(0.0, body - floor) * 0.6)
    return first, confidence, "first stable energy section after intro"


def _suggest_last_energy_time(curve, duration_sec):
    duration = float(duration_sec or 0.0)
    if not curve:
        return max(0.0, duration * 0.82), 0.36, "BPM fallback outro region"
    vals = [v for _t, v in curve]
    threshold = max(0.09, _suggest_percentile(vals, 0.45, 0.18) * 0.55)
    last = None
    for t, v in reversed(curve):
        if t > duration - 2.0:
            continue
        if v >= threshold:
            last = t
            break
    if last is None:
        return max(0.0, duration * 0.82), 0.34, "fallback late phrase from track duration"
    return last, 0.58, "last usable energy before fade/end"


def _suggest_break_time(curve, duration_sec, mix_in_sec, mix_out_sec):
    if not curve:
        return None
    start = max(float(mix_in_sec or 0) + 16.0, float(duration_sec or 0) * 0.28)
    end = min(float(mix_out_sec or duration_sec), float(duration_sec or 0) * 0.78)
    candidates = [(t, v) for t, v in curve if start <= t <= end]
    if len(candidates) < 8:
        return None
    low = _suggest_percentile([v for _t, v in candidates], 0.24, 0.12)
    valleys = [(t, v) for t, v in candidates if v <= low]
    if not valleys:
        return None
    t, v = min(valleys, key=lambda item: item[1])
    return t, max(0.35, min(0.62, 0.62 - v * 0.35)), "low-energy break candidate in middle section"


def _suggest_track_marks_for_track(track_id):
    track_id = int(track_id)
    meta = _track_mark_meta(track_id)
    detail = get_track_waveform_detail(track_id)
    duration = float(detail.get("duration_sec") or 0.0)
    bpm = detail.get("bpm")
    beat_grid = detail.get("beat_grid") or []
    curve = _suggest_energy_curve(detail)
    warnings = []
    if duration <= 0:
        return {
            "ok": True,
            **meta,
            "track_id": track_id,
            "suggestions": {"marks": [], "loops": []},
            "warnings": ["Track duration is unavailable"],
            "confidence": 0.0,
        }
    if not curve:
        warnings.append("Waveform energy curve unavailable; using BPM/duration fallback")
    if not beat_grid:
        warnings.append("Beat-grid unavailable; using BPM fallback")

    beat_sec = _suggest_beat_seconds(bpm, beat_grid)
    phrase16 = beat_sec * 16.0
    phrase32 = beat_sec * 32.0
    marks = []

    raw_mix_in, mix_in_conf, mix_in_reason = _suggest_first_stable_time(curve, duration)
    mix_in = _suggest_snap_time(raw_mix_in, beat_grid, bpm, duration, 16)
    marks.append({
        "type": "MIX_IN",
        "name": _mark_label("MIX_IN"),
        "time_sec": mix_in,
        "raw_time_sec": round(raw_mix_in, 3),
        "confidence": round(max(0.0, min(1.0, mix_in_conf)), 3),
        "reason": f"{mix_in_reason}, snapped to 16 beats",
        "source": "auto",
    })

    last_energy, last_conf, last_reason = _suggest_last_energy_time(curve, duration)
    raw_mix_out = min(last_energy, max(mix_in + phrase32, duration - max(phrase32 * 2.0, 24.0)))
    raw_mix_out = max(mix_in + phrase16, raw_mix_out)
    mix_out = _suggest_snap_time(raw_mix_out, beat_grid, bpm, duration, 32)
    if mix_out >= duration - beat_sec:
        mix_out = _suggest_snap_time(max(mix_in + phrase32, duration - phrase32 * 2.0), beat_grid, bpm, duration, 32)
    marks.append({
        "type": "MIX_OUT",
        "name": _mark_label("MIX_OUT"),
        "time_sec": mix_out,
        "raw_time_sec": round(raw_mix_out, 3),
        "confidence": round(max(0.0, min(1.0, last_conf + 0.08)), 3),
        "reason": f"safe late phrase before outro/end, {last_reason}, snapped to 32 beats",
        "source": "auto",
    })

    raw_outro = max(mix_out, min(last_energy, duration - max(phrase16, 8.0)))
    outro = _suggest_snap_time(raw_outro, beat_grid, bpm, duration, 16)
    if outro < mix_out:
        outro = mix_out
    marks.append({
        "type": "OUTRO",
        "name": _mark_label("OUTRO"),
        "time_sec": outro,
        "raw_time_sec": round(raw_outro, 3),
        "confidence": round(max(0.0, min(1.0, last_conf)), 3),
        "reason": "late outro phrase near final usable energy, snapped to 16 beats",
        "source": "auto",
    })

    vocal_raw = mix_in + max(phrase16, 8.0)
    if vocal_raw < min(duration * 0.45, mix_out - phrase16):
        vocal = _suggest_snap_time(vocal_raw, beat_grid, bpm, duration, 16)
        marks.append({
            "type": "VOCAL_IN",
            "name": _mark_label("VOCAL_IN"),
            "time_sec": vocal,
            "raw_time_sec": round(vocal_raw, 3),
            "confidence": 0.45 if curve else 0.32,
            "reason": "optional early phrase after mix-in; verify vocal manually",
            "source": "auto",
        })

    break_candidate = _suggest_break_time(curve, duration, mix_in, mix_out)
    if break_candidate:
        break_raw, break_conf, break_reason = break_candidate
        break_time = _suggest_snap_time(break_raw, beat_grid, bpm, duration, 16)
        marks.append({
            "type": "BREAK",
            "name": _mark_label("BREAK"),
            "time_sec": break_time,
            "raw_time_sec": round(break_raw, 3),
            "confidence": round(break_conf, 3),
            "reason": f"{break_reason}, snapped to 16 beats",
            "source": "auto",
        })

    loops = []
    outro_len = 32 if outro + beat_sec * 32 <= duration else 16
    outro_start = _suggest_snap_time(outro, beat_grid, bpm, duration, 16)
    outro_end = min(duration, outro_start + beat_sec * outro_len)
    if outro_end > outro_start + beat_sec * 4:
        loops.append({
            "type": "OUTRO_LOOP",
            "name": f"Auto Outro Loop {outro_len}",
            "start_sec": round(outro_start, 3),
            "end_sec": round(outro_end, 3),
            "raw_start_sec": round(outro, 3),
            "length_beats": outro_len,
            "confidence": 0.62 if curve else 0.42,
            "reason": f"loop from outro phrase, {outro_len} beats",
            "source": "auto",
        })

    emergency_len = 16 if duration - mix_out >= beat_sec * 16 else 8
    emergency_raw = max(mix_out, min(last_energy - beat_sec * emergency_len, duration - beat_sec * emergency_len - beat_sec * 2))
    emergency_start = _suggest_snap_time(emergency_raw, beat_grid, bpm, duration, 4)
    emergency_end = min(duration, emergency_start + beat_sec * emergency_len)
    if emergency_end > emergency_start + beat_sec * 4:
        loops.append({
            "type": "EMERGENCY_LOOP",
            "name": f"Auto Emergency Loop {emergency_len}",
            "start_sec": round(emergency_start, 3),
            "end_sec": round(emergency_end, 3),
            "raw_start_sec": round(emergency_raw, 3),
            "length_beats": emergency_len,
            "confidence": 0.56 if curve else 0.38,
            "reason": f"late fallback loop before fade/end, {emergency_len} beats",
            "source": "auto",
        })

    confidence_values = [float(item.get("confidence", 0.0) or 0.0) for item in marks + loops]
    confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0
    return {
        "ok": True,
        **meta,
        "track_id": track_id,
        "suggestions": {"marks": marks, "loops": loops},
        "warnings": warnings,
        "confidence": confidence,
    }


def suggest_track_marks(data):
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    track_id = int(data.get("track_id") or 0)
    if track_id <= 0:
        raise ValueError("track_id is required")
    return _suggest_track_marks_for_track(track_id)


def batch_suggest_track_marks(data):
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    raw_ids = data.get("track_ids") or []
    if not isinstance(raw_ids, list):
        raise ValueError("track_ids must be an array")
    seen = set()
    track_ids = []
    warnings = []
    for value in raw_ids:
        try:
            track_id = int(value)
        except Exception:
            continue
        if track_id <= 0 or track_id in seen:
            continue
        seen.add(track_id)
        track_ids.append(track_id)
    if len(track_ids) > 100:
        warnings.append("Batch suggest limited to 100 tracks; extra tracks were skipped")
        track_ids = track_ids[:100]

    results = []
    for track_id in track_ids:
        try:
            results.append(_suggest_track_marks_for_track(track_id))
        except Exception as exc:
            try:
                meta = _track_mark_meta(track_id)
            except Exception:
                meta = {"track_id": track_id, "title": "", "artist": "", "filename": "", "file_path": "", "duration_sec": 0, "bpm": None}
            results.append({
                "ok": False,
                **meta,
                "track_id": track_id,
                "error": str(exc),
                "suggestions": {"marks": [], "loops": []},
                "warnings": [str(exc)],
                "confidence": 0.0,
            })
    return {"ok": True, "results": results, "warnings": warnings}

MANUAL_MARK_ORDER = ["MIX_IN", "VOCAL_IN", "DROP", "BREAK", "MIX_OUT", "OUTRO"]
MANUAL_MARK_TYPES = set(MANUAL_MARK_ORDER)
MANUAL_LOOP_TYPES = {"OUTRO_LOOP", "EMERGENCY_LOOP", "LOOP"}


def _track_mark_meta(track_id):
    track_id = int(track_id)
    with open_db() as con:
        row = con.execute(
            """
            SELECT id, title, artist, filename, length, bpmAnalyzed, bpm, path
            FROM Track
            WHERE id = ?
            """,
            (track_id,),
        ).fetchone()
    if not row:
        raise ValueError("Track not found")

    file_path = resolve_track_path(row["path"])
    file_size = None
    try:
        candidate = Path(file_path)
        if file_path and candidate.exists() and candidate.is_file():
            file_size = int(candidate.stat().st_size)
    except OSError:
        file_size = None
    bpm = row["bpmAnalyzed"] if row["bpmAnalyzed"] is not None else row["bpm"]
    return {
        "track_id": track_id,
        "title": row["title"] or row["filename"] or "",
        "artist": row["artist"] or "",
        "filename": row["filename"] or "",
        "file_path": file_path,
        "file_size": file_size,
        "duration_sec": int(row["length"] or 0),
        "bpm": None if bpm is None else round(float(bpm), 3),
    }


def _track_marks_file(meta):
    track_id = int(meta["track_id"])
    key_text = "|".join([
        str(track_id),
        str(meta.get("file_path") or "").casefold(),
        str(meta.get("file_size") or ""),
    ])
    digest = hashlib.sha1(key_text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return TRACK_MARKS_DIR / f"track_{track_id}_{digest}.json"


def _track_marks_default(meta):
    return {
        "track_id": int(meta["track_id"]),
        "file_path": meta.get("file_path") or "",
        "file_size": meta.get("file_size"),
        "duration_sec": int(meta.get("duration_sec") or 0),
        "bpm": meta.get("bpm"),
        "marks": [],
        "loops": [],
        "source": "manual",
        "confidence": 1.0,
    }


def _clamp_float(value, lo, hi, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    if not _finite_number(number):
        return default
    return max(lo, min(hi, number))


def _mark_label(mark_type):
    labels = {
        "MIX_IN": "MIX IN",
        "VOCAL_IN": "VOCAL",
        "DROP": "DROP",
        "BREAK": "BREAK",
        "MIX_OUT": "MIX OUT",
        "OUTRO": "OUTRO",
    }
    return labels.get(mark_type, mark_type.replace("_", " "))


def _sanitize_manual_marks(items, duration_sec):
    duration = max(0.0, float(duration_sec or 0))
    by_type = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        mark_type = str(item.get("type") or "").strip().upper()
        if mark_type not in MANUAL_MARK_TYPES:
            continue
        time_sec = _clamp_float(item.get("time_sec"), 0.0, duration or 24 * 60 * 60)
        raw_time = item.get("raw_time_sec")
        raw_time_sec = None
        if raw_time is not None:
            raw_time_sec = _clamp_float(raw_time, 0.0, duration or 24 * 60 * 60)
        by_type[mark_type] = {
            "id": mark_type.lower(),
            "type": mark_type,
            "name": str(item.get("name") or _mark_label(mark_type)).strip()[:48],
            "time_sec": round(time_sec, 3),
            "raw_time_sec": None if raw_time_sec is None else round(raw_time_sec, 3),
            "snap": str(item.get("snap") or "").strip()[:24],
            "source": "manual" if str(item.get("source") or "manual") != "auto" else "auto",
            "confidence": round(_clamp_float(item.get("confidence", 1.0), 0.0, 1.0, 1.0), 3),
        }
    return [by_type[key] for key in MANUAL_MARK_ORDER if key in by_type]


def _sanitize_manual_loops(items, duration_sec):
    duration = max(0.0, float(duration_sec or 0))
    out = []
    for idx, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            continue
        loop_type = str(item.get("type") or "OUTRO_LOOP").strip().upper()
        if loop_type not in MANUAL_LOOP_TYPES:
            loop_type = "OUTRO_LOOP"
        start_sec = _clamp_float(item.get("start_sec"), 0.0, duration or 24 * 60 * 60)
        end_sec = _clamp_float(item.get("end_sec"), 0.0, duration or 24 * 60 * 60)
        if end_sec <= start_sec:
            continue
        try:
            length_beats = int(item.get("length_beats") or 0)
        except Exception:
            length_beats = 0
        length_beats = max(0, min(512, length_beats))
        loop_id = str(item.get("id") or f"loop_{idx}_{length_beats or 'manual'}").strip()
        loop_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", loop_id)[:64] or f"loop_{idx}"
        payload = {
            "id": loop_id,
            "type": loop_type,
            "name": str(item.get("name") or (f"Loop {length_beats}" if length_beats else "Loop")).strip()[:48],
            "start_sec": round(start_sec, 3),
            "end_sec": round(end_sec, 3),
            "length_beats": length_beats,
            "snap": str(item.get("snap") or "").strip()[:24],
            "source": "manual" if str(item.get("source") or "manual") != "auto" else "auto",
            "confidence": round(_clamp_float(item.get("confidence", 1.0), 0.0, 1.0, 1.0), 3),
        }
        from_mark_type = str(item.get("from_mark_type") or "").strip().upper()
        if from_mark_type in MANUAL_MARK_TYPES:
            payload["from_mark_type"] = from_mark_type
        out.append(payload)
    return out


def get_track_marks(track_id):
    meta = _track_mark_meta(track_id)
    storage = _track_marks_file(meta)
    payload = _track_marks_default(meta)
    exists = storage.exists()
    if exists:
        try:
            raw = json.loads(storage.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload["marks"] = _sanitize_manual_marks(raw.get("marks") or [], payload["duration_sec"])
                payload["loops"] = _sanitize_manual_loops(raw.get("loops") or [], payload["duration_sec"])
                payload["source"] = "manual" if str(raw.get("source") or "manual") != "auto" else "auto"
                payload["confidence"] = round(_clamp_float(raw.get("confidence", 1.0), 0.0, 1.0, 1.0), 3)
                payload["saved_at"] = raw.get("saved_at")
        except Exception as exc:
            payload["warning"] = f"Could not read saved marks: {exc!r}"
    payload.update({
        "ok": True,
        "exists": exists,
        "storage_key": storage.stem,
    })
    return payload


def write_track_marks(data):
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    meta = _track_mark_meta(data.get("track_id"))
    payload = _track_marks_default(meta)
    duration = _clamp_float(data.get("duration_sec", payload["duration_sec"]), 0.0, 24 * 60 * 60, payload["duration_sec"])
    bpm = data.get("bpm", payload.get("bpm"))
    try:
        bpm_value = None if bpm in ("", None) else round(float(bpm), 3)
    except Exception:
        bpm_value = payload.get("bpm")
    payload.update({
        "duration_sec": round(duration, 3),
        "bpm": bpm_value,
        "marks": _sanitize_manual_marks(data.get("marks") or [], duration),
        "loops": _sanitize_manual_loops(data.get("loops") or [], duration),
        "source": "manual" if str(data.get("source") or "manual") != "auto" else "auto",
        "confidence": round(_clamp_float(data.get("confidence", 1.0), 0.0, 1.0, 1.0), 3),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    })
    storage = _track_marks_file(meta)
    TRACK_MARKS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = storage.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(storage)
    payload.update({
        "ok": True,
        "exists": True,
        "storage_key": storage.stem,
    })
    return payload


def delete_track_marks(track_id):
    meta = _track_mark_meta(track_id)
    storage = _track_marks_file(meta)
    deleted = False
    if storage.exists():
        storage.unlink()
        deleted = True
    payload = _track_marks_default(meta)
    payload.update({
        "ok": True,
        "exists": False,
        "deleted": deleted,
        "storage_key": storage.stem,
    })
    return payload


def _engine_backup_db():
    if not DB_PATH.exists():
        raise FileNotFoundError(str(DB_PATH))
    ENGINE_DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ENGINE_DB_BACKUP_DIR / f"{stamp}_m.db"
    counter = 1
    while backup.exists():
        backup = ENGINE_DB_BACKUP_DIR / f"{stamp}_{counter}_m.db"
        counter += 1
    shutil.copy2(DB_PATH, backup)
    return backup


def _engine_track_export_row(con, track_id):
    return con.execute(
        """
        SELECT
          Track.id,
          Track.lastEditTime,
          Track.path,
          Track.length,
          Track.bpmAnalyzed,
          Track.bpm,
          PerformanceData.trackId AS performance_track_id,
          PerformanceData.quickCues AS quickCues,
          PerformanceData.loops AS loops
        FROM Track
        LEFT JOIN PerformanceData ON PerformanceData.trackId = Track.id
        WHERE Track.id = ?
        """,
        (int(track_id),),
    ).fetchone()


def _engine_raw_time(time_sec):
    try:
        seconds = float(time_sec)
    except Exception:
        raise ValueError("Invalid cue/loop time")
    if not _finite_number(seconds) or seconds < 0:
        raise ValueError("Invalid cue/loop time")
    return seconds * ENGINE_CUE_TIME_SCALE


def _engine_export_color(existing_color, palette, slot):
    try:
        color = int(existing_color or 0)
    except Exception:
        color = 0
    return color or int(palette.get(int(slot), 0))


def _engine_existing_slot_conflict(kind, slot, existing):
    return {
        "type": kind,
        "slot": int(slot),
        "existing_label": getattr(existing, "label", "") or ("Loop" if kind == "loop" else f"Cue {slot}"),
    }


def _engine_loop_export_label(loop, loop_type, fixed_slot):
    if fixed_slot:
        return ENGINE_LOOP_TYPE_LABELS.get(loop_type, "LOOP")
    label = str(loop.get("name") or "").strip()
    return label[:48] or "MANUAL LOOP"


def _next_free_loop_slot(loops_blob, assigned_slots):
    for slot in range(1, int(loops_blob.slot_count) + 1):
        if slot in assigned_slots:
            continue
        if loops_blob.slot(slot).empty:
            return slot
    return None


def _build_engine_export_payload(marks_payload, row, overwrite_existing):
    marks = list(marks_payload.get("marks") or [])
    prep_loops = list(marks_payload.get("loops") or [])
    cues_blob = parse_quick_cues(row["quickCues"]) if row["quickCues"] else empty_quick_cues()
    loops_blob = parse_loops(row["loops"]) if row["loops"] else empty_loops()
    conflicts = []
    warnings = []
    exported_cues = []
    exported_loops = []
    cue_updates = []
    loop_updates = []

    for mark in marks:
        mark_type = str(mark.get("type") or "").strip().upper()
        slot = ENGINE_MARK_TO_CUE_SLOT.get(mark_type)
        if not slot:
            continue
        if slot > cues_blob.slot_count:
            warnings.append(f"Engine quickCues has no slot {slot} for {mark_type}")
            continue
        existing = cues_blob.slot(slot)
        if not existing.empty and not overwrite_existing:
            conflicts.append(_engine_existing_slot_conflict("cue", slot, existing))
            continue
        time_sec = _clamp_float(mark.get("time_sec"), 0.0, 24 * 60 * 60, 0.0)
        raw = _engine_raw_time(time_sec)
        label = ENGINE_CUE_SLOT_LABELS.get(mark_type, mark_type.replace("_", " "))
        cue_updates.append({
            "type": mark_type,
            "slot": slot,
            "label": label,
            "time_sec": round(time_sec, 3),
            "pos_raw": raw,
            "color": _engine_export_color(existing.color, ENGINE_CUE_SLOT_COLORS, slot),
        })

    fixed_loop_types = set()
    assigned_loop_slots = set()
    for loop in prep_loops:
        loop_type = str(loop.get("type") or "LOOP").strip().upper()
        fixed_slot = None
        if loop_type in ENGINE_LOOP_TYPE_TO_SLOT and loop_type not in fixed_loop_types:
            fixed_slot = ENGINE_LOOP_TYPE_TO_SLOT[loop_type]
            fixed_loop_types.add(loop_type)
        if fixed_slot:
            if fixed_slot > loops_blob.slot_count:
                warnings.append(f"Engine loops has no slot {fixed_slot} for {loop_type}")
                continue
            slot = fixed_slot
            assigned_loop_slots.add(slot)
            existing = loops_blob.slot(slot)
            if not existing.empty and not overwrite_existing:
                conflicts.append(_engine_existing_slot_conflict("loop", slot, existing))
                continue
        else:
            slot = _next_free_loop_slot(loops_blob, assigned_loop_slots)
            if slot is None:
                warnings.append("No free Engine loop slots for manual loop")
                continue
            assigned_loop_slots.add(slot)
            existing = loops_blob.slot(slot)
        start_sec = _clamp_float(loop.get("start_sec"), 0.0, 24 * 60 * 60, 0.0)
        end_sec = _clamp_float(loop.get("end_sec"), 0.0, 24 * 60 * 60, 0.0)
        if end_sec <= start_sec:
            warnings.append(f"Skipped invalid loop at {start_sec:.3f}s")
            continue
        label = _engine_loop_export_label(loop, loop_type, fixed_slot)
        loop_updates.append({
            "type": loop_type,
            "slot": slot,
            "label": label,
            "start_sec": round(start_sec, 3),
            "end_sec": round(end_sec, 3),
            "start_raw": _engine_raw_time(start_sec),
            "end_raw": _engine_raw_time(end_sec),
            "color": _engine_export_color(existing.color, ENGINE_LOOP_SLOT_COLORS, slot),
            "fixed_slot": bool(fixed_slot),
        })

    if conflicts:
        return {
            "ok": False,
            "reason": "conflict",
            "conflicts": conflicts,
            "warnings": warnings,
        }

    next_cues = cues_blob
    for update in cue_updates:
        next_cues = next_cues.with_slot(
            update["slot"],
            label=update["label"],
            pos_raw=update["pos_raw"],
            color=update["color"],
        )
        exported_cues.append({key: update[key] for key in ("type", "slot", "label", "time_sec", "pos_raw")})

    next_loops = loops_blob
    for update in loop_updates:
        next_loops = next_loops.with_slot(
            update["slot"],
            label=update["label"],
            start_raw=update["start_raw"],
            end_raw=update["end_raw"],
            color=update["color"],
            enabled_1=1,
            enabled_2=1,
        )
        exported_loops.append({key: update[key] for key in ("type", "slot", "label", "start_sec", "end_sec", "start_raw", "end_raw")})

    return {
        "ok": True,
        "quickCues": build_quick_cues(next_cues) if exported_cues else row["quickCues"],
        "loops": build_loops(next_loops) if exported_loops else row["loops"],
        "exported_cues": exported_cues,
        "exported_loops": exported_loops,
        "conflicts": [],
        "warnings": warnings,
    }


def export_track_marks_to_engine(data):
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    if not DB_PATH.exists():
        return {"ok": False, "reason": "missing_db", "db_path": str(DB_PATH)}
    try:
        track_id = int(data.get("track_id"))
    except Exception:
        return {"ok": False, "reason": "missing_track_id"}
    overwrite_existing = data.get("overwrite_existing") is True

    try:
        marks_payload = get_track_marks(track_id)
    except ValueError as exc:
        return {"ok": False, "reason": "missing_track", "error": str(exc)}
    if not marks_payload.get("exists"):
        return {"ok": False, "reason": "missing_track_marks", "track_id": track_id}
    if not (marks_payload.get("marks") or marks_payload.get("loops")):
        return {"ok": False, "reason": "empty_track_marks", "track_id": track_id}

    try:
        with sqlite3.connect(str(DB_PATH), timeout=1.0) as con:
            con.row_factory = sqlite3.Row
            row = _engine_track_export_row(con, track_id)
            if not row:
                return {"ok": False, "reason": "missing_track", "track_id": track_id}
            if row["performance_track_id"] is None:
                return {"ok": False, "reason": "missing_performance_data", "track_id": track_id}
            plan = _build_engine_export_payload(marks_payload, row, overwrite_existing)
    except sqlite3.OperationalError as exc:
        reason = "db_locked" if "locked" in str(exc).lower() else "db_error"
        return {"ok": False, "reason": reason, "error": str(exc), "db_path": str(DB_PATH)}
    except Exception as exc:
        return {"ok": False, "reason": "codec_error", "error": str(exc)}

    if not plan.get("ok"):
        return plan
    if not (plan.get("exported_cues") or plan.get("exported_loops")):
        return {"ok": False, "reason": "nothing_to_export", "warnings": plan.get("warnings") or []}

    try:
        backup = _engine_backup_db()
    except Exception as exc:
        return {"ok": False, "reason": "backup_failed", "error": str(exc)}

    con = None
    try:
        con = sqlite3.connect(str(DB_PATH), timeout=1.0)
        con.row_factory = sqlite3.Row
        con.execute("BEGIN IMMEDIATE")
        row = _engine_track_export_row(con, track_id)
        if not row:
            con.rollback()
            return {"ok": False, "reason": "missing_track", "track_id": track_id, "backup_path": str(backup)}
        if row["performance_track_id"] is None:
            con.rollback()
            return {"ok": False, "reason": "missing_performance_data", "track_id": track_id, "backup_path": str(backup)}
        plan = _build_engine_export_payload(marks_payload, row, overwrite_existing)
        if not plan.get("ok"):
            con.rollback()
            plan["backup_path"] = str(backup)
            return plan
        con.execute(
            "UPDATE PerformanceData SET quickCues = ?, loops = ? WHERE trackId = ?",
            (plan["quickCues"], plan["loops"], track_id),
        )
        con.execute("UPDATE Track SET lastEditTime = ? WHERE id = ?", (_engine_now_str(), track_id))
        con.commit()
    except sqlite3.OperationalError as exc:
        if con:
            con.rollback()
        reason = "db_locked" if "locked" in str(exc).lower() else "db_error"
        return {"ok": False, "reason": reason, "error": str(exc), "backup_path": str(backup), "db_path": str(DB_PATH)}
    except Exception as exc:
        if con:
            con.rollback()
        return {"ok": False, "reason": "export_failed", "error": str(exc), "backup_path": str(backup)}
    finally:
        if con:
            con.close()

    return {
        "ok": True,
        "backup_path": str(backup),
        "exported_cues": plan.get("exported_cues") or [],
        "exported_loops": plan.get("exported_loops") or [],
        "conflicts": [],
        "warnings": plan.get("warnings") or [],
    }

def get_track_performance(track_id):
    track_id = int(track_id)
    with open_db() as con:
        trow = con.execute("SELECT length FROM Track WHERE id=?", (track_id,)).fetchone()
        row = con.execute(
            "SELECT overviewWaveFormData, beatData, quickCues, loops FROM PerformanceData WHERE trackId=?",
            (track_id,),
        ).fetchone()
        if not row:
            raise ValueError("PerformanceData not found for track")
    track_len = 0 if not trow else int(trow["length"] or 0)
    overview_raw = _decode_engine_zlib_blob(row["overviewWaveFormData"])
    overview = _parse_overview_waveform(overview_raw)

    markers = []
    qc_raw = _decode_engine_zlib_blob(row["quickCues"])
    bd_raw = _decode_engine_zlib_blob(row["beatData"])
    lp_raw = row["loops"]

    # These formats are not publicly documented; we use robust heuristics:
    # - quickCues/beatData: aligned big-endian doubles after an 8-byte count.
    # - loops: scan both endians but still aligned.
    cues = _parse_quick_cues(qc_raw, track_len)
    loops = _parse_loops(lp_raw, track_len)
    qc_pos = sorted({c["pos_s"] for c in cues})
    bd_pos = _extract_positions_seconds(bd_raw, track_len, endian=">", aligned_offset=8)

    markers.extend(_positions_to_markers(qc_pos, kind="cue", track_len_s=track_len))
    markers.extend(_positions_to_markers(bd_pos, kind="beat", track_len_s=track_len))
    markers.sort(key=lambda m: (m["pos_s"], m["kind"]))
    return {
        "ok": True,
        "track_id": track_id,
        "track_length_s": track_len,
        "overview": overview,
        "cues": cues,
        "loops": loops,
        "has_cue": bool(cues),
        "has_loop": bool(loops),
        "markers": markers[:200],
        "present": {
            "overviewWaveFormData": row["overviewWaveFormData"] is not None,
            "beatData": row["beatData"] is not None,
            "quickCues": row["quickCues"] is not None,
            "loops": row["loops"] is not None,
        },
    }


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
    has_cue = False
    has_loop = False
    try:
        has_cue = bool(row["has_cue"])  # sqlite returns 0/1
    except Exception:
        has_cue = False
    try:
        has_loop = bool(row["has_loop"])
    except Exception:
        has_loop = False
    energy = _row_value(row, "energy", None)
    energy_rating = _row_value(row, "energy_rating", 0)
    if not energy_rating:
        energy, energy_rating = _energy_from_overview_blob(_row_value(row, "overviewWaveFormData"))
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
        "rating": _engine_rating_to_stars(_row_value(row, "rating", 0)),
        "rating_raw": int(_row_value(row, "rating", 0) or 0),
        "energy": energy,
        "energy_rating": int(energy_rating or 0),
        "length": row["length"] or 0,
        "path": path,
        "rel": rel_to_music(path) if path else "",
        "has_cue": has_cue,
        "has_loop": has_loop,
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
    if is_hidden_or_system_path(candidate):
        raise ValueError("Hidden/system media files are ignored")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError("Media file does not exist")
    return candidate


def load_track_maps():
    by_path = {}
    by_name = {}
    sql = """
        SELECT
          Track.id,
          Track.filename,
          Track.length,
          Track.bitrate,
          Track.bpmAnalyzed,
          Track.key,
          Track.rating,
          Track.genre,
          Track.artist,
          Track.title,
          Track.path,
          PerformanceData.quickCues AS quickCues,
          PerformanceData.loops AS loops
        FROM Track
        LEFT JOIN PerformanceData ON PerformanceData.trackId = Track.id
        WHERE Track.isAvailable = 1
          AND Track.path IS NOT NULL
    """
    with open_db() as con:
        for row in con.execute(sql):
            payload = dict(row)
            payload["has_cue"] = _has_any_quick_cue_blob(payload.get("quickCues"), payload.get("length") or 0)
            payload["has_loop"] = _loops_blob_has_any_loop(payload.get("loops"))
            track = row_to_track(payload)
            if track["path"] and is_hidden_or_system_path(track["path"]):
                continue
            if track["path"]:
                by_path[norm_abs(track["path"])] = track
            by_name.setdefault((track["filename"] or "").casefold(), []).append(track)
    unique_name = {name: rows[0] for name, rows in by_name.items() if name and len(rows) == 1}
    return by_path, unique_name


def _chunks(items, size):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _engine_path_candidates(path):
    candidates = []
    try:
        resolved = Path(path).resolve()
    except Exception:
        resolved = Path(path)
    for value in (str(resolved), resolved.as_posix()):
        if value and value not in candidates:
            candidates.append(value)
    try:
        rel = resolved.relative_to(MUSIC_ROOT.resolve()).as_posix()
        for value in (
            f"../Music/{rel}",
            f"Music/{rel}",
            f"G:/Music/{rel}",
            str(PureWindowsPath("G:/Music") / PureWindowsPath(rel)),
        ):
            if value and value not in candidates:
                candidates.append(value)
    except Exception:
        pass
    return candidates


def load_track_maps_for_files(paths):
    paths = [Path(path) for path in paths]
    if not paths:
        return {}, {}

    by_path = {}
    by_name = {}
    wanted_paths = []
    wanted_names = []
    for path in paths:
        wanted_names.append(path.name)
        wanted_paths.extend(_engine_path_candidates(path))

    sql_base = """
        SELECT
          Track.id,
          Track.filename,
          Track.length,
          Track.bitrate,
          Track.bpmAnalyzed,
          Track.key,
          Track.rating,
          Track.genre,
          Track.artist,
          Track.title,
          Track.path,
          PerformanceData.quickCues AS quickCues,
          PerformanceData.loops AS loops
        FROM Track
        LEFT JOIN PerformanceData ON PerformanceData.trackId = Track.id
        WHERE Track.isAvailable = 1
          AND Track.path IS NOT NULL
          AND ({predicate})
    """

    seen_ids = set()
    with open_db() as con:
        for chunk in _chunks(sorted(set(wanted_paths)), 400):
            placeholders = ",".join("?" for _ in chunk)
            sql = sql_base.format(predicate=f"Track.path IN ({placeholders})")
            for row in con.execute(sql, chunk):
                if int(row["id"]) in seen_ids:
                    continue
                seen_ids.add(int(row["id"]))
                payload = dict(row)
                payload["has_cue"] = _has_any_quick_cue_blob(payload.get("quickCues"), payload.get("length") or 0)
                payload["has_loop"] = _loops_blob_has_any_loop(payload.get("loops"))
                track = row_to_track(payload)
                if track["path"] and is_hidden_or_system_path(track["path"]):
                    continue
                if track["path"]:
                    by_path[norm_abs(track["path"])] = track
                by_name.setdefault((track["filename"] or "").casefold(), []).append(track)

        missing_names = [
            path.name
            for path in paths
            if norm_abs(path) not in by_path
        ]
        for chunk in _chunks(sorted(set(missing_names)), 400):
            placeholders = ",".join("?" for _ in chunk)
            sql = sql_base.format(predicate=f"Track.filename IN ({placeholders})")
            for row in con.execute(sql, chunk):
                if int(row["id"]) in seen_ids:
                    continue
                seen_ids.add(int(row["id"]))
                payload = dict(row)
                payload["has_cue"] = _has_any_quick_cue_blob(payload.get("quickCues"), payload.get("length") or 0)
                payload["has_loop"] = _loops_blob_has_any_loop(payload.get("loops"))
                track = row_to_track(payload)
                if track["path"] and is_hidden_or_system_path(track["path"]):
                    continue
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
        "rating": 0,
        "energy": None,
        "energy_rating": 0,
        "length": 0,
        "path": str(path),
        "has_cue": False,
        "has_loop": False,
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


def attach_energy(tracks):
    ids = [int(t["id"]) for t in tracks if t.get("id")]
    if not ids:
        return tracks
    placeholders = ",".join("?" for _ in ids)
    with open_db() as con:
        rows = con.execute(
            f"SELECT trackId, overviewWaveFormData FROM PerformanceData WHERE trackId IN ({placeholders})",
            ids,
        ).fetchall()
    by_id = {}
    for row in rows:
        by_id[int(row["trackId"])] = _energy_from_overview_blob(row["overviewWaveFormData"])
    for track in tracks:
        pair = by_id.get(int(track["id"] or 0))
        if pair:
            track["energy"], track["energy_rating"] = pair
    return tracks


def browse_music(rel):
    current = safe_music_path(rel)
    if not current.exists() or not current.is_dir():
        raise ValueError("Folder does not exist")
    dirs = []
    audio_files = []
    try:
        children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
    except OSError:
        children = []
    for child in children:
        if is_hidden_or_system_path(child):
            continue
        if child.is_dir():
            dirs.append({"name": child.name, "rel": rel_to_music(child)})
        elif is_audio_file(child):
            audio_files.append(child)
    by_path, unique_name = load_track_maps_for_files(audio_files)
    tracks = []
    for child in audio_files:
        tr = track_for_file(child, by_path, unique_name)
        tr["rel"] = rel_to_music(child)
        tr["source"] = "engine" if tr.get("id") else "file"
        tracks.append(tr)
    attach_energy(tracks)
    parent = ""
    if current.resolve() != MUSIC_ROOT.resolve():
        parent = rel_to_music(current.parent)
    return {"rel": rel_to_music(current), "parent": parent, "dirs": dirs, "tracks": tracks}


def search_tracks(query, limit):
    terms = [t.casefold() for t in re.split(r"\s+", query or "") if t.strip()]
    sql = """
        SELECT
          Track.id,
          Track.filename,
          Track.length,
          Track.bitrate,
          Track.bpmAnalyzed,
          Track.key,
          Track.rating,
          Track.genre,
          Track.artist,
          Track.title,
          Track.path,
          PerformanceData.quickCues AS quickCues,
          PerformanceData.loops AS loops
        FROM Track
        LEFT JOIN PerformanceData ON PerformanceData.trackId = Track.id
        WHERE Track.isAvailable = 1
          AND Track.bpmAnalyzed IS NOT NULL
          AND Track.key IS NOT NULL
          AND Track.length IS NOT NULL
          AND Track.length BETWEEN 75 AND 720
          AND Track.path IS NOT NULL
        ORDER BY Track.artist, Track.title, Track.filename
    """
    out = []
    with open_db() as con:
        for row in con.execute(sql):
            p = resolve_track_path(row["path"]).replace("\\", "/").casefold()
            if is_hidden_or_system_path(resolve_track_path(row["path"])):
                continue
            if "/music/set/" in p or "/music/sets/" in p:
                continue
            haystack = " ".join([
                row["artist"] or "", row["title"] or "", row["filename"] or "", row["genre"] or "", p
            ]).casefold()
            if terms and not all(t in haystack for t in terms):
                continue
            payload = dict(row)
            payload["has_cue"] = _has_any_quick_cue_blob(payload.get("quickCues"), payload.get("length") or 0)
            payload["has_loop"] = _loops_blob_has_any_loop(payload.get("loops"))
            out.append(row_to_track(payload))
            if len(out) >= limit:
                break
    return attach_energy(out)


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
            if data["count"] > 0 or label in {"Rus", "House", "Electronic", "Dance", "Techno", "Drum & Bass", "Pop", "Rock"}:
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
    rus = counts.get("rus", {"label": "Rus", "count": 0})
    groups.append({
        "name": "Допуск русских треков",
        "styles": [{
            "value": "rus",
            "label": "Rus (допуск)",
            "count": rus["count"],
            "title": RUS_ALLOW_DESCRIPTION,
        }],
    })
    return groups


def genre_options():
    seen = {}
    for group in style_groups():
        for style in group["styles"]:
            seen.setdefault(style["label"].casefold(), style["label"])
    return sorted(seen.values(), key=lambda s: s.casefold())


def split_genre_tags(value):
    tags = []
    for part in re.split(r"[,;/|<>]+", str(value or "")):
        tag = re.sub(r"\s+", " ", part).strip()
        if tag:
            tags.append(tag)
    return tags


def join_genre_tags(tags):
    out = []
    seen = set()
    for tag in tags or []:
        clean = re.sub(r"\s+", " ", str(tag or "")).strip()
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return ", ".join(out)


def _normalize_genre_value(value):
    genre = join_genre_tags(split_genre_tags(value))
    if not genre:
        raise ValueError("Genre is empty")
    return genre


def _track_file_tag_result(path, genre=None, bpm=None, key=None, rating=None):
    key_text = None
    if key is not None and str(key).strip():
        try:
            key_text = engine_key_to_camelot(int(key))
        except Exception:
            key_text = str(key).strip()
    rating_stars = None
    try:
        rating_stars = _engine_rating_to_stars(rating)
    except Exception:
        rating_stars = None
    result = write_audio_tags(
        path,
        genre=genre,
        bpm=bpm,
        key=key_text,
        autoset_styles=genre,
        rating=rating_stars,
    ).as_dict()
    return result


def _file_tag_summary(result):
    result = result or {}
    warning = result.get("file_tags_warning")
    return {
        "file_tags_updated": bool(result.get("file_tags_updated")) or (bool(result.get("ok")) and not warning),
        "file_tags_warning": warning,
        "written_fields": result.get("written_fields") or [],
    }


def update_genre(track_id, genre):
    genre = _normalize_genre_value(genre)
    with open_db() as con:
        row = con.execute(
            "SELECT id, filename, length, bitrate, bpmAnalyzed, key, rating, genre, artist, title, path FROM Track WHERE id = ?",
            (int(track_id),),
        ).fetchone()
        if not row:
            raise ValueError("Track not found")
        con.execute("UPDATE Track SET genre = ?, lastEditTime = ? WHERE id = ?", (genre, _engine_now_str(), int(track_id)))
        con.commit()
    track = row_to_track(row)
    path = safe_media_path(track["rel"] or track["path"])
    file_result = _track_file_tag_result(
        path,
        genre=genre,
        bpm=row["bpmAnalyzed"],
        key=row["key"],
        rating=_row_value(row, "rating", 0),
    )
    track["genre"] = genre
    summary = _file_tag_summary(file_result)
    return {
        "ok": True,
        "track": track,
        "engine_db_updated": True,
        **summary,
        "file_tag_result": file_result,
    }


def _genre_after_bulk_action(current, action, tag, find, replace):
    current_tags = split_genre_tags(current)
    if action == "append":
        additions = split_genre_tags(tag)
        if not additions:
            raise ValueError("Tag is empty")
        return join_genre_tags(current_tags + additions)
    if action in {"replace", "remove"}:
        needles = {t.casefold() for t in split_genre_tags(find)}
        if not needles:
            raise ValueError("Find tag is empty")
        replacement = split_genre_tags(replace)
        out = []
        changed = False
        for item in current_tags:
            if item.casefold() in needles:
                changed = True
                if action == "replace":
                    out.extend(replacement)
            else:
                out.append(item)
        return join_genre_tags(out), changed
    raise ValueError("Unknown bulk genre action")


def _text_has_any(text, needles):
    text = text.casefold()
    return any(needle.casefold() in text for needle in needles)


def _track_style_text(track, path):
    return " ".join([
        str(track.get("genre") or ""),
        str(track.get("artist") or ""),
        str(track.get("title") or ""),
        str(track.get("filename") or ""),
        str(track.get("label") or ""),
    ]).casefold()


def _append_style(out, existing_norms, label):
    if normalize_style(label) not in existing_norms and label not in out:
        out.append(label)


def suggest_style_details(track, path):
    current_tags = split_genre_tags(track.get("genre") or "")
    existing_norms = {normalize_style(tag) for tag in current_tags}
    text = _track_style_text(track, path)
    additions = []
    confidence = "low"
    reasons = []

    def add(labels, level, reason):
        nonlocal confidence
        for label in labels:
            _append_style(additions, existing_norms, label)
        if DETAIL_CONFIDENCE_ORDER[level] > DETAIL_CONFIDENCE_ORDER[confidence]:
            confidence = level
        reasons.append(reason)

    if _text_has_any(text, ["tech house", "techhouse"]):
        add(["House", "Tech House"], "high", "найден Tech House")
    elif _text_has_any(text, ["deep house"]):
        add(["House", "Deep House"], "high", "найден Deep House")
    elif _text_has_any(text, ["afro house"]):
        add(["House", "Afro House"], "high", "найден Afro House")
    elif _text_has_any(text, ["progressive house"]):
        add(["House", "Progressive House"], "high", "найден Progressive House")
    elif _text_has_any(text, ["disco house"]):
        add(["House", "Disco House"], "high", "найден Disco House")
    elif _text_has_any(text, ["funky house", "jackin house", "club house", "chill house"]):
        if "funky house" in text:
            add(["House", "Funky House"], "high", "найден Funky House")
        if "jackin house" in text:
            add(["House", "Jackin House"], "high", "найден Jackin House")
        if "club house" in text:
            add(["House", "Club House"], "medium", "найден Club House")
        if "chill house" in text:
            add(["House", "Chill House"], "medium", "найден Chill House")
    elif _text_has_any(text, ["house"]) and normalize_style("Club") in existing_norms:
        add(["House"], "medium", "Club уточнен как House")

    if _text_has_any(text, ["melodic techno"]):
        add(["Techno", "Melodic Techno"], "high", "найден Melodic Techno")
    elif _text_has_any(text, ["minimal techno", "minimal/deep tech", "minimal deep tech", "deep tech"]):
        add(["Techno", "Minimal / Deep Tech"], "high", "найден Minimal / Deep Tech")
    elif _text_has_any(text, ["techno"]):
        add(["Techno"], "medium", "найден Techno")

    if _text_has_any(text, ["drum & bass", "drum and bass", "dnb"]):
        add(["Drum & Bass"], "high", "найден Drum & Bass")
    if _text_has_any(text, ["uk garage"]):
        add(["Garage", "UK Garage"], "high", "найден UK Garage")
    elif _text_has_any(text, ["garage"]) and (track.get("bpm") or 0) >= 126:
        add(["Garage"], "medium", "найден Garage при клубном BPM")
    if _text_has_any(text, ["breakbeat", "break beat"]):
        add(["Breakbeat"], "high", "найден Breakbeat")
    if _text_has_any(text, ["trance"]):
        add(["Trance"], "high", "найден Trance")
    if _text_has_any(text, ["nu disco", "nudisco"]):
        add(["Nu Disco"], "high", "найден Nu Disco")
    if _text_has_any(text, ["indie dance"]):
        add(["Indie Dance"], "high", "найден Indie Dance")

    return {
        "additions": additions,
        "new_genre": join_genre_tags(current_tags + additions),
        "confidence": confidence,
        "reason": "; ".join(dict.fromkeys(reasons)) or "нет уверенного подстиля",
    }


def _audio_files_for_genre_bulk(rel, recursive):
    target = safe_music_path(rel)
    if not target.exists() or not target.is_dir():
        raise ValueError("Folder does not exist")
    iterator = target.rglob("*") if bool(recursive) else target.iterdir()
    return sorted([
        path
        for path in iterator
        if is_audio_file(path)
    ], key=lambda p: str(p).casefold())


def detail_folder_styles(rel, recursive=False, apply=False, min_confidence="medium", selected_files=None, source="online"):
    target = safe_music_path(rel)
    if _is_protected_set_path(target):
        raise ValueError("Set/Sets folders are protected from style updates")
    if not target.exists() or not target.is_dir():
        raise ValueError("Folder does not exist")
    min_confidence = min_confidence if min_confidence in DETAIL_CONFIDENCE_ORDER else "medium"
    files = _audio_files_for_genre_bulk(rel, recursive)
    if selected_files:
        selected = {str(item).lower() for item in selected_files if item}
        files = [path for path in files if str(path).lower() in selected]
    total_files = len(files)
    by_path, unique_name = load_track_maps_for_files(files)
    now = _engine_now_str()
    suggestions = []
    missing = []
    eligible = 0
    updated = 0
    unchanged = 0
    skipped_confidence = 0
    file_written = 0
    file_failed = 0
    file_warnings = []

    with open_db() as con:
        for path in files:
            track = track_for_file(path, by_path, unique_name)
            if not track.get("id"):
                missing.append(str(path))
                continue
            if source == "local":
                decision = suggest_style_details(track, path)
                decision["source"] = "AutoSet local"
            else:
                decision = suggest_online_style_details(track) or {
                    "additions": [],
                    "new_genre": track.get("genre") or "",
                    "confidence": "low",
                    "reason": "online sources did not return a known AutoSet style",
                    "source": "Online",
                }
            if not decision["additions"]:
                unchanged += 1
                continue
            eligible += 1
            allowed = DETAIL_CONFIDENCE_ORDER[decision["confidence"]] >= DETAIL_CONFIDENCE_ORDER[min_confidence]
            action = "preview"
            if not allowed:
                skipped_confidence += 1
                action = "skipped_confidence"
            elif apply:
                con.execute(
                    "UPDATE Track SET genre = ?, lastEditTime = ? WHERE id = ?",
                    (decision["new_genre"], now, int(track["id"])),
                )
                updated += 1
                action = "updated"
                file_result = _track_file_tag_result(
                    path,
                    genre=decision["new_genre"],
                    bpm=track.get("bpm"),
                    key=track.get("camelot"),
                    rating=track.get("rating_raw", 0),
                )
                if file_result.get("file_tags_warning"):
                    file_failed += 1
                    file_warnings.append(f"{path}: {file_result.get('file_tags_warning')}")
                else:
                    file_written += 1
            suggestions.append({
                "track_id": int(track["id"]),
                "file": str(path),
                "label": track.get("label") or track.get("filename") or path.name,
                "old_genre": track.get("genre") or "",
                "additions": decision["additions"],
                "new_genre": decision["new_genre"],
                "confidence": decision["confidence"],
                "reason": decision["reason"],
                "source": decision.get("source") or ("AutoSet local" if source == "local" else "Online"),
                "action": action,
            })
        if apply:
            con.commit()

    scope = "current folder and subfolders" if recursive else "current folder"
    lines = [
        f"Style detail {'applied' if apply else 'preview'} for {scope}.",
        f"Source: {'local AutoSet rules' if source == 'local' else 'online lookup'}",
        f"Online providers: Discogs + MusicBrainz{' + Last.fm' if LASTFM_API_KEY else ' (Last.fm API key not set)'}",
        f"Audio files scanned: {len(files)} of {total_files}",
        f"Matched in Engine DB: {len(files) - len(missing)}",
        f"Tracks with suggestions: {eligible}",
        f"Updated: {updated}",
        f"Already detailed/no suggestion: {unchanged}",
        f"Skipped by confidence: {skipped_confidence}",
        f"File tags written: {file_written}",
        f"File tags skipped/failed: {file_failed}",
        f"Not found in Engine DB: {len(missing)}",
    ]
    if file_warnings:
        lines.append("")
        lines.append("File tag warnings:")
        lines.extend(f"- {item}" for item in file_warnings[:10])
    if suggestions:
        lines.append("")
        lines.append("Examples:")
        for item in suggestions[:18]:
            add_text = ", ".join(item["additions"])
            lines.append(f"- {item['label']}: + {add_text} -> {item['new_genre']} [{item['source']}; {item['confidence']}; {item['action']}]")
    if missing:
        lines.append("")
        lines.append("Missing examples:")
        lines.extend(f"- {p}" for p in missing[:8])
    return {
        "ok": True,
        "apply": bool(apply),
        "suggestions": suggestions,
        "suggestion_count": eligible,
        "updated": updated,
        "unchanged": unchanged,
        "skipped_confidence": skipped_confidence,
        "missing": len(missing),
        "file_tags_updated": file_written > 0,
        "file_tags_warning": "; ".join(file_warnings[:3]) if file_warnings else None,
        "written_fields": ["genre", "bpm", "key", "autoset_styles", "rating"] if file_written else [],
        "output": "\n".join(lines),
    }


def bulk_update_genres(rel, recursive, action, tag="", find="", replace=""):
    files = _audio_files_for_genre_bulk(rel, recursive)
    by_path, unique_name = load_track_maps()
    targets = []
    missing = []
    for path in files:
        track = track_for_file(path, by_path, unique_name)
        if track.get("id"):
            targets.append((int(track["id"]), path))
        else:
            missing.append(str(path))
    if not targets:
        return {"ok": False, "updated": 0, "output": "No Engine DB tracks found in this folder."}

    now = _engine_now_str()
    updated = 0
    unchanged = 0
    file_written = 0
    file_failed = 0
    file_warnings = []
    with open_db() as con:
        for track_id, path in targets:
            row = con.execute("SELECT genre, bpmAnalyzed, key, rating FROM Track WHERE id = ?", (int(track_id),)).fetchone()
            if not row:
                missing.append(str(path))
                continue
            current = row["genre"] or ""
            if action == "append":
                new_genre = _genre_after_bulk_action(current, action, tag, find, replace)
                changed = new_genre != join_genre_tags(split_genre_tags(current))
            else:
                new_genre, changed = _genre_after_bulk_action(current, action, tag, find, replace)
            if not changed:
                unchanged += 1
                continue
            con.execute(
                "UPDATE Track SET genre = ?, lastEditTime = ? WHERE id = ?",
                (new_genre, now, int(track_id)),
            )
            updated += 1
            file_result = _track_file_tag_result(
                path,
                genre=new_genre,
                bpm=row["bpmAnalyzed"],
                key=row["key"],
                rating=row["rating"],
            )
            if file_result.get("file_tags_warning"):
                file_failed += 1
                file_warnings.append(f"{path}: {file_result.get('file_tags_warning')}")
            else:
                file_written += 1
        con.commit()

    scope = "current folder and subfolders" if recursive else "current folder"
    output = (
        f"Genre tags updated for {scope}.\n"
        f"Audio files: {len(files)}\n"
        f"Matched in Engine DB: {len(targets)}\n"
        f"Updated: {updated}\n"
        f"Unchanged: {unchanged}\n"
        f"File tags written: {file_written}\n"
        f"File tags skipped/failed: {file_failed}\n"
        f"Not found in Engine DB: {len(missing)}"
    )
    if file_warnings:
        output += "\n\nFile tag warnings:\n" + "\n".join(f"- {item}" for item in file_warnings[:10])
    if missing:
        output += "\n\nMissing examples:\n" + "\n".join(f"- {p}" for p in missing[:12])
    return {
        "ok": True,
        "updated": updated,
        "unchanged": unchanged,
        "file_written": file_written,
        "file_failed": file_failed,
        "engine_db_updated": updated > 0,
        "file_tags_updated": file_written > 0,
        "file_tags_warning": "; ".join(file_warnings[:3]) if file_warnings else None,
        "written_fields": ["genre", "bpm", "key", "autoset_styles", "rating"] if file_written else [],
        "missing": len(missing),
        "output": output,
    }


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


def _table_has_column(con, table_name, column_name):
    try:
        rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
    except Exception:
        return False
    return any(str(row[1]).casefold() == str(column_name).casefold() for row in rows)


def _database_uuid_for_track(con, track_id, default_uuid):
    """Return the most likely Engine databaseUuid for a track.

    Some Engine libraries keep tracks from different import roots / devices under
    different databaseUuid values. If we write every PlaylistEntity with one global
    UUID, Engine can keep the row in SQLite but hide the track in the UI.
    """
    track_id = int(track_id)

    if _table_has_column(con, "Track", "databaseUuid"):
        try:
            row = con.execute(
                "SELECT databaseUuid FROM Track WHERE id=? AND databaseUuid IS NOT NULL AND databaseUuid != ''",
                (track_id,),
            ).fetchone()
            if row and row[0]:
                return str(row[0])
        except Exception:
            pass

    try:
        row = con.execute(
            """
            SELECT databaseUuid
            FROM PlaylistEntity
            WHERE trackId=?
              AND databaseUuid IS NOT NULL
              AND databaseUuid != ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (track_id,),
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass

    return str(default_uuid)


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
    # Важно: '-' внутри [] должен быть экранирован или стоять в конце, иначе regex падает ("bad character range").
    value = re.sub(r"[^0-9A-Za-zА-Яа-я _.,()\[\]\\-]+", "", value)
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
    ref_title = str(ref.get("title") or "").strip() or str(ref.get("filename") or "playlist")
    name = unified_set_or_playlist_name(ref.get("genre") or "", ref_title)
    return _safe_slug(name, 120) or _safe_slug(f"engine_playlist_{datetime.now().strftime('%d.%m.%y')}", 96)


def write_local_playlist_no_copy(playlist, out_dir, playlist_name):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist_name = str(playlist_name or "").strip() or "playlist"
    m3u_path = out_dir / f"{playlist_name}.m3u"
    csv_path = out_dir / f"{playlist_name}.csv"

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


def _engine_track_id_for_playlist_item(con, item):
    if isinstance(item, dict):
        raw_id = item.get("id")
        if raw_id is not None:
            try:
                track_id = int(raw_id)
            except Exception:
                track_id = 0
            if track_id:
                row = con.execute("SELECT id FROM Track WHERE id=?", (track_id,)).fetchone()
                if row:
                    return int(row[0]), None
        raw_path = item.get("path") or ""
    else:
        raw_path = item

    abs_path = str(Path(str(raw_path)).resolve()) if str(raw_path).strip() else ""
    if not abs_path:
        return None, ("", "")
    try:
        engine_path = _engine_track_path_for_abs(abs_path)
    except Exception:
        engine_path = abs_path
    row = con.execute("SELECT id FROM Track WHERE path=?", (engine_path,)).fetchone()
    if not row:
        row = con.execute("SELECT id FROM Track WHERE path=?", (abs_path,)).fetchone()
    if row:
        return int(row[0]), None
    return None, (abs_path, engine_path)


def _next_available_playlist_title(con, parent_list_id, title):
    """Return title or title_N if a playlist with this title already exists."""
    base = str(title or "").strip() or "playlist"
    if not _find_playlist(con, parent_list_id, base):
        return base
    for index in range(2, 10000):
        candidate = f"{base}_{index}"
        if not _find_playlist(con, parent_list_id, candidate):
            return candidate
    raise ValueError(f"Cannot find free playlist name for: {base}")


def create_engine_playlist_from_tracks(tracks, folder_path, title):
    folder_path = str(folder_path or "").strip()
    title = str(title or "").strip()
    if not folder_path or not title:
        raise ValueError("folder and title are required")
    tracks = [t for t in (tracks or []) if t]
    if not tracks:
        raise ValueError("Empty track list")

    con = sqlite3.connect(str(DB_PATH))
    try:
        con.execute("PRAGMA foreign_keys=ON;")
        database_uuid = _get_engine_database_uuid(con)
        with con:
            parent_id = _ensure_folder_path(con, folder_path)
            final_title = _next_available_playlist_title(con, parent_id, title)
            list_id = _insert_playlist(con, parent_id, final_title)

            missing = []
            track_ids = []
            for item in tracks:
                track_id, missing_path = _engine_track_id_for_playlist_item(con, item)
                if not track_id:
                    missing.append(missing_path)
                    continue
                track_ids.append(int(track_id))

            if missing:
                lines = ["Some tracks are not imported in Engine DB (Track.path not found):"]
                for abs_path, engine_path in missing[:30]:
                    lines.append(f"- {abs_path} (expected: {engine_path})")
                if len(missing) > 30:
                    lines.append(f"... and {len(missing) - 30} more")
                raise ValueError("\n".join(lines))

            # Insert rows in the same visible order as the playlist.
            # Then patch nextEntityId in a second pass. This is closer to how
            # Engine DJ writes playlist entities than reverse insertion.
            entity_ids = []
            for track_id in track_ids:
                track_database_uuid = _database_uuid_for_track(con, track_id, database_uuid)
                cur = con.execute(
                    """
                    INSERT INTO PlaylistEntity(listId, trackId, databaseUuid, nextEntityId, membershipReference)
                    VALUES (?, ?, ?, 0, 0)
                    """,
                    (int(list_id), int(track_id), track_database_uuid),
                )
                entity_ids.append(int(cur.lastrowid))

            for current_entity_id, next_entity_id in zip(entity_ids, entity_ids[1:]):
                con.execute(
                    "UPDATE PlaylistEntity SET nextEntityId=? WHERE id=?",
                    (int(next_entity_id), int(current_entity_id)),
                )

            now = _engine_now_str()
            con.execute("UPDATE Playlist SET lastEditTime=? WHERE id=?", (now, int(list_id)))
            # Also touch the parent folder so Engine notices externally-created playlist changes.
            con.execute("UPDATE Playlist SET lastEditTime=? WHERE id=?", (now, int(parent_id)))

        return {
            "ok": True,
            "playlist_id": list_id,
            "track_count": len(track_ids),
            "playlist_title": final_title,
            "output": f"Engine playlist created: {folder_path}/{final_title} (id={list_id}), tracks: {len(track_ids)}",
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
        str(PROJECT_DIR / "reports"),
        "--backup-dir",
        str(PROJECT_DIR / "tag_backups"),
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


def _is_protected_set_path(path):
    rel_norm = rel_to_music(path).replace("\\", "/").casefold()
    return rel_norm in {"set", "sets"} or rel_norm.startswith("set/") or rel_norm.startswith("sets/")


def _write_energy_ratings_for_paths(paths, scope_label):
    wanted = {norm_abs(p): p for p in paths}
    if not wanted:
        return {"ok": True, "updated": 0, "matched": 0, "skipped": 0, "output": f"No audio files in {scope_label}."}
    now = _engine_now_str()
    matched = 0
    updated = 0
    skipped = 0
    unchanged = 0
    file_written = 0
    file_failed = 0
    file_warnings = []
    with open_db() as con:
        rows = con.execute(
            """
            SELECT
              Track.id,
              Track.path,
              Track.genre,
              Track.bpmAnalyzed,
              Track.key,
              Track.rating,
              PerformanceData.overviewWaveFormData AS overviewWaveFormData
            FROM Track
            LEFT JOIN PerformanceData ON PerformanceData.trackId = Track.id
            WHERE Track.isAvailable = 1
              AND Track.path IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            path = resolve_track_path(row["path"])
            if norm_abs(path) not in wanted:
                continue
            matched += 1
            _energy, rating = _energy_from_overview_blob(row["overviewWaveFormData"])
            if not rating:
                skipped += 1
                continue
            engine_rating = _stars_to_engine_rating(rating)
            if int(row["rating"] or 0) == engine_rating:
                unchanged += 1
                continue
            con.execute(
                "UPDATE Track SET rating = ?, lastEditTime = ? WHERE id = ?",
                (int(engine_rating), now, int(row["id"])),
            )
            updated += 1
            file_result = _track_file_tag_result(
                path,
                genre=row["genre"],
                bpm=row["bpmAnalyzed"],
                key=row["key"],
                rating=rating,
            )
            if file_result.get("file_tags_warning"):
                file_failed += 1
                file_warnings.append(f"{path}: {file_result.get('file_tags_warning')}")
            else:
                file_written += 1
        con.commit()

    missing = max(0, len(wanted) - matched)
    output = (
        f"Energy stars updated for {scope_label}.\n"
        f"Audio files: {len(wanted)}\n"
        f"Matched in Engine DB: {matched}\n"
        f"Updated Track.rating: {updated}\n"
        f"File tags written: {file_written}\n"
        f"File tags skipped/failed: {file_failed}\n"
        f"Already correct: {unchanged}\n"
        f"Skipped without waveform: {skipped}\n"
        f"Not found in Engine DB: {missing}"
    )
    if file_warnings:
        output += "\n\nFile tag warnings:\n" + "\n".join(f"- {item}" for item in file_warnings[:10])
    return {
        "ok": True,
        "updated": updated,
        "matched": matched,
        "skipped": skipped,
        "unchanged": unchanged,
        "missing": missing,
        "engine_db_updated": updated > 0,
        "file_tags_updated": file_written > 0,
        "file_tags_warning": "; ".join(file_warnings[:3]) if file_warnings else None,
        "written_fields": ["genre", "bpm", "key", "autoset_styles", "rating"] if file_written else [],
        "output": output,
    }


def write_energy_ratings(rel):
    target = safe_music_path(rel)
    if _is_protected_set_path(target):
        raise ValueError("Set/Sets folders are protected from rating updates")
    if not target.exists() or not target.is_dir():
        raise ValueError("Folder does not exist")
    files = [
        child
        for child in target.iterdir()
        if is_audio_file(child)
    ]
    return _write_energy_ratings_for_paths(files, "current folder")


def write_all_energy_ratings():
    files = []
    for path in MUSIC_ROOT.rglob("*"):
        if not is_audio_file(path):
            continue
        if _is_protected_set_path(path):
            continue
        files.append(path)
    return _write_energy_ratings_for_paths(files, "Music library")


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
        str(PROJECT_DIR / "reports" / "genres"),
        "--backup-dir",
        str(PROJECT_DIR / "tag_backups"),
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
        if parsed.path == "/api/db-diagnostics":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(engine_db_diagnostics(qs.get("limit", ["2"])[0]))
            except Exception as exc:
                self.send_json({"ok": False, "error": repr(exc)}, status=400)
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
        if parsed.path == "/api/performance":
            qs = parse_qs(parsed.query)
            track_id = qs.get("track_id", [""])[0]
            try:
                self.send_json(get_track_performance(track_id))
            except Exception as exc:
                self.send_json({"ok": False, "error": repr(exc)}, status=400)
            return
        if parsed.path == "/api/track_waveform_detail":
            qs = parse_qs(parsed.query)
            track_id = qs.get("track_id", [""])[0]
            try:
                self.send_json(get_track_waveform_detail(track_id))
            except Exception as exc:
                self.send_json({"ok": False, "error": repr(exc)}, status=400)
            return
        if parsed.path == "/api/track_marks":
            qs = parse_qs(parsed.query)
            track_id = qs.get("track_id", [""])[0]
            try:
                self.send_json(get_track_marks(track_id))
            except Exception as exc:
                self.send_json({"ok": False, "error": repr(exc)}, status=400)
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
        if parsed_path not in {"/api/build", "/api/engine-playlist", "/api/refresh-tags", "/api/write-energy-ratings", "/api/write-all-energy-ratings", "/api/update-genre", "/api/bulk-genre", "/api/detail-styles", "/api/config", "/api/track_marks", "/api/export_track_marks_to_engine", "/api/suggest_track_marks", "/api/batch_suggest_track_marks"}:
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
            elif parsed_path == "/api/track_marks":
                self.send_json(write_track_marks(data))
            elif parsed_path == "/api/export_track_marks_to_engine":
                self.send_json(export_track_marks_to_engine(data))
            elif parsed_path == "/api/suggest_track_marks":
                self.send_json(suggest_track_marks(data))
            elif parsed_path == "/api/batch_suggest_track_marks":
                self.send_json(batch_suggest_track_marks(data))
            elif parsed_path == "/api/build":
                self.send_json(build_set(data["track_id"], data.get("role", "start"), data.get("minutes", 90), data.get("max_key_step", 3), data.get("bpm_window", 5), data.get("style_filter", [])))
            elif parsed_path == "/api/engine-playlist":
                playlist = _build_playlist_only(
                    data["track_id"],
                    data.get("role", "start"),
                    data.get("minutes", 90),
                    data.get("max_key_step", 3),
                    data.get("bpm_window", 5),
                    data.get("style_filter", []),
                )
                base_name = _engine_playlist_local_folder_name(playlist, data.get("role", "start"))
                # Сначала создаем Engine playlist и получаем фактическое имя.
                # Если такое имя уже есть, create_engine_playlist_from_tracks добавит _2, _3 и т.д.
                result = create_engine_playlist_from_tracks(playlist.get("tracks") or [], data.get("folder", ""), base_name)
                engine_title = result.get("playlist_title") or base_name
                # Локальный m3u/csv должен называться так же, как новый плейлист Engine,
                # чтобы тестовые прогоны не перезаписывали один и тот же файл.
                local_out = write_local_playlist_no_copy(playlist, SETS_DIR / engine_title, engine_title)
                result["local_playlist_folder"] = local_out["folder"]
                result["local_m3u"] = local_out["m3u"]
                result["local_csv"] = local_out["csv"]
                result["engine_playlist_title"] = engine_title
                self.send_json(result)
            elif parsed_path == "/api/refresh-tags":
                self.send_json(refresh_tags(data.get("path", "")))
            elif parsed_path == "/api/write-energy-ratings":
                self.send_json(write_energy_ratings(data.get("path", "")))
            elif parsed_path == "/api/write-all-energy-ratings":
                self.send_json(write_all_energy_ratings())
            elif parsed_path == "/api/bulk-genre":
                self.send_json(bulk_update_genres(
                    data.get("path", ""),
                    bool(data.get("recursive", False)),
                    data.get("action", ""),
                    data.get("tag", ""),
                    data.get("find", ""),
                    data.get("replace", ""),
                ))
            elif parsed_path == "/api/detail-styles":
                self.send_json(detail_folder_styles(
                    data.get("path", ""),
                    bool(data.get("recursive", False)),
                    bool(data.get("apply", False)),
                    data.get("min_confidence", "medium"),
                    data.get("files") or None,
                    data.get("source", "online"),
                ))
            else:
                self.send_json(update_genre(data["track_id"], data["genre"]))
        except Exception as exc:
            self.send_json({"ok": False, "error": repr(exc)}, status=500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/track_marks":
            self.send_error(404)
            return
        qs = parse_qs(parsed.query)
        track_id = qs.get("track_id", [""])[0]
        try:
            self.send_json(delete_track_marks(track_id))
        except Exception as exc:
            self.send_json({"ok": False, "error": repr(exc)}, status=400)


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
