from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from track_analysis import (
    TrackProfile,
    bpm_similarity,
    camelot_similarity,
    energy_similarity,
    genre_similarity,
)


TRANSITION_WEIGHTS = {
    "bpm": 0.30,
    "camelot": 0.30,
    "energy": 0.25,
    "genre": 0.15,
}

MAX_BPM_DELTA = 5.0
MIN_CAMELOT_SCORE = 0.45


@dataclass(frozen=True)
class TransitionResult:
    total: float
    accepted: bool
    components: dict[str, float]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "accepted": self.accepted,
            "components": dict(self.components),
            "reasons": list(self.reasons),
        }


def transition_score(
    previous: TrackProfile,
    candidate: TrackProfile,
) -> TransitionResult:
    reasons: list[str] = []
    components: dict[str, float] = {}

    if previous.bpm is not None and candidate.bpm is not None:
        bpm_delta = abs(previous.bpm - candidate.bpm)

        if bpm_delta > MAX_BPM_DELTA:
            reasons.append(
                f"BPM delta {bpm_delta:.2f} exceeds limit {MAX_BPM_DELTA:.2f}"
            )
            return TransitionResult(
                total=0.0,
                accepted=False,
                components={"bpm": 0.0},
                reasons=reasons,
            )

        bpm_value = bpm_similarity(previous.bpm, candidate.bpm)
        if bpm_value is not None:
            components["bpm"] = bpm_value
            reasons.append(f"BPM delta {bpm_delta:.2f}")
    else:
        reasons.append("BPM unavailable")

    camelot_value = camelot_similarity(
        previous.camelot_key,
        candidate.camelot_key,
    )
    if camelot_value is not None:
        components["camelot"] = camelot_value

        if camelot_value < MIN_CAMELOT_SCORE:
            reasons.append(
                f"Camelot compatibility {camelot_value:.2f} below minimum "
                f"{MIN_CAMELOT_SCORE:.2f}"
            )
            return TransitionResult(
                total=0.0,
                accepted=False,
                components=components,
                reasons=reasons,
            )

        reasons.append(
            f"Camelot {previous.camelot_key or 'n/a'} -> "
            f"{candidate.camelot_key or 'n/a'}"
        )
    else:
        reasons.append("Camelot unavailable")

    energy_value = energy_similarity(
        previous.energy_mean,
        candidate.energy_mean,
    )
    if energy_value is not None:
        components["energy"] = energy_value
        energy_delta = abs(
            float(previous.energy_mean) - float(candidate.energy_mean)
        )
        reasons.append(f"Energy delta {energy_delta:.3f}")
    else:
        reasons.append("Energy unavailable")

    genre_value = genre_similarity(
        previous.genre,
        candidate.genre,
    )
    if genre_value is not None:
        components["genre"] = genre_value
        reasons.append(f"Genre compatibility {genre_value:.2f}")
    else:
        reasons.append("Genre unavailable")

    available_weight_total = sum(
        TRANSITION_WEIGHTS[name]
        for name in components
    )

    if available_weight_total <= 0:
        reasons.append("No comparable transition features")
        return TransitionResult(
            total=0.0,
            accepted=False,
            components={},
            reasons=reasons,
        )

    total = sum(
        components[name]
        * (TRANSITION_WEIGHTS[name] / available_weight_total)
        for name in components
    )

    return TransitionResult(
        total=round(max(0.0, min(1.0, total)), 4),
        accepted=True,
        components={
            name: round(value, 4)
            for name, value in components.items()
        },
        reasons=reasons,
    )


def find_transition_candidates(
    previous: TrackProfile,
    candidates: Iterable[TrackProfile],
    *,
    limit: int = 20,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for candidate in candidates:
        same_track_id = (
            bool(previous.track_id)
            and candidate.track_id == previous.track_id
        )
        same_path = (
            bool(previous.file_path)
            and candidate.file_path == previous.file_path
        )

        if same_track_id or same_path:
            continue

        result = transition_score(previous, candidate)

        if not result.accepted:
            continue

        if result.total < min_score:
            continue

        results.append(
            {
                "profile": candidate,
                "total": result.total,
                "components": result.components,
                "reasons": result.reasons,
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
