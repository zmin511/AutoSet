import argparse
import os
import sqlite3
import sys
from datetime import datetime
from typing import List, Optional, Sequence, Tuple


ENGINE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _now_str() -> str:
    return datetime.now().strftime(ENGINE_TIME_FORMAT)


def _norm_engine_track_path(abs_path: str, music_root: str) -> str:
    abs_path = os.path.abspath(abs_path)
    music_root = os.path.abspath(music_root)
    rel = os.path.relpath(abs_path, music_root).replace("\\", "/")
    # Engine DB обычно хранит путь относительно папки "Engine Library" как "../Music/<...>".
    return f"../Music/{rel}"


def _read_track_paths_from_m3u(m3u_path: str) -> List[str]:
    paths: List[str] = []
    base_dir = os.path.dirname(os.path.abspath(m3u_path))
    with open(m3u_path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not os.path.isabs(line):
                line = os.path.abspath(os.path.join(base_dir, line))
            paths.append(line)
    return paths


def _read_track_paths_from_csv(csv_path: str) -> List[str]:
    # Поддержка:
    # - playlist.csv из нашего билдера (есть колонка source_path)
    # - простого CSV (1 строка = путь, либо путь в 1-й колонке)
    import csv

    paths: List[str] = []
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        has_header = any(h in sample.lower() for h in ("source_path", "filepath", "file_path", "path,"))
        if has_header:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                src = (row.get("source_path") or row.get("path") or row.get("file") or "").strip()
                if not src:
                    continue
                paths.append(src)
        else:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                cell = (row[0] or "").strip()
                if not cell or cell.lower() in {"path", "file", "filepath", "filename"}:
                    continue
                paths.append(cell)
    return paths


def _dedupe_preserve_order(values: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    # Engine, как правило, не полагается на FK-constraint enforcement, но мы включим:
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def _get_preferred_database_uuid(con: sqlite3.Connection) -> str:
    row = con.execute(
        "select databaseUuid, count(*) as c from PlaylistEntity "
        "where databaseUuid is not null and databaseUuid != '' "
        "group by databaseUuid order by c desc limit 1"
    ).fetchone()
    if row and row["databaseUuid"]:
        return str(row["databaseUuid"])
    row = con.execute("select uuid from Information limit 1").fetchone()
    if row and row["uuid"]:
        return str(row["uuid"])
    raise RuntimeError("Не удалось определить databaseUuid (ни из PlaylistEntity, ни из Information.uuid).")


def _find_playlist_by_title(
    con: sqlite3.Connection, parent_list_id: int, title: str
) -> Optional[sqlite3.Row]:
    return con.execute(
        "select * from Playlist where parentListId = ? and title = ?",
        (parent_list_id, title),
    ).fetchone()


def _find_last_child_list_id(con: sqlite3.Connection, parent_list_id: int) -> Optional[int]:
    # Последний элемент — тот, у которого nextListId = 0 (в рамках parentListId).
    row = con.execute(
        "select id from Playlist where parentListId = ? and nextListId = 0",
        (parent_list_id,),
    ).fetchone()
    if not row:
        return None
    return int(row["id"])


def _insert_playlist_row(
    con: sqlite3.Connection,
    parent_list_id: int,
    title: str,
    is_persisted: int,
    is_explicitly_exported: int,
) -> int:
    now = _now_str()
    cur = con.execute(
        "insert into Playlist(title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported) "
        "values (?, ?, ?, 0, ?, ?)",
        (title, parent_list_id, is_persisted, now, is_explicitly_exported),
    )
    new_id = int(cur.lastrowid)
    last_child = _find_last_child_list_id(con, parent_list_id)
    if last_child is not None and last_child != new_id:
        # Важно: _find_last_child_list_id выполнится уже после insert, поэтому если это первый ребёнок,
        # last_child будет new_id.
        con.execute(
            "update Playlist set nextListId = ? where id = ?",
            (new_id, last_child),
        )
    return new_id


def _ensure_folder_path(con: sqlite3.Connection, folder_path: str) -> int:
    # folder_path вида "Event/Sub" (или просто "Event").
    parts = [p.strip() for p in folder_path.replace("\\", "/").split("/") if p.strip()]
    parent_id = 0
    for part in parts:
        existing = _find_playlist_by_title(con, parent_id, part)
        if existing:
            parent_id = int(existing["id"])
            continue

        # По умолчанию папки/плейлисты, созданные руками, обычно имеют isPersisted=1 и isExplicitlyExported=1.
        parent_id = _insert_playlist_row(
            con=con,
            parent_list_id=parent_id,
            title=part,
            is_persisted=1,
            is_explicitly_exported=1,
        )
    return parent_id


def _resolve_folder_path(con: sqlite3.Connection, folder_path: str) -> Optional[int]:
    parts = [p.strip() for p in folder_path.replace("\\", "/").split("/") if p.strip()]
    parent_id = 0
    for part in parts:
        existing = _find_playlist_by_title(con, parent_id, part)
        if not existing:
            return None
        parent_id = int(existing["id"])
    return parent_id


def _lookup_track_ids(
    con: sqlite3.Connection, abs_paths: Sequence[str], music_root: str
) -> Tuple[List[int], List[Tuple[str, str]]]:
    # Returns (track_ids_in_order, missing[(abs, engine_rel)])
    track_ids: List[int] = []
    missing: List[Tuple[str, str]] = []
    for abs_path in abs_paths:
        engine_path = _norm_engine_track_path(abs_path, music_root)
        row = con.execute("select id from Track where path = ?", (engine_path,)).fetchone()
        if not row:
            # fallback: иногда путь в БД может быть абсолютным (встречается редко)
            row = con.execute("select id from Track where path = ?", (os.path.abspath(abs_path),)).fetchone()
        if not row:
            missing.append((abs_path, engine_path))
            continue
        track_ids.append(int(row["id"]))
    return track_ids, missing


def _insert_playlist_entities(
    con: sqlite3.Connection, list_id: int, track_ids: Sequence[int], database_uuid: str
) -> int:
    # Создаём связный список через nextEntityId. Возвращаем id первого элемента.
    next_entity_id = 0
    first_entity_id = 0
    now = _now_str()
    # Engine хранит порядок через nextEntityId, поэтому вставляем с конца.
    for track_id in reversed(track_ids):
        cur = con.execute(
            "insert into PlaylistEntity(listId, trackId, databaseUuid, nextEntityId, membershipReference) "
            "values (?, ?, ?, ?, 0)",
            (list_id, track_id, database_uuid, next_entity_id),
        )
        ent_id = int(cur.lastrowid)
        next_entity_id = ent_id
        first_entity_id = ent_id
    # Обновим lastEditTime у плейлиста.
    con.execute("update Playlist set lastEditTime = ? where id = ?", (now, list_id))
    return first_entity_id


def create_engine_playlist(
    *,
    db_path: str,
    folder_path: str,
    playlist_title: str,
    track_paths: Sequence[str],
    music_root: str,
    dry_run: bool,
) -> None:
    con = _connect(db_path)
    try:
        database_uuid = _get_preferred_database_uuid(con)
        track_paths = _dedupe_preserve_order([os.path.abspath(p) for p in track_paths])
        track_ids, missing = _lookup_track_ids(con, track_paths, music_root)
        if missing:
            msg = ["Не все треки найдены в Engine DB (Track.path)."]
            msg.append("Проверь, что эти файлы уже импортированы в Engine и что music_root задан верно.")
            msg.append("")
            for abs_path, engine_path in missing[:50]:
                msg.append(f"- {abs_path} -> ожидаемый путь в БД: {engine_path}")
            if len(missing) > 50:
                msg.append(f"... и ещё {len(missing) - 50} шт.")
            raise RuntimeError("\n".join(msg))

        if not track_ids:
            raise RuntimeError("Список треков пуст (после фильтрации/поиска в БД).")

        if dry_run:
            parent_id = _resolve_folder_path(con, folder_path)
            existing = None
            if parent_id is not None:
                existing = _find_playlist_by_title(con, parent_id, playlist_title)
            print(f"[dry-run] db={db_path}")
            if parent_id is None:
                print(f"[dry-run] folder='{folder_path}' -> будет создана")
            else:
                print(f"[dry-run] folder='{folder_path}' (parentListId={parent_id})")
            if existing:
                print(f"[dry-run] playlist='{playlist_title}' -> УЖЕ СУЩЕСТВУЕТ (id={existing['id']})")
            else:
                print(f"[dry-run] playlist='{playlist_title}' tracks={len(track_ids)} -> будет создан")
            return

        with con:
            parent_id = _ensure_folder_path(con, folder_path)
            existing = _find_playlist_by_title(con, parent_id, playlist_title)
            if existing:
                raise RuntimeError(
                    f"Плейлист '{playlist_title}' уже существует в '{folder_path}' (id={existing['id']})."
                )

            now = _now_str()
            list_id = _insert_playlist_row(
                con=con,
                parent_list_id=parent_id,
                title=playlist_title,
                is_persisted=1,
                is_explicitly_exported=1,
            )
            _insert_playlist_entities(con, list_id, track_ids, database_uuid)
            con.execute("update Playlist set lastEditTime = ? where id = ?", (now, list_id))
            print(f"Создан плейлист: '{folder_path}/{playlist_title}' (listId={list_id}), треков: {len(track_ids)}")
    finally:
        con.close()


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Создаёт плейлист в Engine DB как ссылки на существующие треки (без копирования файлов). "
            "Порядок треков формируется через PlaylistEntity.nextEntityId."
        )
    )
    p.add_argument(
        "--db",
        required=True,
        help="Путь к Engine SQLite базе (обычно ...\\Engine Library\\Database2\\m.db).",
    )
    p.add_argument(
        "--music-root",
        default=r"F:\Music",
        help="Корневая папка музыки, относительно которой формируется Track.path вида ../Music/<...>.",
    )
    p.add_argument(
        "--folder",
        required=True,
        help="Папка (в дереве плейлистов Engine), например 'Event' или 'Event/Sub'.",
    )
    p.add_argument("--title", required=True, help="Название плейлиста.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--m3u", help="Путь к .m3u/.m3u8 (строки с путями к файлам).")
    src.add_argument("--csv", help="Путь к playlist.csv (1 строка = путь, либо путь в 1-й колонке).")
    src.add_argument("--tracks", nargs="+", help="Список путей к трекам (абсолютные пути).")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Проверяет соответствие треков в БД, но не пишет изменения.",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = _build_arg_parser().parse_args(argv)

    if args.m3u:
        track_paths = _read_track_paths_from_m3u(args.m3u)
    elif args.csv:
        track_paths = _read_track_paths_from_csv(args.csv)
    else:
        track_paths = list(args.tracks or [])

    try:
        create_engine_playlist(
            db_path=args.db,
            folder_path=args.folder,
            playlist_title=args.title,
            track_paths=track_paths,
            music_root=args.music_root,
            dry_run=bool(args.dry_run),
        )
        return 0
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
