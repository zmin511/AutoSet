from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional


ANALYSIS_VERSION = 1

SIMILARITY_WEIGHTS = {
    "bpm": 0.25,
    "camelot": 0.25,
    "energy": 0.25,
    "genre": 0.15,
    "duration": 0.10,
}

_CAMELOT_PATTERN = re.compile(
    r"^\s*(1[0-2]|[1-9])\s*([AB])\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TrackProfile:
    track_id: str
    file_path: str
    file_size: Optional[int] = None
    file_mtime: Optional[float] = None
    analysis_version: int = ANALYSIS_VERSION
    duration_seconds: Optional[float] = None
    bpm: Optional[float] = None
    camelot_key: str = ""
    genre: str = ""
    energy_mean: Optional[float] = None
    energy_intro: Optional[float] = None
    energy_peak: Optional[float] = None
    energy_outro: Optional[float] = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimilarityResult:
    total: float
    components: dict[str, float]
    available_weights: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "components": dict(self.components),
            "available_weights": dict(self.available_weights),
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def normalize_optional_float(
    value: Any,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[float]:
    if value is None or value == "":
        return None

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)

    return result


def normalize_bpm(value: Any) -> Optional[float]:
    bpm = normalize_optional_float(value)
    if bpm is None or bpm <= 0:
        return None

    while bpm < 70:
        bpm *= 2

    while bpm > 190:
        bpm /= 2

    return round(bpm, 4)


def normalize_energy(value: Any) -> Optional[float]:
    energy = normalize_optional_float(value)
    if energy is None:
        return None
    return round(clamp(energy), 4)


def normalize_duration(value: Any) -> Optional[float]:
    duration = normalize_optional_float(value)
    if duration is None or duration <= 0:
        return None
    return round(duration, 3)


def normalize_camelot(value: Any) -> str:
    match = _CAMELOT_PATTERN.match(str(value or ""))
    if not match:
        return ""
    return f"{int(match.group(1))}{match.group(2).upper()}"


def parse_camelot(value: Any) -> Optional[tuple[int, str]]:
    normalized = normalize_camelot(value)
    if not normalized:
        return None
    return int(normalized[:-1]), normalized[-1]


def camelot_number_distance(first: int, second: int) -> int:
    distance = abs(first - second)
    return min(distance, 12 - distance)


def _value_from_source(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def build_track_profile(
    source: Any,
    *,
    file_path: Optional[str] = None,
    camelot_key: Optional[str] = None,
) -> TrackProfile:
    track_id = str(_value_from_source(source, "track_id", "") or "")
    if not track_id:
        track_id = str(_value_from_source(source, "id", "") or "")

    resolved_path = file_path
    if resolved_path is None:
        resolved_path = str(
            _value_from_source(source, "file_path", "")
            or _value_from_source(source, "path", "")
            or ""
        )

    resolved_camelot = camelot_key
    if resolved_camelot is None:
        resolved_camelot = str(
            _value_from_source(source, "camelot_key", "")
            or _value_from_source(source, "camelot", "")
            or ""
        )

    created_at = str(_value_from_source(source, "created_at", "") or "")
    if not created_at:
        created_at = utc_now_iso()

    return TrackProfile(
        track_id=track_id,
        file_path=resolved_path,
        file_size=_value_from_source(source, "file_size"),
        file_mtime=normalize_optional_float(
            _value_from_source(source, "file_mtime")
        ),
        analysis_version=int(
            _value_from_source(
                source,
                "analysis_version",
                ANALYSIS_VERSION,
            )
            or ANALYSIS_VERSION
        ),
        duration_seconds=normalize_duration(
            _value_from_source(
                source,
                "duration_seconds",
                _value_from_source(source, "length"),
            )
        ),
        bpm=normalize_bpm(_value_from_source(source, "bpm")),
        camelot_key=normalize_camelot(resolved_camelot),
        genre=str(_value_from_source(source, "genre", "") or "").strip(),
        energy_mean=normalize_energy(
            _value_from_source(
                source,
                "energy_mean",
                _value_from_source(source, "wave_energy"),
            )
        ),
        energy_intro=normalize_energy(
            _value_from_source(source, "energy_intro")
        ),
        energy_peak=normalize_energy(
            _value_from_source(source, "energy_peak")
        ),
        energy_outro=normalize_energy(
            _value_from_source(source, "energy_outro")
        ),
        created_at=created_at,
    )


def bpm_similarity(
    first: Optional[float],
    second: Optional[float],
) -> Optional[float]:
    first_bpm = normalize_bpm(first)
    second_bpm = normalize_bpm(second)

    if first_bpm is None or second_bpm is None:
        return None

    difference = abs(first_bpm - second_bpm)
    return round(clamp(1.0 - difference / 12.0), 4)


def camelot_similarity(first: Any, second: Any) -> Optional[float]:
    first_key = parse_camelot(first)
    second_key = parse_camelot(second)

    if first_key is None or second_key is None:
        return None

    if first_key == second_key:
        return 1.0

    distance = camelot_number_distance(first_key[0], second_key[0])
    same_mode = first_key[1] == second_key[1]

    if distance == 0:
        return 0.95
    if distance == 1 and same_mode:
        return 0.90
    if distance == 1:
        return 0.75
    if distance == 2 and same_mode:
        return 0.60
    if distance == 2:
        return 0.45

    penalty = 0.12 if not same_mode else 0.0
    return round(clamp(0.50 - distance * 0.10 - penalty), 4)


def energy_similarity(
    first: Optional[float],
    second: Optional[float],
) -> Optional[float]:
    first_energy = normalize_energy(first)
    second_energy = normalize_energy(second)

    if first_energy is None or second_energy is None:
        return None

    return round(clamp(1.0 - abs(first_energy - second_energy)), 4)


def _genre_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(
            r"[^a-zа-яё0-9]+",
            str(value or "").casefold(),
        )
        if token
    }


def genre_similarity(first: str, second: str) -> Optional[float]:
    first_tokens = _genre_tokens(first)
    second_tokens = _genre_tokens(second)

    if not first_tokens or not second_tokens:
        return None

    if first_tokens == second_tokens:
        return 1.0

    intersection = first_tokens & second_tokens
    union = first_tokens | second_tokens

    if not union:
        return None

    return round(len(intersection) / len(union), 4)


def duration_similarity(
    first: Optional[float],
    second: Optional[float],
) -> Optional[float]:
    first_duration = normalize_duration(first)
    second_duration = normalize_duration(second)

    if first_duration is None or second_duration is None:
        return None

    scale = max(first_duration, second_duration, 60.0)
    difference = abs(first_duration - second_duration)
    return round(clamp(1.0 - difference / scale), 4)


def compare_profiles(
    first: TrackProfile,
    second: TrackProfile,
) -> SimilarityResult:
    raw_components: dict[str, Optional[float]] = {
        "bpm": bpm_similarity(first.bpm, second.bpm),
        "camelot": camelot_similarity(
            first.camelot_key,
            second.camelot_key,
        ),
        "energy": energy_similarity(
            first.energy_mean,
            second.energy_mean,
        ),
        "genre": genre_similarity(first.genre, second.genre),
        "duration": duration_similarity(
            first.duration_seconds,
            second.duration_seconds,
        ),
    }

    components = {
        name: value
        for name, value in raw_components.items()
        if value is not None
    }

    available_weight_total = sum(
        SIMILARITY_WEIGHTS[name]
        for name in components
    )

    if available_weight_total <= 0:
        return SimilarityResult(
            total=0.0,
            components={},
            available_weights={},
        )

    available_weights = {
        name: round(
            SIMILARITY_WEIGHTS[name] / available_weight_total,
            6,
        )
        for name in components
    }

    total = sum(
        components[name] * available_weights[name]
        for name in components
    )

    return SimilarityResult(
        total=round(clamp(total), 4),
        components={
            name: round(value, 4)
            for name, value in components.items()
        },
        available_weights=available_weights,
    )


def find_similar_tracks(
    reference_profile: TrackProfile,
    candidates: Iterable[TrackProfile],
    limit: int = 20,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for candidate in candidates:
        same_track_id = (
            bool(reference_profile.track_id)
            and candidate.track_id == reference_profile.track_id
        )
        same_path = (
            bool(reference_profile.file_path)
            and candidate.file_path == reference_profile.file_path
        )

        if same_track_id or same_path:
            continue

        similarity = compare_profiles(
            reference_profile,
            candidate,
        )

        results.append(
            {
                "profile": candidate,
                "total": similarity.total,
                "components": similarity.components,
                "available_weights": similarity.available_weights,
            }
        )

    results.sort(
        key=lambda item: (
            -item["total"],
            str(item["profile"].file_path).casefold(),
            str(item["profile"].track_id),
        )
    )

    return results[:max(0, int(limit))]
