import argparse
import csv
import math
import os
import re
import shutil
import sqlite3
import struct
import sys
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import List, Optional, Sequence, Tuple

from track_analysis import TrackProfile
from transition_analysis import (
    TRANSITION_REJECTED,
    TRANSITION_RISKY,
    TRANSITION_SAFE,
    transition_score as profile_transition_score,
)

try:
    from engine_config import PATHS
except Exception:
    PATHS = {
        "db_path": str(Path.cwd().parent / "Engine Library" / "Database2" / "m.db"),
        "music_root": str(Path.cwd().parent / "Music"),
        "out_dir": str(Path.cwd().parent / "Music" / "Sets"),
    }

DEFAULT_DB_PATH = PATHS["db_path"]
DEFAULT_MUSIC_ROOT = PATHS["music_root"]
DEFAULT_OUT_DIR = PATHS["out_dir"]
BPM_RISE_LIMIT = 5.0
BPM_WINDOW_DOWN = 4.0
MAX_ADJACENT_BPM_STEP = 2.0


@dataclass(frozen=True)
class Track:
    id: int
    filename: str
    length: int
    bitrate: Optional[int]
    bpm: Optional[float]
    key: Optional[int]
    genre: str
    artist: str
    title: str
    path: str
    wave_energy: Optional[float] = None
    dj_style: str = ""
    dj_family: str = ""
    dj_set_ok: bool = True


_NOTE_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_CAMELOT_MAJOR = {
    "C": "8B", "C#": "3B", "D": "10B", "D#": "5B", "E": "12B", "F": "7B",
    "F#": "2B", "G": "9B", "G#": "4B", "A": "11B", "A#": "6B", "B": "1B",
}
_CAMELOT_MINOR = {
    "C": "5A", "C#": "12A", "D": "7A", "D#": "2A", "E": "9A", "F": "4A",
    "F#": "11A", "G": "6A", "G#": "1A", "A": "8A", "A#": "3A", "B": "10A",
}

STYLE_CANONICAL = {
    "breakbeat": "break_beat",
    "break_beat": "break_beat",
    "drum_bass": "drum_and_bass",
    "drum_n_bass": "drum_and_bass",
    "drum_and_bass": "drum_and_bass",
    "dnb": "drum_and_bass",
    "funky": "funky_house",
    "groove": "funky_house",
    "jackin": "jackin_house",
    "deep_tech": "minimal_deep_tech",
    "minimal_deep_tech": "minimal_deep_tech",
    "euro_house": "euro_house",
    "soul_funk": "soul_and_funk",
    "soul_and_funk": "soul_and_funk",
    "russian": "rus",
    "рус": "rus",
}

STYLE_ALIASES = {
    "house": ["house"],
    "tech_house": ["tech house", "techhouse"],
    "deep_house": ["deep house"],
    "disco_house": ["disco house", "disco"],
    "progressive": ["progressive"],
    "progressive_house": ["progressive house"],
    "afro_house": ["afro house", "afro"],
    "funky_house": ["funky house", "funky", "groove"],
    "club_house": ["club house", "club-house"],
    "electro_house": ["electro house"],
    "future_house": ["future house"],
    "soulful_house": ["soulful house"],
    "jazz_house": ["jazz house"],
    "chill_house": ["chill house"],
    "techno": ["techno", "minimal"],
    "melodic_techno": ["melodic techno", "anyma"],
    "minimal_deep_tech": ["minimal deep tech", "minimal/deep tech", "deep tech"],
    "electronic": ["electronic", "electronics", "electronica"],
    "electro": ["electro"],
    "dance": ["dance", "edm", "eurodance"],
    "nu_disco": ["nu disco"],
    "indie_dance": ["indie dance"],
    "trance": ["trance"],
    "progressive_trance": ["progressive trance"],
    "psy_trance": ["psy-trance", "psy trance"],
    "uplifting_trance": ["uplifting trance"],
    "break_beat": ["breakbeat", "break beat"],
    "drum_and_bass": ["drum & bass", "drum and bass", "dnb"],
    "uk_garage": ["uk garage"],
    "garage": ["garage"],
    "pop": ["pop", "ruspop", "europop"],
    "rock": ["rock", "rusrock", "alternative"],
    "chill": ["chill", "chillout", "chill out", "ambient", "downtempo", "lounge"],
}

SPECIAL_ALLOW_STYLES = {"rus"}
RUS_STYLE_VALUES = {"rus", "russian", "рус", "ruspop", "rusrock"}


