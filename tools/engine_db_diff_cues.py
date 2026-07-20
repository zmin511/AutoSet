#!/usr/bin/env python3
"""
Read-only Engine DJ cue/loop storage diff tool for AutoSet.

Workflow:
1. Close Engine DJ.
2. Copy Engine Library/Database2/m.db to before_m.db.
3. Open Engine DJ.
4. Add or edit a cue/loop on one known test track.
5. Close Engine DJ so SQLite changes are flushed.
6. Copy Engine Library/Database2/m.db to after_m.db.
7. Run:
   python -B tools/engine_db_diff_cues.py --before before_m.db --after after_m.db --track-id 123 --out report.json

The script opens both databases with SQLite mode=ro and never writes to Engine DB.
It compares PerformanceData, Track, and tables whose table name or schema mentions
cue, loop, marker, performance, or beat.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

from engine_cue_loop_codec import (
    parse_loops as codec_parse_loops,
    parse_quick_cues as codec_parse_quick_cues,
)
from engine_db_read import open_engine_db_read_only

CANDIDATE_TERMS = ("cue", "loop", "marker", "performance", "beat")
ALWAYS_TABLES = {"PerformanceData", "Track"}
SPECIAL_FIELDS = {"quickCues", "loops", "beatData"}
MAX_CHANGED_ROWS_PER_TABLE = 200
MAX_FIELD_PREVIEW_BYTES = 96
MAX_TEXT_PREVIEW = 400
MAX_NUMERIC_VALUES = 24


def sqlite_ro(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    return open_engine_db_read_only(resolved)


def quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def table_names(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(row["name"]) for row in rows]


def table_schema(con: sqlite3.Connection, table: str) -> dict[str, Any]:
    sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    columns = [dict(row) for row in con.execute(f"PRAGMA table_info({quote_ident(table)})")]
    return {
        "sql": sql["sql"] if sql else "",
        "columns": columns,
        "column_names": [str(col.get("name")) for col in columns],
        "pk_columns": [str(col.get("name")) for col in columns if int(col.get("pk") or 0) > 0],
    }


def is_candidate_table(table: str, schema: dict[str, Any]) -> bool:
    if table in ALWAYS_TABLES:
        return True
    haystack = " ".join([
        table,
        schema.get("sql") or "",
        " ".join(schema.get("column_names") or []),
    ]).casefold()
    return any(term in haystack for term in CANDIDATE_TERMS)


def candidate_tables(before: sqlite3.Connection, after: sqlite3.Connection) -> list[str]:
    names = sorted(set(table_names(before)) | set(table_names(after)))
    out: list[str] = []
    for name in names:
        schemas = []
        for con in (before, after):
            if name in table_names(con):
                schemas.append(table_schema(con, name))
        if name in ALWAYS_TABLES or any(is_candidate_table(name, schema) for schema in schemas):
            out.append(name)
    return out


def track_filter_column(table: str, columns: list[str]) -> str | None:
    lowered = {col.casefold(): col for col in columns}
    if table.casefold() == "track" and "id" in lowered:
        return lowered["id"]
    for key in ("trackid", "track_id", "track id"):
        if key in lowered:
            return lowered[key]
    for col in columns:
        norm = col.replace("_", "").casefold()
        if norm in {"trackid", "trackuuid"}:
            return col
    return None


def row_key_columns(schema: dict[str, Any]) -> tuple[list[str], bool]:
    pk = list(schema.get("pk_columns") or [])
    if pk:
        return pk, False
    return ["__rowid__"], True


def fetch_rows(con: sqlite3.Connection, table: str, schema: dict[str, Any], track_id: str | None) -> dict[str, dict[str, Any]]:
    columns = list(schema.get("column_names") or [])
    key_cols, needs_rowid = row_key_columns(schema)
    select_cols = [quote_ident(col) for col in columns]
    if needs_rowid:
        select_cols.insert(0, "rowid AS __rowid__")
    sql = f"SELECT {', '.join(select_cols)} FROM {quote_ident(table)}"
    params: list[Any] = []
    filter_col = track_filter_column(table, columns) if track_id else None
    if filter_col:
        sql += f" WHERE {quote_ident(filter_col)} = ?"
        params.append(track_id)
    rows: dict[str, dict[str, Any]] = {}
    for row in con.execute(sql, params):
        item = {key: row[key] for key in row.keys()}
        key = json.dumps([item.get(col) for col in key_cols], ensure_ascii=False, default=str)
        rows[key] = item
    return rows


def sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def printable_text(data: bytes) -> str | None:
    for enc in ("utf-8", "utf-16-le", "utf-16-be"):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        if not text:
            continue
        printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
        if printable / max(1, len(text)) >= 0.85:
            return text
    return None


def maybe_json(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except Exception:
        return None


def finite_float(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def aligned_doubles(data: bytes, *, endian: str, offsets: tuple[int, ...] = (0, 4, 8)) -> list[float]:
    fmt = f"{endian}d"
    out: list[float] = []
    for offset in offsets:
        for idx in range(offset, max(0, len(data) - 7), 8):
            try:
                value = struct.unpack(fmt, data[idx : idx + 8])[0]
            except Exception:
                continue
            if not finite_float(value):
                continue
            if abs(value) > 1e12:
                continue
            if abs(value) < 1e-12 or abs(value - 1.0) < 1e-12 or abs(value + 1.0) < 1e-12:
                continue
            out.append(round(float(value), 6))
            if len(out) >= MAX_NUMERIC_VALUES:
                return out
    return out


def decode_engine_zlib(blob: bytes) -> dict[str, Any] | None:
    if len(blob) < 6:
        return None
    try:
        expected = struct.unpack(">I", blob[:4])[0]
        raw = zlib.decompress(blob[4:])
    except Exception:
        return None
    return {
        "expected_len": expected,
        "actual_len": len(raw),
        "sha256_16": sha16(raw),
        "first_hex": raw[:MAX_FIELD_PREVIEW_BYTES].hex(),
        "text_preview": (printable_text(raw) or "")[:MAX_TEXT_PREVIEW] or None,
        "doubles_be": aligned_doubles(raw, endian=">"),
        "doubles_le": aligned_doubles(raw, endian="<"),
    }


def parse_quick_cues(blob: bytes) -> dict[str, Any] | None:
    decoded = decode_engine_zlib(blob)
    if not decoded:
        return None
    try:
        cues = codec_parse_quick_cues(blob)
    except Exception:
        return {"zlib": decoded}
    return {
        "zlib": decoded,
        "slots": cues.slot_count,
        "trailing_len": len(cues.trailing_bytes),
        "items": [
            {"slot": item.slot, "label": item.label, "pos_raw": item.pos_raw, "color": item.color}
            for item in cues.slots[:16]
        ],
    }

def parse_beat_data(blob: bytes) -> dict[str, Any] | None:
    decoded = decode_engine_zlib(blob)
    if not decoded:
        return None
    raw = zlib.decompress(blob[4:])
    count = None
    if len(raw) >= 8:
        try:
            count = int(struct.unpack(">Q", raw[:8])[0])
        except Exception:
            count = None
    return {"zlib": decoded, "declared_count_be_u64": count}


def parse_loops(blob: bytes) -> dict[str, Any] | None:
    try:
        loops = codec_parse_loops(blob)
    except Exception:
        return None
    return {
        "slots_le_u32": loops.slot_count,
        "unknown_le_u32": loops.unknown_u32,
        "trailing_len": len(loops.trailing_bytes),
        "items": [
            {
                "slot": item.slot,
                "label": item.label,
                "start_raw": item.start_raw,
                "end_raw": item.end_raw,
                "enabled_bytes": [item.enabled_1, item.enabled_2],
                "color": item.color,
            }
            for item in loops.slots[:16]
        ],
    }

def summarize_blob(blob: bytes, field_name: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "blob",
        "len": len(blob),
        "sha256_16": sha16(blob),
        "first_hex": blob[:MAX_FIELD_PREVIEW_BYTES].hex(),
    }
    text = printable_text(blob)
    if text is not None:
        out["text_preview"] = text[:MAX_TEXT_PREVIEW]
        parsed = maybe_json(text)
        if parsed is not None:
            out["json"] = parsed
    zlib_info = decode_engine_zlib(blob)
    if zlib_info:
        out["engine_zlib"] = zlib_info

    if field_name == "quickCues":
        out["quickCues_parse"] = parse_quick_cues(blob)
    elif field_name == "beatData":
        out["beatData_parse"] = parse_beat_data(blob)
    elif field_name == "loops":
        out["loops_parse"] = parse_loops(blob)
    return out


def summarize_value(value: Any, field_name: str = "") -> dict[str, Any]:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bytes):
        return summarize_blob(value, field_name)
    if isinstance(value, (int, float)):
        return {"type": type(value).__name__, "value": value}
    text = str(value)
    out: dict[str, Any] = {
        "type": "text",
        "len": len(text),
        "sha256_16": sha16(text.encode("utf-8", errors="replace")),
        "preview": text[:MAX_TEXT_PREVIEW],
    }
    parsed = maybe_json(text)
    if parsed is not None:
        out["json"] = parsed
    return out


def row_digest(row: dict[str, Any]) -> str:
    h = hashlib.sha256()
    for key in sorted(row.keys()):
        h.update(str(key).encode("utf-8", errors="replace"))
        h.update(b"=")
        value = row[key]
        if isinstance(value, bytes):
            h.update(value)
        else:
            h.update(repr(value).encode("utf-8", errors="replace"))
        h.update(b"\0")
    return h.hexdigest()


def compare_rows(before_row: dict[str, Any], after_row: dict[str, Any]) -> dict[str, Any]:
    before_cols = set(before_row.keys()) - {"__rowid__"}
    after_cols = set(after_row.keys()) - {"__rowid__"}
    fields: dict[str, Any] = {}
    for col in sorted(before_cols | after_cols):
        before_value = before_row.get(col)
        after_value = after_row.get(col)
        if before_value == after_value:
            continue
        fields[col] = {
            "before": summarize_value(before_value, col),
            "after": summarize_value(after_value, col),
            "special": col in SPECIAL_FIELDS,
        }
    return fields


def compare_table(before: sqlite3.Connection, after: sqlite3.Connection, table: str, track_id: str | None) -> dict[str, Any]:
    before_tables = set(table_names(before))
    after_tables = set(table_names(after))
    item: dict[str, Any] = {"table": table, "changed": False}
    if table not in before_tables:
        item.update({"changed": True, "status": "added_table"})
        return item
    if table not in after_tables:
        item.update({"changed": True, "status": "deleted_table"})
        return item

    before_schema = table_schema(before, table)
    after_schema = table_schema(after, table)
    item["schema"] = {
        "before_columns": before_schema.get("column_names") or [],
        "after_columns": after_schema.get("column_names") or [],
        "changed": before_schema.get("sql") != after_schema.get("sql"),
    }
    item["track_filter_column"] = track_filter_column(table, after_schema.get("column_names") or []) if track_id else None

    before_rows = fetch_rows(before, table, before_schema, track_id)
    after_rows = fetch_rows(after, table, after_schema, track_id)
    added = sorted(set(after_rows) - set(before_rows))
    deleted = sorted(set(before_rows) - set(after_rows))
    changed_rows: list[dict[str, Any]] = []
    for key in sorted(set(before_rows) & set(after_rows)):
        if row_digest(before_rows[key]) == row_digest(after_rows[key]):
            continue
        fields = compare_rows(before_rows[key], after_rows[key])
        if fields:
            changed_rows.append({"key": json.loads(key), "fields": fields})
            if len(changed_rows) >= MAX_CHANGED_ROWS_PER_TABLE:
                break

    item.update({
        "before_row_count": len(before_rows),
        "after_row_count": len(after_rows),
        "added_rows": [json.loads(key) for key in added[:MAX_CHANGED_ROWS_PER_TABLE]],
        "deleted_rows": [json.loads(key) for key in deleted[:MAX_CHANGED_ROWS_PER_TABLE]],
        "changed_rows": changed_rows,
        "truncated": len(changed_rows) >= MAX_CHANGED_ROWS_PER_TABLE,
    })
    item["changed"] = bool(item["schema"]["changed"] or added or deleted or changed_rows)
    return item


def build_report(before_path: Path, after_path: Path, track_id: str | None) -> dict[str, Any]:
    with sqlite_ro(before_path) as before, sqlite_ro(after_path) as after:
        candidates = candidate_tables(before, after)
        tables = [compare_table(before, after, table, track_id) for table in candidates]
    return {
        "ok": True,
        "mode": "read_only",
        "before": str(before_path),
        "after": str(after_path),
        "track_id": track_id,
        "candidate_terms": list(CANDIDATE_TERMS),
        "candidate_tables": candidates,
        "changed_tables": [table["table"] for table in tables if table.get("changed")],
        "tables": tables,
    }


def print_summary(report: dict[str, Any]) -> None:
    print("Engine DJ cue/loop DB diff (read-only)")
    print(f"before: {report['before']}")
    print(f"after : {report['after']}")
    if report.get("track_id"):
        print(f"track : {report['track_id']}")
    print(f"candidate tables: {len(report.get('candidate_tables') or [])}")
    changed = report.get("changed_tables") or []
    print(f"changed tables: {len(changed)}")
    for table in report.get("tables") or []:
        if not table.get("changed"):
            continue
        print(f"\n- {table['table']}")
        if table.get("status"):
            print(f"  status: {table['status']}")
            continue
        if table.get("track_filter_column"):
            print(f"  track filter: {table['track_filter_column']}")
        schema = table.get("schema") or {}
        if schema.get("changed"):
            print("  schema changed")
        print(f"  rows before/after: {table.get('before_row_count')} / {table.get('after_row_count')}")
        if table.get("added_rows"):
            print(f"  added rows: {len(table['added_rows'])}")
        if table.get("deleted_rows"):
            print(f"  deleted rows: {len(table['deleted_rows'])}")
        for row in table.get("changed_rows") or []:
            fields = row.get("fields") or {}
            special = [name for name, info in fields.items() if info.get("special")]
            field_names = ", ".join(fields.keys())
            print(f"  changed row {row.get('key')}: {field_names}")
            if special:
                print(f"    special cue/loop/beat fields: {', '.join(special)}")
        if table.get("truncated"):
            print(f"  output truncated at {MAX_CHANGED_ROWS_PER_TABLE} changed rows")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only diff of Engine DJ cue/loop storage between two m.db copies.")
    parser.add_argument("--before", required=True, type=Path, help="Path to before m.db copy")
    parser.add_argument("--after", required=True, type=Path, help="Path to after m.db copy")
    parser.add_argument("--track-id", default=None, help="Optional Engine Track.id to narrow relevant tables")
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON report path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(args.before, args.after, str(args.track_id) if args.track_id is not None else None)
    print_summary(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
