import argparse
import csv
import json
import os
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from shutil import copy2
from typing import Iterable, Optional
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import musicbrainzngs
from mutagen.id3 import ID3, ID3NoHeaderError, TCON, TPE1, TIT2, TALB


@dataclass(frozen=True)
class TrackKey:
    artist: str
    title: str


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _clean_title_from_filename(title: str) -> str:
    # Remove common DJ suffixes that hurt matching.
    title = re.sub(r"\s*\((?:radio edit|extended mix|original mix|club mix|remix|bootleg|edit|dub|mix)\)\s*$", "", title, flags=re.I)
    title = re.sub(r"\s*\((?:backing track|karaoke|instrumental)\)(?:\s*\(.*?mdx.*?\))*\s*$", "", title, flags=re.I)
    title = re.sub(r"\s*\(.*?mdx.*?\)\s*$", "", title, flags=re.I)
    title = re.sub(r"\s*\(.*?voc\s*ft.*?\)\s*$", "", title, flags=re.I)
    title = re.sub(r"\s*\[(?:mixed|acapella|instrumental).*?\]\s*$", "", title, flags=re.I)
    title = re.sub(r"\s*\(\d+\)\s*$", "", title)
    return _norm_space(title)


def guess_artist_title_from_path(path: str) -> Optional[TrackKey]:
    base = os.path.splitext(os.path.basename(path))[0]
    base = base.replace("–", "-").replace("—", "-")
    base = re.sub(r"^\._+", "", base).strip()
    m = re.match(r"^\s*(?P<artist>.+?)\s*-\s*(?P<title>.+?)\s*$", base)
    if not m:
        return None
    artist = _norm_space(m.group("artist"))
    artist = re.sub(r"^\._+", "", artist).strip()
    title = _clean_title_from_filename(_norm_space(m.group("title")))
    if not artist or not title:
        return None
    return TrackKey(artist=artist, title=title)


def read_id3_artist_title(path: str) -> Optional[TrackKey]:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return None
    artist = tags.get("TPE1")
    title = tags.get("TIT2")
    if not artist or not title:
        return None
    a = _norm_space(str(artist))
    t = _norm_space(str(title))
    if not a or not t:
        return None
    return TrackKey(artist=a, title=_clean_title_from_filename(t))


def read_existing_genres(path: str) -> list[str]:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return []
    frame = tags.get("TCON")
    if not frame:
        return []
    # Mutagen stores multi-values in .text list.
    genres: list[str] = []
    for g in getattr(frame, "text", []) or []:
        g = _norm_space(str(g))
        if g:
            genres.append(g)
    # De-dupe preserving order.
    out: list[str] = []
    seen = set()
    for g in genres:
        k = g.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(g)
    return out


def write_genres(path: str, genres: list[str]) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("TCON")
    tags.add(TCON(encoding=3, text=genres))
    tags.save(path)


def mb_init(user_agent: str) -> None:
    musicbrainzngs.set_useragent("codex-mp3-tagger", "0.1", user_agent)
    musicbrainzngs.set_rate_limit(limit_or_interval=1.0, new_requests=1)


def mb_genres_for_track(key: TrackKey, min_score: int, limit: int, sleep_s: float) -> list[str]:
    # Search recording with artist+title.
    result = musicbrainzngs.search_recordings(
        artist=key.artist,
        recording=key.title,
        limit=limit,
    )
    recs = result.get("recording-list", [])
    best = None
    best_score = -1
    for r in recs:
        score = int(r.get("ext:score", 0))
        if score > best_score:
            best_score = score
            best = r
    if not best or best_score < min_score:
        return []

    rec_id = best.get("id")
    if not rec_id:
        return []

    # Fetch tags for recording.
    time.sleep(sleep_s)
    rec = musicbrainzngs.get_recording_by_id(rec_id, includes=["tags"]).get("recording", {})
    tags = rec.get("tag-list", []) or []
    genres: list[str] = []
    for t in tags:
        name = _norm_space(t.get("name", ""))
        if name:
            genres.append(name)
    # De-dupe.
    out: list[str] = []
    seen = set()
    for g in genres:
        k = g.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(g)
    return out


def _norm_cmp(s: str) -> str:
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.U)
    return _norm_space(s)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm_cmp(a), _norm_cmp(b)).ratio()