def open_db(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _wave_energy_from_blob(blob) -> Optional[float]:
    """Return normalized average peak energy from Engine overview waveform data."""
    if not blob or len(blob) < 22:
        return None
    try:
        raw = zlib.decompress(blob[4:])
        if len(raw) < 16:
            return None
        _header, points, _reserved_a, _reserved_b = struct.unpack(">4I", raw[:16])
        if not points or points > 8192:
            return None
        payload = raw[16:]
        needed = points * 3
        if len(payload) < needed:
            return None
        peaks = (max(payload[i], payload[i + 1], payload[i + 2]) for i in range(0, needed, 3))
        average = sum(peaks) / (points * 255.0)
        return round(max(0.05, min(0.98, average ** 0.85)), 4)
    except (TypeError, ValueError, IndexError, struct.error, zlib.error):
        return None


def engine_key_to_name(key: Optional[int]) -> str:
    if key is None or key < 0 or key > 23:
        return ""
    if key <= 11:
        return _NOTE_SHARP[key]
    return f"{_NOTE_SHARP[key - 12]}m"


def engine_key_to_camelot(key: Optional[int]) -> str:
    name = engine_key_to_name(key)
    if not name:
        return ""
    if name.endswith("m"):
        return _CAMELOT_MINOR.get(name[:-1], "")
    return _CAMELOT_MAJOR.get(name, "")


def parse_camelot(value: str) -> Optional[Tuple[int, str]]:
    m = re.match(r"^\s*(1[0-2]|[1-9])\s*([AB])\s*$", value or "", re.I)
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper()


def number_distance(a: int, b: int) -> int:
    d = abs(a - b)
    return min(d, 12 - d)


def camelot_score(a_key: Optional[int], b_key: Optional[int], max_step: int) -> float:
    a = parse_camelot(engine_key_to_camelot(a_key))
    b = parse_camelot(engine_key_to_camelot(b_key))
    if not a or not b:
        return 999.0
    num_dist = number_distance(a[0], b[0])
    if num_dist > max(0, int(max_step)):
        return 999.0
    return float(num_dist)


def camelot_relation(a_key: Optional[int], b_key: Optional[int]) -> Tuple[Optional[int], str]:
    a = parse_camelot(engine_key_to_camelot(a_key))
    b = parse_camelot(engine_key_to_camelot(b_key))
    if not a or not b:
        return None, "unknown"
    num_dist = number_distance(a[0], b[0])
    if a == b:
        return 0, "same key"
    if a[0] == b[0]:
        return 0, "same Camelot number (A/B allowed)"
    if a[1] == b[1] and num_dist == 1:
        return 1, "neighbor key"
    if a[1] == b[1]:
        return num_dist, f"{num_dist} wheel steps"
    return num_dist, f"{num_dist} wheel steps (A/B allowed)"


def normalize_style(value: str) -> str:
    value = (value or "").casefold().strip()
    value = re.sub(r"&", " and ", value)
    value = re.sub(r"[^a-zа-я0-9]+", "_", value, flags=re.I)
    normalized = re.sub(r"_+", "_", value).strip("_")
    return STYLE_CANONICAL.get(normalized, normalized)


def parse_style_filter(value: str) -> set:
    return {normalize_style(p) for p in re.split(r"[,;|]+", value or "") if p.strip()}


def genre_tokens(genre: str) -> set:
    return {p.strip().lower() for p in re.split(r"[,;/|<>]+", genre or "") if p.strip()}


def genre_words(track: Track) -> set:
    text = " ".join([track.genre, track.filename, track.title, track.artist, track.dj_style, track.dj_family])
    return {p.strip().lower() for p in re.split(r"[^A-Za-zА-Яа-я0-9]+", text or "") if p.strip()}


def genre_family(track: Track) -> set:
    if track.dj_family:
        return {normalize_style(track.dj_family)}
    words = genre_words(track)
    families = set()
    identity = " ".join([track.artist, track.title, track.filename]).casefold()
    if "house" in words:
        families.add("house")
    if "techno" in words or "minimal" in words or "anyma" in identity:
        families.add("techno")
    if "trance" in words:
        families.add("trance")
    if "disco" in words:
        families.add("disco")
    if "funky" in words or "funk" in words:
        families.add("funk")
    if "dance" in words:
        families.add("dance")
    if "electronic" in words or "electronics" in words or "electronica" in words:
        families.add("electronic")
    if "break" in words or "breakbeat" in words:
        families.add("break_beat")
    if "dnb" in words or "drum" in words:
        families.add("drum_and_bass")
    if "pop" in words or "ruspop" in words:
        families.add("pop")
    if "rock" in words or "rusrock" in words:
        families.add("rock")
    strong = families - {"electronic", "dance"}
    return strong or families or {normalize_style(x) for x in genre_tokens(track.genre)}


def style_buckets(track: Track) -> set:
    text = " ".join([track.genre, track.dj_style, track.dj_family, track.filename, track.artist, track.title]).casefold()
    buckets = set()
    for bucket, aliases in STYLE_ALIASES.items():
        if any(alias in text for alias in aliases):
            buckets.add(normalize_style(bucket))
    if not buckets:
        buckets |= genre_family(track)
    return buckets


def candidate_style_values(track: Track) -> set:
    values = set(style_buckets(track))
    for field in [track.genre, track.dj_style, track.dj_family]:
        for part in re.split(r"[,;/|<>]+", field or ""):
            norm = normalize_style(part)
            if norm:
                values.add(norm)
    return values


def track_has_rus_tag(track: Track) -> bool:
    for field in [track.genre, track.dj_style, track.dj_family]:
        for part in re.split(r"[,;/|<>]+", field or ""):
            if normalize_style(part) in RUS_STYLE_VALUES:
                return True
    return False


def same_genre_family(reference: Track, candidate: Track) -> bool:
    if not candidate.dj_set_ok:
        return False
    ref = genre_family(reference)
    cand = genre_family(candidate)
    return bool(ref and cand and ref & cand)


def style_allowed(reference: Track, candidate: Track, allowed_styles: set) -> bool:
    if not candidate.dj_set_ok:
        return False
    allow_rus = "rus" in allowed_styles
    if track_has_rus_tag(candidate) and not allow_rus:
        return False
    music_styles = set(allowed_styles) - SPECIAL_ALLOW_STYLES
    if music_styles:
        return bool(candidate_style_values(candidate) & music_styles)
    return same_genre_family(reference, candidate)


def genre_distance(a: Track, b: Track) -> float:
    af = genre_family(a)
    bf = genre_family(b)
    if af and bf and af & bf:
        return 0.15
    at = genre_tokens(a.genre) | genre_words(a)
    bt = genre_tokens(b.genre) | genre_words(b)
    if not at or not bt:
        return 0.65
    overlap = len(at & bt)
    union = len(at | bt)
    return max(0.2, 1.0 - (overlap / union)) if overlap else 1.0


def energy_score(track: Track) -> float:
    if track.wave_energy is not None:
        return float(track.wave_energy)
    words = genre_words(track)
    base = 0.5
    if {"ambient", "downtempo", "chill", "chillout"} & words:
        base = 0.28
    elif {"deep", "organic"} & words and "house" in words:
        base = 0.48
    elif {"afro", "disco", "funky", "funk"} & words and "house" in words:
        base = 0.62
    elif "house" in words:
        base = 0.66
    elif "techno" in words:
        base = 0.8
    elif {"dnb", "drum"} & words:
        base = 0.9
    elif {"dance", "edm"} & words:
        base = 0.72
    if track.bpm:
        base += max(-0.12, min(0.16, (track.bpm - 120.0) / 90.0))
    if track.length < 180:
        base -= 0.04
    if "radio" in words or "edit" in words:
        base -= 0.03
    if "extended" in words or "remix" in words:
        base += 0.03
    return max(0.05, min(0.98, base))


def _track_to_transition_profile(track: Track) -> TrackProfile:
    return TrackProfile(
        track_id=str(track.id),
        file_path=str(track.path or track.filename or ""),
        duration_seconds=float(track.length),
        bpm=track.bpm,
        camelot_key=engine_key_to_camelot(track.key),
        genre=track.genre,
        energy_mean=energy_score(track),
    )


def transition_score_adjustment(
    previous: Track,
    candidate: Track,
) -> Optional[float]:
    result = profile_transition_score(
        _track_to_transition_profile(previous),
        _track_to_transition_profile(candidate),
    )

    if (
        not result.accepted
        or result.transition_class == TRANSITION_REJECTED
    ):
        return None

    if result.transition_class == TRANSITION_SAFE:
        return -8.0

    if result.transition_class == TRANSITION_RISKY:
        return 35.0

    return 0.0


def transition_score(previous: Optional[Track], candidate: Track) -> Tuple[float, str]:
    if previous is None:
        return 1.0, "opening track"
    bpm_delta = abs((previous.bpm or candidate.bpm or 0.0) - (candidate.bpm or previous.bpm or 0.0))
    cdist, relation = camelot_relation(previous.key, candidate.key)
    gdist = genre_distance(previous, candidate)
    edelta = abs(energy_score(previous) - energy_score(candidate))
    score = 1.0
    score -= min(0.35, bpm_delta / 18.0)
    score -= min(0.3, (cdist if cdist is not None else 4) / 10.0)
    score -= min(0.2, gdist * 0.2)
    score -= min(0.2, edelta * 0.45)
    reason = f"BPM delta {bpm_delta:.1f}; {relation}; genre distance {gdist:.2f}; energy delta {edelta:.2f}"
    return max(0.0, round(score, 4)), reason


def track_identity(track: Track) -> Tuple[str, str]:
    artist = re.split(r"\s*(?:,|&|feat\.?|ft\.?|/)\s*", (track.artist or "").casefold())[0].strip()
    title = (track.title or track.filename or "").casefold()
    title = re.sub(r"\([^)]*(?:mix|edit|remix|radio|extended|original)[^)]*\)", "", title)
    title = re.sub(r"\[[^]]*(?:mix|edit|remix|radio|extended|original)[^]]*\]", "", title)
    return re.sub(r"\W+", "", artist), re.sub(r"\W+", "", title)


def label(track: Track) -> str:
    parts = [p for p in [track.artist.strip(), track.title.strip()] if p]
    return " - ".join(parts) if parts else track.filename


def slug(text: str) -> str:
    text = re.sub(r"[^\w\- ]+", "", text, flags=re.U).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:80] or "hour_set"


