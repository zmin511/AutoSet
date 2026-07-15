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

TRANSITION_SAFE = "safe"
TRANSITION_COMPATIBLE = "compatible"
TRANSITION_RISKY = "risky"
TRANSITION_REJECTED = "rejected"


@dataclass(frozen=True)
class TransitionResult:
    total: float
    accepted: bool
    transition_class: str
    components: dict[str, float]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "accepted": self.accepted,
            "transition_class": self.transition_class,
            "components": dict(self.components),
            "reasons": list(self.reasons),
        }


def _classify_transition(
    total: float,
    components: dict[str, float],
    *,
    genre_comparable: bool,
) -> str:
    bpm = components.get("bpm")
    camelot = components.get("camelot")
    energy = components.get("energy")
    genre = components.get("genre")

    # Известные, но полностью несовместимые жанры считаем рискованными.
    if genre_comparable and genre == 0.0:
        return TRANSITION_RISKY

    # Слишком слабые отдельные компоненты также делают переход рискованным.
    if bpm is not None and bpm < 0.70:
        return TRANSITION_RISKY
    if camelot is not None and camelot < 0.60:
        return TRANSITION_RISKY
    if energy is not None and energy < 0.60:
        return TRANSITION_RISKY

    safe_components = (
        (bpm is None or bpm >= 0.82)
        and (camelot is None or camelot >= 0.75)
        and (energy is None or energy >= 0.75)
        and (genre is None or genre > 0.0)
    )

    if total >= 0.88 and safe_components:
        return TRANSITION_SAFE

    if total >= 0.72:
        return TRANSITION_COMPATIBLE

    return TRANSITION_RISKY


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
                transition_class=TRANSITION_REJECTED,
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
                transition_class=TRANSITION_REJECTED,
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
    genre_comparable = genre_value is not None

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
            transition_class=TRANSITION_REJECTED,
            components={},
            reasons=reasons,
        )

    total = sum(
        components[name]
        * (TRANSITION_WEIGHTS[name] / available_weight_total)
        for name in components
    )
    total = round(max(0.0, min(1.0, total)), 4)

    transition_class = _classify_transition(
        total,
        components,
        genre_comparable=genre_comparable,
    )

    reasons.append(f"Transition class: {transition_class}")

    return TransitionResult(
        total=total,
        accepted=True,
        transition_class=transition_class,
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
    include_risky: bool = False,
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

        if (
            result.transition_class == TRANSITION_RISKY
            and not include_risky
        ):
            continue

        results.append(
            {
                "profile": candidate,
                "total": result.total,
                "transition_class": result.transition_class,
                "components": result.components,
                "reasons": result.reasons,
            }
        )

    class_priority = {
        TRANSITION_SAFE: 0,
        TRANSITION_COMPATIBLE: 1,
        TRANSITION_RISKY: 2,
    }

    results.sort(
        key=lambda item: (
            class_priority.get(item["transition_class"], 9),
            -item["total"],
            str(item["profile"].file_path).casefold(),
            str(item["profile"].track_id),
        )
    )

    return results[:max(0, int(limit))]