def itunes_genres_for_track(key: TrackKey, limit: int, timeout_s: float) -> list[str]:
    q = quote_plus(f"{key.artist} {key.title}")
    url = f"https://itunes.apple.com/search?term={q}&entity=song&limit={limit}"
    req = Request(url, headers={"User-Agent": "codex-mp3-tagger/0.1"})
    with urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    results = payload.get("results", []) or []
    best = None
    best_score = 0.0
    for r in results:
        artist = r.get("artistName", "") or ""
        title = r.get("trackName", "") or ""
        if not artist or not title:
            continue
        s = 0.6 * _similar(key.artist, artist) + 0.4 * _similar(key.title, title)
        if s > best_score:
            best_score = s
            best = r

    if not best or best_score < 0.78:
        return []

    g = _norm_space(str(best.get("primaryGenreName", "") or ""))
    return [g] if g else []


def iter_mp3_files(root: str, from_list: Optional[str]) -> Iterable[str]:
    if from_list:
        with open(from_list, "r", encoding="utf-8") as f:
            for line in f:
                p = line.strip()
                if not p:
                    continue
                yield p
        return

    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".mp3"):
                yield os.path.join(dirpath, fn)


def main() -> int:
    ap = argparse.ArgumentParser(description="Enrich MP3 genres using MusicBrainz (append-only).")
    ap.add_argument("--root", default=".", help="Root folder to scan (default: current dir).")
    ap.add_argument("--user-agent-email", required=True, help="Your email for MusicBrainz User-Agent.")
    ap.add_argument("--min-score", type=int, default=90, help="Minimum MusicBrainz match score.")
    ap.add_argument("--max-new-genres", type=int, default=3, help="Max number of genres to append from MusicBrainz.")
    ap.add_argument("--sleep", type=float, default=1.1, help="Sleep between MB requests (seconds).")
    ap.add_argument("--report", default="genre_enrich_report.csv", help="CSV report path.")
    ap.add_argument("--apply", action="store_true", help="Actually write tags. Without this, dry-run only.")
    ap.add_argument("--only-missing-genre", action="store_true", help="Only process files with no existing genre tag.")
    ap.add_argument("--from-list", help="Optional text file containing absolute MP3 paths (one per line).")
    ap.add_argument("--max-files", type=int, default=0, help="Optional cap on number of files to process (0 = no cap).")
    ap.add_argument("--source", choices=["musicbrainz", "itunes", "auto"], default="auto", help="Genre source.")
    ap.add_argument("--backup-dir", help="Optional directory to store backups of modified files.")
    args = ap.parse_args()

    mb_init(args.user_agent_email)

    processed = 0
    updated = 0
    with open(args.report, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path", "artist", "title", "existing_genres", "new_genres", "final_genres", "action"])

        for path in iter_mp3_files(args.root, args.from_list):
            if args.max_files and processed >= args.max_files:
                break
            processed += 1

            existing = read_existing_genres(path)
            if args.only_missing_genre and existing:
                continue

            key = read_id3_artist_title(path) or guess_artist_title_from_path(path)
            if not key:
                w.writerow([path, "", "", ";".join(existing), "", ";".join(existing), "skip_no_artist_title"])
                continue

            genres: list[str] = []
            source_used = ""
            if args.source in ("musicbrainz", "auto"):
                try:
                    genres = mb_genres_for_track(key, min_score=args.min_score, limit=5, sleep_s=args.sleep)
                    source_used = "musicbrainz"
                except Exception:
                    genres = []
                    source_used = "musicbrainz_error"

            if not genres and args.source in ("itunes", "auto"):
                try:
                    time.sleep(0.2)
                    genres = itunes_genres_for_track(key, limit=5, timeout_s=20.0)
                    source_used = "itunes"
                except Exception:
                    genres = []
                    source_used = "itunes_error"

            if not genres:
                w.writerow([path, key.artist, key.title, ";".join(existing), "", ";".join(existing), f"no_match_or_no_genres:{source_used}"])
                continue

            # Append-only, unique.
            final = list(existing)
            existing_keys = {g.casefold() for g in existing}
            new_added: list[str] = []
            for g in genres:
                if len(new_added) >= args.max_new_genres:
                    break
                if g.casefold() in existing_keys:
                    continue
                existing_keys.add(g.casefold())
                final.append(g)
                new_added.append(g)

            if not new_added:
                w.writerow([path, key.artist, key.title, ";".join(existing), "", ";".join(final), "already_has_all"])
                continue

            action = "would_update"
            if args.apply:
                if args.backup_dir:
                    os.makedirs(args.backup_dir, exist_ok=True)
                    backup_name = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(path))
                    backup_path = os.path.join(args.backup_dir, backup_name)
                    if not os.path.exists(backup_path):
                        copy2(path, backup_path)
                write_genres(path, final)
                updated += 1
                action = "updated"

            w.writerow([path, key.artist, key.title, ";".join(existing), ";".join(new_added), ";".join(final), action])

    print(f"processed={processed}")
    print(f"updated={updated}")
    print(f"report={os.path.abspath(args.report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