def reference_genre_slug(reference: Track) -> str:
    parts = [p.strip() for p in re.split(r"[,;/|<>]+", reference.genre or "") if p.strip()]
    return slug(parts[0] if parts else reference.genre).lower() or "mixed"


def safe_filename(text: str, fallback: str = "track") -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text or "")
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    return text[:140] or fallback


def debug_suffix(track: Track) -> str:
    bpm = f"{round(track.bpm, 1):g}BPM" if track.bpm else "BPM"
    camelot = engine_key_to_camelot(track.key) or "key"
    return safe_filename(f"{bpm}-{camelot}", "meta")


def resolve_track_path(track: Track, music_root: Path) -> Optional[Path]:
    if not track.path:
        return None
    original = track.path.strip()
    raw = original.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", raw):
        win_path = PureWindowsPath(original)
        for root in (PureWindowsPath("G:/Music"), PureWindowsPath("F:/Music")):
            try:
                rel = win_path.relative_to(root)
                return music_root.joinpath(*rel.parts).resolve()
            except ValueError:
                pass
        return Path(original)
    if os.path.isabs(original):
        return Path(original)
    for prefix in ("../Music/", "Music/"):
        if raw.startswith(prefix):
            rel = raw[len(prefix):]
            return music_root.joinpath(*[p for p in rel.split("/") if p]).resolve()
    if raw.startswith("../"):
        raw = raw[3:]
    return music_root.joinpath(*[p for p in raw.split("/") if p]).resolve() if raw else None


