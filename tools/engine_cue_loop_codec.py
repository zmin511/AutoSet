#!/usr/bin/env python3
"""
Read-only Engine DJ quickCues/loops codec diagnostics for AutoSet.

Purpose:
- Decode PerformanceData.quickCues and PerformanceData.loops.
- Build them back for byte/payload round-trip checks.
- Provide dry-run position diagnostics for future Track Prep export.

Workflow to confirm seconds_to_raw before any real exporter exists:
1. Close Engine DJ.
2. Copy Engine Library/Database2/m.db to before_m.db.
3. Open Engine DJ.
4. Put one cue at a known time, for example exactly 30.000 sec.
5. Optionally create one saved loop with known start/end times.
6. Close Engine DJ.
7. Copy Engine Library/Database2/m.db to after_m.db.
8. Run tools/engine_db_diff_cues.py on the two copies.
9. Compare known seconds with cue pos_raw and loop start_raw/end_raw.

This tool opens SQLite with mode=ro and never writes Engine DB.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import struct
import sys
import zlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

MAX_ENGINE_SLOTS = 32
DEFAULT_CUE_SLOTS = 8
DEFAULT_LOOP_SLOTS = 8
EMPTY_RAW = -1.0
DEFAULT_COLOR = 0
RAW_SCALE_CANDIDATES = (
    ("seconds", 1.0, "raw = seconds"),
    ("milliseconds", 1.0 / 1000.0, "raw = seconds * 1000"),
    ("frames44100", 1.0 / 44100.0, "raw = seconds * 44100"),
    ("frames48000", 1.0 / 48000.0, "raw = seconds * 48000"),
)


def finite_number(value: Any) -> bool:
    try:
        number = float(value)
    except Exception:
        return False
    return number == number and number not in (float("inf"), float("-inf"))


def decode_engine_zlib_blob(blob: bytes | None) -> bytes | None:
    if not blob or len(blob) < 6:
        return None
    try:
        expected = struct.unpack(">I", blob[:4])[0]
        payload = zlib.decompress(blob[4:])
    except Exception:
        return None
    if expected != len(payload):
        # Engine blobs carry the decompressed length as the first big-endian u32.
        # Keep the payload anyway for diagnostics; round-trip will expose mismatch.
        pass
    return payload


def encode_engine_zlib_blob(payload: bytes) -> bytes:
    payload = bytes(payload or b"")
    return struct.pack(">I", len(payload)) + zlib.compress(payload)


def _decode_label(data: bytes) -> str:
    return bytes(data or b"").decode("utf-8", "replace")


def _label_bytes(label: str, original: bytes = b"") -> bytes:
    original = bytes(original or b"")
    if original and _decode_label(original) == str(label or ""):
        return original
    encoded = str(label or "").encode("utf-8")
    if len(encoded) > 255:
        raise ValueError("Engine cue/loop labels must fit in one length byte")
    return encoded


def _color(value: int | None) -> int:
    return DEFAULT_COLOR if value is None else int(value) & 0xFFFFFFFF


def _is_empty_raw(value: float) -> bool:
    if not finite_number(value):
        return True
    return float(value) <= 0.0 or abs(float(value) - EMPTY_RAW) < 1e-9


@dataclass
class QuickCueSlot:
    slot: int
    label: str = ""
    pos_raw: float = EMPTY_RAW
    color: int | None = DEFAULT_COLOR
    label_bytes: bytes = field(default=b"", repr=False)

    @property
    def empty(self) -> bool:
        return _is_empty_raw(self.pos_raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "empty": self.empty,
            "label": self.label,
            "pos_raw": self.pos_raw,
            "color": self.color,
            "color_hex": None if self.color is None else f"#{int(self.color) & 0xFFFFFF:06x}",
        }


@dataclass
class QuickCuesBlob:
    slot_count: int
    slots: list[QuickCueSlot]
    trailing_bytes: bytes = field(default=b"", repr=False)
    payload: bytes | None = field(default=None, repr=False)
    blob: bytes | None = field(default=None, repr=False)

    def slot(self, slot: int) -> QuickCueSlot:
        for item in self.slots:
            if item.slot == int(slot):
                return item
        raise IndexError(f"quick cue slot {slot} not found")

    def with_slot(self, slot: int, *, label: str | None = None, pos_raw: float | None = None, color: int | None = None) -> "QuickCuesBlob":
        next_slots: list[QuickCueSlot] = []
        found = False
        for item in self.slots:
            if item.slot == int(slot):
                found = True
                next_slots.append(replace(
                    item,
                    label=item.label if label is None else str(label),
                    pos_raw=item.pos_raw if pos_raw is None else float(pos_raw),
                    color=item.color if color is None else int(color),
                ))
            else:
                next_slots.append(item)
        if not found:
            raise IndexError(f"quick cue slot {slot} not found")
        return replace(self, slots=next_slots, payload=None, blob=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_count": self.slot_count,
            "slots": [slot.to_dict() for slot in self.slots],
            "trailing_len": len(self.trailing_bytes),
        }


@dataclass
class LoopSlot:
    slot: int
    label: str = ""
    start_raw: float = EMPTY_RAW
    end_raw: float = EMPTY_RAW
    enabled_1: int = 0
    enabled_2: int = 0
    color: int | None = DEFAULT_COLOR
    label_bytes: bytes = field(default=b"", repr=False)

    @property
    def empty(self) -> bool:
        return _is_empty_raw(self.start_raw) or _is_empty_raw(self.end_raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "empty": self.empty,
            "label": self.label,
            "start_raw": self.start_raw,
            "end_raw": self.end_raw,
            "enabled_bytes": [self.enabled_1, self.enabled_2],
            "color": self.color,
            "color_hex": None if self.color is None else f"#{int(self.color) & 0xFFFFFF:06x}",
        }


@dataclass
class LoopsBlob:
    slot_count: int
    unknown_u32: int
    slots: list[LoopSlot]
    trailing_bytes: bytes = field(default=b"", repr=False)
    blob: bytes | None = field(default=None, repr=False)

    def slot(self, slot: int) -> LoopSlot:
        for item in self.slots:
            if item.slot == int(slot):
                return item
        raise IndexError(f"loop slot {slot} not found")

    def with_slot(
        self,
        slot: int,
        *,
        label: str | None = None,
        start_raw: float | None = None,
        end_raw: float | None = None,
        color: int | None = None,
        enabled_1: int | None = None,
        enabled_2: int | None = None,
    ) -> "LoopsBlob":
        next_slots: list[LoopSlot] = []
        found = False
        for item in self.slots:
            if item.slot == int(slot):
                found = True
                next_slots.append(replace(
                    item,
                    label=item.label if label is None else str(label),
                    start_raw=item.start_raw if start_raw is None else float(start_raw),
                    end_raw=item.end_raw if end_raw is None else float(end_raw),
                    color=item.color if color is None else int(color),
                    enabled_1=item.enabled_1 if enabled_1 is None else int(enabled_1) & 0xFF,
                    enabled_2=item.enabled_2 if enabled_2 is None else int(enabled_2) & 0xFF,
                ))
            else:
                next_slots.append(item)
        if not found:
            raise IndexError(f"loop slot {slot} not found")
        return replace(self, slots=next_slots, blob=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_count": self.slot_count,
            "unknown_u32": self.unknown_u32,
            "slots": [slot.to_dict() for slot in self.slots],
            "trailing_len": len(self.trailing_bytes),
        }


def empty_quick_cues(slot_count: int = DEFAULT_CUE_SLOTS) -> QuickCuesBlob:
    return QuickCuesBlob(
        slot_count=slot_count,
        slots=[QuickCueSlot(slot=i, pos_raw=EMPTY_RAW, color=DEFAULT_COLOR) for i in range(1, slot_count + 1)],
    )


def empty_loops(slot_count: int = DEFAULT_LOOP_SLOTS) -> LoopsBlob:
    return LoopsBlob(
        slot_count=slot_count,
        unknown_u32=0,
        slots=[LoopSlot(slot=i, start_raw=EMPTY_RAW, end_raw=EMPTY_RAW, color=DEFAULT_COLOR) for i in range(1, slot_count + 1)],
    )


def parse_quick_cues(blob: bytes | None) -> QuickCuesBlob:
    payload = decode_engine_zlib_blob(blob)
    if payload is None:
        raise ValueError("quickCues is empty or not an Engine zlib blob")
    if len(payload) < 8:
        raise ValueError("quickCues payload is too short")
    slot_count = int(struct.unpack(">Q", payload[:8])[0])
    if slot_count <= 0 or slot_count > MAX_ENGINE_SLOTS:
        raise ValueError(f"unsupported quickCues slot count: {slot_count}")
    offset = 8
    slots: list[QuickCueSlot] = []
    for slot_num in range(1, slot_count + 1):
        if offset >= len(payload):
            raise ValueError(f"quickCues ended before slot {slot_num}")
        label_len = int(payload[offset])
        offset += 1
        if offset + label_len > len(payload):
            raise ValueError(f"quickCues label overruns slot {slot_num}")
        label_raw = payload[offset : offset + label_len]
        offset += label_len
        if offset + 8 > len(payload):
            raise ValueError(f"quickCues position missing for slot {slot_num}")
        pos_raw = float(struct.unpack(">d", payload[offset : offset + 8])[0])
        offset += 8
        color = None
        if offset + 4 <= len(payload):
            color = int(struct.unpack(">I", payload[offset : offset + 4])[0])
            offset += 4
        slots.append(QuickCueSlot(
            slot=slot_num,
            label=_decode_label(label_raw),
            pos_raw=pos_raw,
            color=color,
            label_bytes=label_raw,
        ))
    return QuickCuesBlob(
        slot_count=slot_count,
        slots=slots,
        trailing_bytes=payload[offset:],
        payload=payload,
        blob=bytes(blob or b""),
    )


def build_quick_cues(cues: QuickCuesBlob | Iterable[QuickCueSlot]) -> bytes:
    if isinstance(cues, QuickCuesBlob):
        slot_count = int(cues.slot_count)
        slots = list(cues.slots)
        trailing = bytes(cues.trailing_bytes or b"")
    else:
        slots = sorted(list(cues), key=lambda item: item.slot)
        slot_count = len(slots)
        trailing = b""
    if slot_count <= 0 or slot_count > MAX_ENGINE_SLOTS:
        raise ValueError(f"unsupported quick cue slot count: {slot_count}")
    if len(slots) != slot_count:
        raise ValueError("quick cue slot list does not match slot_count")
    out = bytearray(struct.pack(">Q", slot_count))
    for expected_slot, slot in enumerate(slots, start=1):
        if int(slot.slot) != expected_slot:
            raise ValueError("quick cue slots must be contiguous and 1-based")
        label_raw = _label_bytes(slot.label, slot.label_bytes)
        out.append(len(label_raw))
        out.extend(label_raw)
        out.extend(struct.pack(">d", float(slot.pos_raw)))
        out.extend(struct.pack(">I", _color(slot.color)))
    out.extend(trailing)
    return encode_engine_zlib_blob(bytes(out))


def parse_loops(blob: bytes | None) -> LoopsBlob:
    if not blob or len(blob) < 8:
        raise ValueError("loops is empty or too short")
    data = bytes(blob)
    slot_count = int(struct.unpack("<I", data[:4])[0])
    unknown = int(struct.unpack("<I", data[4:8])[0])
    if slot_count <= 0 or slot_count > MAX_ENGINE_SLOTS:
        raise ValueError(f"unsupported loop slot count: {slot_count}")
    offset = 8
    slots: list[LoopSlot] = []
    for slot_num in range(1, slot_count + 1):
        if offset >= len(data):
            raise ValueError(f"loops ended before slot {slot_num}")
        label_len = int(data[offset])
        offset += 1
        if offset + label_len > len(data):
            raise ValueError(f"loop label overruns slot {slot_num}")
        label_raw = data[offset : offset + label_len]
        offset += label_len
        if offset + 16 > len(data):
            raise ValueError(f"loop positions missing for slot {slot_num}")
        start_raw = float(struct.unpack("<d", data[offset : offset + 8])[0])
        end_raw = float(struct.unpack("<d", data[offset + 8 : offset + 16])[0])
        offset += 16
        enabled_1 = 0
        enabled_2 = 0
        color = None
        if offset + 6 <= len(data):
            enabled_1 = int(data[offset])
            enabled_2 = int(data[offset + 1])
            offset += 2
            color = int(struct.unpack(">I", data[offset : offset + 4])[0])
            offset += 4
        slots.append(LoopSlot(
            slot=slot_num,
            label=_decode_label(label_raw),
            start_raw=start_raw,
            end_raw=end_raw,
            enabled_1=enabled_1,
            enabled_2=enabled_2,
            color=color,
            label_bytes=label_raw,
        ))
    return LoopsBlob(
        slot_count=slot_count,
        unknown_u32=unknown,
        slots=slots,
        trailing_bytes=data[offset:],
        blob=data,
    )


def build_loops(loops: LoopsBlob | Iterable[LoopSlot]) -> bytes:
    if isinstance(loops, LoopsBlob):
        slot_count = int(loops.slot_count)
        unknown = int(loops.unknown_u32) & 0xFFFFFFFF
        slots = list(loops.slots)
        trailing = bytes(loops.trailing_bytes or b"")
    else:
        slots = sorted(list(loops), key=lambda item: item.slot)
        slot_count = len(slots)
        unknown = 0
        trailing = b""
    if slot_count <= 0 or slot_count > MAX_ENGINE_SLOTS:
        raise ValueError(f"unsupported loop slot count: {slot_count}")
    if len(slots) != slot_count:
        raise ValueError("loop slot list does not match slot_count")
    out = bytearray(struct.pack("<I", slot_count))
    out.extend(struct.pack("<I", unknown))
    for expected_slot, slot in enumerate(slots, start=1):
        if int(slot.slot) != expected_slot:
            raise ValueError("loop slots must be contiguous and 1-based")
        label_raw = _label_bytes(slot.label, slot.label_bytes)
        out.append(len(label_raw))
        out.extend(label_raw)
        out.extend(struct.pack("<d", float(slot.start_raw)))
        out.extend(struct.pack("<d", float(slot.end_raw)))
        out.append(int(slot.enabled_1) & 0xFF)
        out.append(int(slot.enabled_2) & 0xFF)
        out.extend(struct.pack(">I", _color(slot.color)))
    out.extend(trailing)
    return bytes(out)


def round_trip_quick_cues(blob: bytes | None) -> dict[str, Any]:
    if not blob:
        return {"present": False, "ok": True, "message": "quickCues is NULL/empty"}
    parsed = parse_quick_cues(blob)
    rebuilt = build_quick_cues(parsed)
    original_payload = decode_engine_zlib_blob(blob)
    rebuilt_payload = decode_engine_zlib_blob(rebuilt)
    payload_equal = original_payload == rebuilt_payload
    blob_equal = bytes(blob) == rebuilt
    return {
        "present": True,
        "ok": payload_equal,
        "blob_equal": blob_equal,
        "payload_equal": payload_equal,
        "slot_count": parsed.slot_count,
        "trailing_len": len(parsed.trailing_bytes),
        "original_blob_len": len(blob),
        "rebuilt_blob_len": len(rebuilt),
    }


def round_trip_loops(blob: bytes | None) -> dict[str, Any]:
    if not blob:
        return {"present": False, "ok": True, "message": "loops is NULL/empty"}
    parsed = parse_loops(blob)
    rebuilt = build_loops(parsed)
    blob_equal = bytes(blob) == rebuilt
    return {
        "present": True,
        "ok": blob_equal,
        "blob_equal": blob_equal,
        "slot_count": parsed.slot_count,
        "trailing_len": len(parsed.trailing_bytes),
        "original_blob_len": len(blob),
        "rebuilt_blob_len": len(rebuilt),
    }


def sqlite_ro(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    con = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_track_payload(db_path: Path, track_id: int) -> dict[str, Any]:
    with sqlite_ro(db_path) as con:
        row = con.execute(
            """
            SELECT
              Track.id,
              Track.title,
              Track.artist,
              Track.filename,
              Track.length,
              Track.bpmAnalyzed,
              Track.bpm,
              Track.lastEditTime,
              PerformanceData.quickCues,
              PerformanceData.loops
            FROM Track
            LEFT JOIN PerformanceData ON PerformanceData.trackId = Track.id
            WHERE Track.id = ?
            """,
            (int(track_id),),
        ).fetchone()
    if not row:
        raise ValueError(f"track_id {track_id} not found")
    return {key: row[key] for key in row.keys()}


def positive_raw_values(cues: QuickCuesBlob | None, loops: LoopsBlob | None) -> list[float]:
    values: list[float] = []
    if cues:
        values.extend(float(slot.pos_raw) for slot in cues.slots if not slot.empty and finite_number(slot.pos_raw))
    if loops:
        for slot in loops.slots:
            if not slot.empty:
                values.extend([float(slot.start_raw), float(slot.end_raw)])
    return [value for value in values if value > 0.0 and value < 1e12]


def infer_raw_scale(raw_values: list[float], duration_sec: float | None) -> dict[str, Any]:
    duration = float(duration_sec or 0.0)
    results = []
    for name, seconds_per_raw, formula in RAW_SCALE_CANDIDATES:
        seconds = [value * seconds_per_raw for value in raw_values]
        plausible = [value for value in seconds if value >= 0.0 and (not duration or value <= duration * 1.10)]
        results.append({
            "name": name,
            "seconds_per_raw": seconds_per_raw,
            "formula": formula,
            "plausible_count": len(plausible),
            "sample_seconds": [round(value, 3) for value in plausible[:8]],
        })
    best = max(results, key=lambda item: item["plausible_count"], default=None)
    return {
        "confirmed": False,
        "warning": "seconds_to_raw is not confirmed yet",
        "best_plausible": best if best and best["plausible_count"] else None,
        "candidates": results,
    }


def raw_candidates_for_seconds(seconds: float) -> list[dict[str, Any]]:
    out = []
    for name, seconds_per_raw, formula in RAW_SCALE_CANDIDATES:
        raw = float(seconds) / seconds_per_raw if seconds_per_raw else math.nan
        out.append({"name": name, "raw": raw, "formula": formula})
    return out


def print_track_summary(row: dict[str, Any]) -> None:
    bpm = row.get("bpmAnalyzed") if row.get("bpmAnalyzed") is not None else row.get("bpm")
    label = " - ".join(part for part in [row.get("artist") or "", row.get("title") or row.get("filename") or ""] if part)
    print(f"Track {row.get('id')}: {label or row.get('filename') or ''}")
    print(f"length: {row.get('length') or '?'} sec  bpm: {bpm or '?'}  lastEditTime: {row.get('lastEditTime') or '?'}")


def print_quick_cues(cues: QuickCuesBlob | None, duration_sec: float | None) -> None:
    print("\nquickCues:")
    if not cues:
        print("  not present")
        return
    print(f"  slots: {cues.slot_count}  trailing: {len(cues.trailing_bytes)} bytes")
    for slot in cues.slots:
        status = "empty" if slot.empty else "set"
        if slot.empty:
            print(f"  {slot.slot}: {status} raw={slot.pos_raw} label={slot.label!r} color={slot.color}")
            continue
        candidates = raw_candidates_for_seconds(0.0)  # placeholder for names/order
        seconds_text = []
        for name, seconds_per_raw, _formula in RAW_SCALE_CANDIDATES:
            seconds = slot.pos_raw * seconds_per_raw
            if not duration_sec or 0 <= seconds <= float(duration_sec) * 1.10:
                seconds_text.append(f"{name}:{seconds:.3f}s")
        print(f"  {slot.slot}: {status} raw={slot.pos_raw:.6f} label={slot.label!r} color={slot.color} {' '.join(seconds_text)}")


def print_loops(loops: LoopsBlob | None, duration_sec: float | None) -> None:
    print("\nloops:")
    if not loops:
        print("  not present")
        return
    print(f"  slots: {loops.slot_count}  unknown_u32: {loops.unknown_u32}  trailing: {len(loops.trailing_bytes)} bytes")
    for slot in loops.slots:
        status = "empty" if slot.empty else "set"
        if slot.empty:
            print(f"  {slot.slot}: {status} start_raw={slot.start_raw} end_raw={slot.end_raw} label={slot.label!r} color={slot.color}")
            continue
        seconds_text = []
        for name, seconds_per_raw, _formula in RAW_SCALE_CANDIDATES:
            start = slot.start_raw * seconds_per_raw
            end = slot.end_raw * seconds_per_raw
            if not duration_sec or (0 <= start <= float(duration_sec) * 1.10 and 0 <= end <= float(duration_sec) * 1.10):
                seconds_text.append(f"{name}:{start:.3f}-{end:.3f}s")
        print(
            f"  {slot.slot}: {status} start_raw={slot.start_raw:.6f} end_raw={slot.end_raw:.6f} "
            f"label={slot.label!r} enabled={[slot.enabled_1, slot.enabled_2]} color={slot.color} {' '.join(seconds_text)}"
        )


def print_round_trip(quick_result: dict[str, Any], loops_result: dict[str, Any]) -> None:
    print("\nround-trip:")
    if quick_result.get("present"):
        print(
            "  quickCues: "
            f"payload_equal={quick_result.get('payload_equal')} blob_equal={quick_result.get('blob_equal')} "
            f"slots={quick_result.get('slot_count')}"
        )
    else:
        print(f"  quickCues: {quick_result.get('message')}")
    if loops_result.get("present"):
        print(
            "  loops: "
            f"blob_equal={loops_result.get('blob_equal')} slots={loops_result.get('slot_count')}"
        )
    else:
        print(f"  loops: {loops_result.get('message')}")


def dry_run_set_cue(cues: QuickCuesBlob | None, slot: int, time_sec: float, duration_sec: float | None, scale_info: dict[str, Any]) -> None:
    print("\ndry-run set cue:")
    print("  WARNING: seconds_to_raw is not confirmed yet")
    if not cues:
        cues = empty_quick_cues()
        print("  quickCues blob is missing; using an empty 8-slot shape for diagnostics only")
    current = cues.slot(slot)
    print(f"  slot: {slot}")
    print(f"  current: empty={current.empty} raw={current.pos_raw} label={current.label!r} color={current.color}")
    print(f"  requested time_sec: {float(time_sec):.3f}")
    best = scale_info.get("best_plausible")
    if best:
        raw = float(time_sec) / float(best["seconds_per_raw"])
        print(f"  best plausible scale from existing data: {best['name']} -> raw {raw:.6f}")
    else:
        print("  no plausible scale could be inferred from existing non-empty cue/loop slots")
    print("  raw candidates:")
    for item in raw_candidates_for_seconds(float(time_sec)):
        print(f"    {item['name']}: {item['raw']:.6f} ({item['formula']})")
    print("  no database writes were made")
    if duration_sec and float(time_sec) > float(duration_sec):
        print(f"  WARNING: requested time exceeds track length {duration_sec}s")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Engine DJ quickCues/loops codec diagnostics.")
    parser.add_argument("--db", required=True, type=Path, help="Path to Engine m.db or a copied debug DB")
    parser.add_argument("--track-id", required=True, type=int, help="Engine Track.id")
    parser.add_argument("--print", action="store_true", help="Print decoded quick cue and loop slots")
    parser.add_argument("--dry-run-set-cue", type=int, default=None, metavar="SLOT", help="Show raw position candidates for setting a cue slot; does not write")
    parser.add_argument("--time-sec", type=float, default=None, help="Cue time in seconds for --dry-run-set-cue")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional JSON diagnostic output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.dry_run_set_cue is not None and args.time_sec is None:
        raise SystemExit("--time-sec is required with --dry-run-set-cue")

    row = load_track_payload(args.db, args.track_id)
    duration_sec = float(row.get("length") or 0.0) or None

    quick_cues = None
    loops = None
    quick_error = None
    loops_error = None
    try:
        if row.get("quickCues"):
            quick_cues = parse_quick_cues(row.get("quickCues"))
    except Exception as exc:
        quick_error = repr(exc)
    try:
        if row.get("loops"):
            loops = parse_loops(row.get("loops"))
    except Exception as exc:
        loops_error = repr(exc)

    quick_round_trip = round_trip_quick_cues(row.get("quickCues")) if not quick_error else {"present": True, "ok": False, "error": quick_error}
    loops_round_trip = round_trip_loops(row.get("loops")) if not loops_error else {"present": True, "ok": False, "error": loops_error}
    scale_info = infer_raw_scale(positive_raw_values(quick_cues, loops), duration_sec)

    should_print = args.print or args.dry_run_set_cue is None
    if should_print:
        print_track_summary(row)
        if quick_error:
            print(f"\nquickCues parse error: {quick_error}")
        else:
            print_quick_cues(quick_cues, duration_sec)
        if loops_error:
            print(f"\nloops parse error: {loops_error}")
        else:
            print_loops(loops, duration_sec)
        print_round_trip(quick_round_trip, loops_round_trip)
        print("\nraw scale inference:")
        print(f"  WARNING: {scale_info['warning']}")
        if scale_info.get("best_plausible"):
            best = scale_info["best_plausible"]
            print(f"  best plausible: {best['name']} ({best['formula']}) samples={best['sample_seconds']}")
        else:
            print("  best plausible: none")

    if args.dry_run_set_cue is not None:
        dry_run_set_cue(quick_cues, args.dry_run_set_cue, float(args.time_sec), duration_sec, scale_info)

    if args.json_out:
        payload = {
            "ok": bool(quick_round_trip.get("ok", True) and loops_round_trip.get("ok", True)),
            "db": str(args.db),
            "track_id": args.track_id,
            "track": {key: row.get(key) for key in ("id", "title", "artist", "filename", "length", "bpmAnalyzed", "bpm", "lastEditTime")},
            "quickCues": quick_cues.to_dict() if quick_cues else None,
            "loops": loops.to_dict() if loops else None,
            "quickCues_error": quick_error,
            "loops_error": loops_error,
            "round_trip": {"quickCues": quick_round_trip, "loops": loops_round_trip},
            "raw_scale": scale_info,
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON diagnostics: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