def _read_txxx_mp3(path: Optional[Path]) -> Tuple[str, str, Optional[bool]]:
    if not path or not path.exists() or path.suffix.lower() != ".mp3":
        return "", "", None
    try:
        from mutagen.id3 import ID3
        tags = ID3(str(path))
    except Exception:
        return "", "", None
    values = {}
    for frame in tags.getall("TXXX"):
        desc = str(getattr(frame, "desc", "") or "")
        text = getattr(frame, "text", []) or []
        values[desc] = str(text[0]) if text else ""
    set_ok_raw = values.get("DJ_SET_OK", "")
    set_ok = None
    if set_ok_raw.strip() in {"0", "1"}:
        set_ok = set_ok_raw.strip() == "1"
    return values.get("DJ_STYLE", ""), values.get("DJ_GENRE_FAMILY", ""), set_ok


def _row_has_column(con: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return False
    return any(str(r[1]).lower() == column.lower() for r in rows)


def load_tracks(con: sqlite3.Connection, music_root: Path) -> List[Track]:
    # Keep this query intentionally conservative: it uses core Engine columns and does not fail if
    # PerformanceData is absent or differs across Engine versions.
    has_perf = False
    try:
        con.execute("SELECT 1 FROM PerformanceData LIMIT 1").fetchone()
        has_perf = True
    except Exception:
        has_perf = False

    if has_perf:
        query = """
        SELECT Track.id, Track.filename, Track.length, Track.bitrate,
               Track.bpmAnalyzed, Track.key, Track.genre, Track.artist,
               Track.title, Track.path,
               PerformanceData.overviewWaveFormData AS overviewWaveFormData
        FROM Track
        LEFT JOIN PerformanceData ON PerformanceData.trackId = Track.id
        WHERE isAvailable = 1
          AND bpmAnalyzed IS NOT NULL
          AND key IS NOT NULL
          AND length IS NOT NULL
          AND length BETWEEN 75 AND 720
          AND path IS NOT NULL
        """
    else:
        query = """
        SELECT id, filename, length, bitrate, bpmAnalyzed, key, genre, artist, title, path
        FROM Track
        WHERE isAvailable = 1
          AND bpmAnalyzed IS NOT NULL
          AND key IS NOT NULL
          AND length IS NOT NULL
          AND length BETWEEN 75 AND 720
          AND path IS NOT NULL
        """

    rows = con.execute(query).fetchall()
    tracks: List[Track] = []
    for r in rows:
        base = Track(
            id=int(r["id"]),
            filename=str(r["filename"] or ""),
            length=int(r["length"] or 0),
            bitrate=None if r["bitrate"] is None else int(r["bitrate"]),
            bpm=None if r["bpmAnalyzed"] is None else float(r["bpmAnalyzed"]),
            key=None if r["key"] is None else int(r["key"]),
            genre=str(r["genre"] or ""),
            artist=str(r["artist"] or ""),
            title=str(r["title"] or ""),
            path=str(r["path"] or ""),
            wave_energy=_wave_energy_from_blob(r["overviewWaveFormData"]),
        )
        resolved = resolve_track_path(base, music_root)
        dj_style, dj_family, dj_set_ok = _read_txxx_mp3(resolved)
        tracks.append(Track(**{**base.__dict__, "dj_style": dj_style, "dj_family": dj_family, "dj_set_ok": True if dj_set_ok is None else dj_set_ok}))
    return tracks


def dedupe_tracks(tracks: Sequence[Track], keep_id: int) -> List[Track]:
    kept: List[Track] = []
    seen_paths = set()
    seen_songs = set()
    for track in tracks:
        path_key = (track.path or track.filename).strip().lower().replace("/", "\\")
        song_key = (*track_identity(track), round(track.bpm or 0.0))
        if track.id != keep_id and (path_key in seen_paths or song_key in seen_songs):
            continue
        kept.append(track)
        seen_paths.add(path_key)
        seen_songs.add(song_key)
    return kept


def pick_reference_by_id(reference_id: int, tracks: Sequence[Track]) -> Track:
    for t in tracks:
        if t.id == reference_id:
            return t
    raise SystemExit(f"Reference track is in Engine DB but is not usable for a set: id={reference_id}")


def pick_reference(reference_file: Path, tracks: Sequence[Track], db_path: str) -> Track:
    size = reference_file.stat().st_size if reference_file.exists() else None
    name = reference_file.name.lower()
    with open_db(db_path) as con:
        row = None
        if size is not None and _row_has_column(con, "Track", "fileBytes"):
            row = con.execute(
                "SELECT id FROM Track WHERE lower(filename) = ? AND fileBytes = ? LIMIT 1",
                (name, int(size)),
            ).fetchone()
        if not row:
            row = con.execute(
                "SELECT id FROM Track WHERE lower(filename) = ? GROUP BY lower(filename) HAVING COUNT(*) = 1 LIMIT 1",
                (name,),
            ).fetchone()
    if not row:
        raise SystemExit(f"Reference track was not found in Engine DB by filename: {reference_file}")
    return pick_reference_by_id(int(row["id"]), tracks)


def score_candidate(
    candidate: Track,
    previous: Optional[Track],
    reference: Track,
    target_bpm: float,
    target_energy: Optional[float],
    target_remaining: Optional[int],
    max_key_step: int,
    min_bpm: float,
    max_bpm: float,
    allowed_styles: set,
    selected: Optional[Sequence[Track]] = None,
) -> float:
    cand_bpm = candidate.bpm or target_bpm
    if cand_bpm < min_bpm or cand_bpm > max_bpm:
        return 1e9
    if not style_allowed(reference, candidate, allowed_styles):
        return 1e9

    score = 0.0
    if previous:
        h = camelot_score(previous.key, candidate.key, max_key_step)
        if h >= 999:
            return 1e9
        score += h * 22.0
        bpm_delta = abs((previous.bpm or target_bpm) - cand_bpm)
        if bpm_delta > MAX_ADJACENT_BPM_STEP:
            return 1e9
        score += bpm_delta * 10.0

        transition_adjustment = transition_score_adjustment(
            previous,
            candidate,
        )
        if transition_adjustment is None:
            return 1e9
        score += transition_adjustment
    else:
        score += camelot_score(reference.key, candidate.key, max_key_step) * 10.0

    score += abs(cand_bpm - target_bpm) * 4.0
    selected = selected or []
    exact_key_count = sum(1 for t in selected if engine_key_to_camelot(t.key) == engine_key_to_camelot(reference.key))
    exact_bpm_count = sum(1 for t in selected if t.bpm is not None and reference.bpm is not None and abs(t.bpm - reference.bpm) < 0.25)
    exact_key_limit = max(2, math.ceil((len(selected) + 1) * 0.55))
    exact_bpm_limit = max(2, math.ceil((len(selected) + 1) * 0.55))
    if engine_key_to_camelot(candidate.key) == engine_key_to_camelot(reference.key) and exact_key_count >= exact_key_limit:
        score += 14.0
    if reference.bpm is not None and abs(cand_bpm - reference.bpm) < 0.25 and exact_bpm_count >= exact_bpm_limit:
        score += 9.0

    if target_energy is None:
        target_energy = energy_score(reference)
    score += abs(energy_score(candidate) - target_energy) * 8.0
    if previous and track_identity(previous) == track_identity(candidate):
        score += 18.0
    if candidate.bitrate is not None and candidate.bitrate < 256:
        score += 8.0
    if candidate.length < 150 or candidate.length > 420:
        score += 5.0
    if target_remaining is not None:
        score += abs(target_remaining - candidate.length) / 90.0
        if candidate.length > target_remaining + 210:
            score += 20.0
    return score


def pick_next(
    remaining: List[Track],
    previous: Optional[Track],
    reference: Track,
    target_bpm: float,
    target_energy: Optional[float],
    target_remaining: Optional[int],
    max_key_step: int,
    min_bpm: float,
    max_bpm: float,
    allowed_styles: set,
    selected: Optional[Sequence[Track]] = None,
) -> Optional[Track]:
    best_i = None
    best_score = 1e9
    for i, track in enumerate(remaining):
        s = score_candidate(
            track, previous, reference, target_bpm, target_energy, target_remaining,
            max_key_step, min_bpm, max_bpm, allowed_styles, selected,
        )
        if s < best_score:
            best_i = i
            best_score = s
    if best_i is None or best_score >= 1e9:
        return None
    return remaining.pop(best_i)


def extend_forward(sequence: List[Track], remaining: List[Track], reference: Track, target_total: int,
                   max_key_step: int, bpm_curve, energy_curve, min_bpm: float, max_bpm: float,
                   allowed_styles: set) -> List[Track]:
    elapsed = sum(t.length for t in sequence)
    while elapsed < target_total - 120 and remaining:
        frac = min(1.0, elapsed / max(1, target_total))
        target_bpm = bpm_curve(frac)
        target_energy = None if energy_curve is None else energy_curve(frac)
        target_remaining = target_total - elapsed
        previous = sequence[-1] if sequence else None
        pick = pick_next(
            remaining=remaining,
            previous=previous,
            reference=reference,
            target_bpm=target_bpm,
            target_energy=target_energy,
            target_remaining=target_remaining,
            max_key_step=max_key_step,
            min_bpm=min_bpm,
            max_bpm=max_bpm,
            allowed_styles=allowed_styles,
            selected=sequence,
        )
        if not pick:
            break
        sequence.append(pick)
        elapsed += pick.length
    return sequence


def build_start_set(reference: Track, tracks: Sequence[Track], target_seconds: int, max_key_step: int,
                    bpm_window: float, allowed_styles: set) -> List[Track]:
    ref_bpm = reference.bpm or 122.0
    min_bpm, max_bpm = (0.0, 999.0) if bpm_window <= 0 else (ref_bpm - bpm_window, ref_bpm + bpm_window)
    remaining = [
        t for t in tracks
        if t.id != reference.id and t.bpm is not None and min_bpm <= t.bpm <= max_bpm and style_allowed(reference, t, allowed_styles)
    ]

    def curve(frac: float) -> float:
        rise = bpm_window if bpm_window > 0 else BPM_RISE_LIMIT
        return ref_bpm + rise * min(1.0, frac / 0.78)

    ref_e = energy_score(reference)

    def energy(frac: float) -> float:
        start = max(0.1, ref_e - 0.10)
        end = min(0.95, ref_e + 0.14)
        t = min(1.0, frac / 0.78)
        return start + (end - start) * t

    return extend_forward([reference], remaining, reference, target_seconds, max_key_step, curve, energy, min_bpm, max_bpm, allowed_styles)


def build_peak_set(reference: Track, tracks: Sequence[Track], target_seconds: int, max_key_step: int,
                   bpm_window: float, allowed_styles: set) -> List[Track]:
    ref_bpm = reference.bpm or 122.0
    min_bpm, max_bpm = (0.0, 999.0) if bpm_window <= 0 else (ref_bpm - bpm_window, ref_bpm + bpm_window)
    remaining = [
        t for t in tracks
        if t.id != reference.id and t.bpm is not None and min_bpm <= t.bpm <= max_bpm and style_allowed(reference, t, allowed_styles)
    ]
    peak_at = int(target_seconds * 0.70)

    reverse_pre = [reference]
    elapsed_pre = reference.length
    while elapsed_pre < peak_at - 120 and remaining:
        frac_from_peak = min(1.0, elapsed_pre / max(1, peak_at))
        fall = bpm_window if bpm_window > 0 else BPM_RISE_LIMIT
        target_bpm = ref_bpm - fall * frac_from_peak
        target_remaining = peak_at - elapsed_pre
        current_first = reverse_pre[-1]

        # Fixed: pass target_energy explicitly. The old call missed this argument,
        # shifted parameters, and sent allowed_styles into max_bpm, causing:
        # TypeError: '>' not supported between instances of 'float' and 'set'.
        pick = pick_next(
            remaining=remaining,
            previous=current_first,
            reference=reference,
            target_bpm=target_bpm,
            target_energy=None,
            target_remaining=target_remaining,
            max_key_step=max_key_step,
            min_bpm=min_bpm,
            max_bpm=max_bpm,
            allowed_styles=allowed_styles,
            selected=reverse_pre,
        )
        if not pick:
            break
        reverse_pre.append(pick)
        elapsed_pre += pick.length

    prelude = list(reversed(reverse_pre[1:]))
    sequence = prelude + [reference]

    def curve(frac: float) -> float:
        fall = bpm_window if bpm_window > 0 else min(BPM_WINDOW_DOWN, BPM_RISE_LIMIT)
        return ref_bpm - fall * frac

    ref_e = energy_score(reference)

    def energy(frac: float) -> float:
        return max(0.1, min(0.95, ref_e - 0.12 * frac))

    return extend_forward(sequence, remaining, reference, target_seconds, max_key_step, curve, energy, min_bpm, max_bpm, allowed_styles)


def write_outputs(playlist: Sequence[Track], set_dir: Path, music_root: Path) -> Tuple[Path, Path, Path]:
    set_dir.mkdir(parents=True, exist_ok=True)
    m3u_path = set_dir / "playlist.m3u"
    csv_path = set_dir / "playlist.csv"
    copied_paths: List[Tuple[Track, Path, Path]] = []

    for i, track in enumerate(playlist, 1):
        src = resolve_track_path(track, music_root)
        if not src or not src.exists():
            raise SystemExit(f"Track file was not found for copying: {label(track)} ({track.path})")
        base_name = safe_filename(label(track), track.filename)
        meta = debug_suffix(track)
        dst = set_dir / f"{i:02d} - {base_name} ({meta}){src.suffix.lower()}"
        copy_index = 2
        while dst.exists():
            dst = set_dir / f"{i:02d} - {base_name} ({meta}) ({copy_index}){src.suffix.lower()}"
            copy_index += 1
        shutil.copy2(src, dst)
        copied_paths.append((track, src, dst))

    with m3u_path.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for t, _, dst in copied_paths:
            f.write(f"#EXTINF:{t.length},{label(t)}\n")
            f.write(f"{dst.name}\n")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "position", "artist", "title", "length", "bpm", "camelot", "genre", "family",
            "energy", "bpm_delta", "camelot_distance", "camelot_relation", "genre_distance",
            "transition_score", "transition_reason", "bitrate", "copied_file", "source_path",
        ])
        for i, (t, src, dst) in enumerate(copied_paths, 1):
            previous = copied_paths[i - 2][0] if i > 1 else None
            bpm_delta = 0.0 if previous is None else abs((previous.bpm or t.bpm or 0.0) - (t.bpm or previous.bpm or 0.0))
            cdist, relation = camelot_relation(previous.key if previous else t.key, t.key)
            gdist = 0.0 if previous is None else genre_distance(previous, t)
            tscore, treason = transition_score(previous, t)
            w.writerow([
                i, t.artist, t.title or t.filename, t.length, round(t.bpm or 0, 1),
                engine_key_to_camelot(t.key), t.genre, ", ".join(sorted(genre_family(t))),
                round(energy_score(t), 2), round(bpm_delta, 1), "" if cdist is None else cdist,
                "anchor" if previous is None else relation, round(gdist, 2), tscore, treason,
                t.bitrate or "", dst.name, str(src),
            ])

    methodology_path = set_dir / "methodology.txt"
    with methodology_path.open("w", encoding="utf-8") as f:
        f.write("Selection methodology\n")
        f.write("- Reads Denon Engine DJ metadata: BPM, key, genre, bitrate, length, path.\n")
        f.write("- Filters candidates by selected style bucket, BPM corridor, and Camelot step limit.\n")
        f.write("- Scores neighboring transitions by BPM delta, Camelot relation, genre distance, and estimated energy.\n")
        f.write("- Fixes peak-set pick_next argument order to prevent float/set comparison errors.\n")
    return set_dir, m3u_path, csv_path


def format_time(seconds: int) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Build a harmonic DJ set from Engine DJ metadata.")
    parser.add_argument("reference", help="Reference audio file already imported/analyzed in Engine DJ.")
    parser.add_argument("--reference-id", type=int, help="Use an Engine DJ Track.id instead of matching by file path.")
    parser.add_argument("--role", choices=["start", "peak"], default="peak", help="Use reference as set opener or peak track.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--library-provider", choices=["denon_engine"], default="denon_engine")
    parser.add_argument("--music-root", default=DEFAULT_MUSIC_ROOT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--minutes", type=int, default=90)
    parser.add_argument("--max-key-step", type=int, default=3)
    parser.add_argument("--bpm-window", type=float, default=5.0, help="Allowed BPM distance from reference. Use 0 for no BPM limit.")
    parser.add_argument("--style-filter", default="", help="Comma-separated style buckets to allow. Empty keeps reference-family behavior.")
    parser.add_argument("--no-copy", action="store_true", help="Do not copy files / write set outputs (build playlist only).")
    parser.add_argument("--emit-playlist-json", action="store_true", help="Print playlist as JSON to stdout (implies --no-copy).")
    args = parser.parse_args(argv)

    music_root = Path(args.music_root)
    with open_db(args.db_path) as con:
        tracks = load_tracks(con, music_root)
    ref = pick_reference_by_id(args.reference_id, tracks) if args.reference_id else pick_reference(Path(args.reference), tracks, args.db_path)
    tracks = dedupe_tracks(tracks, ref.id)

    target_seconds = max(15, int(args.minutes)) * 60
    bpm_window = max(0.0, float(args.bpm_window))
    allowed_styles = parse_style_filter(args.style_filter)
    if args.role == "start":
        playlist = build_start_set(ref, tracks, target_seconds, args.max_key_step, bpm_window, allowed_styles)
    else:
        playlist = build_peak_set(ref, tracks, target_seconds, args.max_key_step, bpm_window, allowed_styles)

    total = sum(t.length for t in playlist)
    date_str = datetime.now().strftime("%d.%m.%y")
    ref_title = (ref.title or "").strip() or ref.filename
    ref_slug = slug(ref_title)
    base_name = safe_filename(f"{reference_genre_slug(ref)}_{date_str}_{ref_slug}", "set")

    if args.emit_playlist_json:
        args.no_copy = True

    if args.no_copy:
        payload = {
            "role": args.role,
            "reference_id": ref.id,
            "tracks": [
                {
                    "id": t.id,
                    "path": (str(resolve_track_path(t, music_root).resolve()) if resolve_track_path(t, music_root) else ""),
                    "artist": t.artist,
                    "title": t.title,
                    "filename": t.filename,
                    "bpm": t.bpm,
                    "key": t.key,
                    "genre": t.genre,
                    "length": t.length,
                }
                for t in playlist
            ],
        }
        if args.emit_playlist_json:
            import json as _json
            print(_json.dumps(payload, ensure_ascii=False))
        else:
            print(f"Role: {args.role}")
            print(f"Reference: {label(ref)} | bpm={ref.bpm:.1f} | camelot={engine_key_to_camelot(ref.key)}")
            print(f"Tracks: {len(playlist)}")
            print(f"Total: {format_time(total)}")
        return 0

    set_dir, m3u_path, csv_path = write_outputs(playlist, Path(args.out_dir) / base_name, music_root)
    print(f"Role: {args.role}")
    print(f"Reference: {label(ref)} | bpm={ref.bpm:.1f} | camelot={engine_key_to_camelot(ref.key)}")
    print(f"Tracks: {len(playlist)}")
    print(f"Total: {format_time(total)}")
    print(f"Set folder: {set_dir}")
    print(f"M3U: {m3u_path}")
    print(f"CSV: {csv_path}")
    print("")
    for i, t in enumerate(playlist, 1):
        marker = " <REF>" if t.id == ref.id else ""
        print(f"{i:02d}. {label(t)} | {format_time(t.length)} | bpm={t.bpm:.1f} | {engine_key_to_camelot(t.key)} | {t.genre}{marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
