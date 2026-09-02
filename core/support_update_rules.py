from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SupportUpdateOutcome:
    support_before: float
    support_after: float
    direction_matched: bool | str
    magnitude_matched: bool | str
    status: str
    support_delta: float


def observed_delta_from_comparison(
    *,
    skill_delta: float | None,
    pearson_delta: float | None,
    rmse_delta: float | None,
) -> float:
    if skill_delta is not None:
        return skill_delta
    if pearson_delta is not None:
        return pearson_delta
    if rmse_delta is not None:
        return -rmse_delta
    return 0.0


def match_direction(
    observed_delta: float,
    expected_effect: str,
) -> bool | str:
    effect = expected_effect.lower()
    if effect == "positive":
        if observed_delta > 0.005:
            return True
        if observed_delta >= 0.0:
            return "partial"
        return False
    if effect == "negative":
        if observed_delta < -0.005:
            return True
        if observed_delta <= 0.0:
            return "partial"
        return False
    if effect == "near_zero":
        absolute = abs(observed_delta)
        if absolute <= 0.01:
            return True
        if absolute <= 0.02:
            return "partial"
        return False
    return "partial"


def match_magnitude(
    observed_delta: float,
    expected_range: list[float] | None,
) -> bool | str:
    if not expected_range:
        return "partial"
    lower, upper = expected_range
    if lower <= observed_delta <= upper:
        return True
    if (observed_delta < lower and observed_delta >= min(lower, 0.0)) or (
        observed_delta > upper and observed_delta <= max(upper, 0.0)
    ):
        return "partial"
    return False


def compute_support_update_from_prediction(
    *,
    current_support: float,
    expected_effect: str,
    expected_range: list[float] | None,
    observed_delta: float,
) -> SupportUpdateOutcome:
    direction_matched = match_direction(observed_delta, expected_effect)
    magnitude_matched = match_magnitude(observed_delta, expected_range)
    direction_factor = {True: 1.15, "partial": 1.0, False: 0.8}[direction_matched]
    magnitude_factor = {True: 1.05, "partial": 0.95, False: 0.85}[magnitude_matched]
    precision_factor = _precision_factor(expected_range, observed_delta)
    updated = current_support * direction_factor * magnitude_factor * precision_factor
    support_after = round(min(max(updated, 0.05), 0.95), 4)
    return SupportUpdateOutcome(
        support_before=current_support,
        support_after=support_after,
        direction_matched=direction_matched,
        magnitude_matched=magnitude_matched,
        status=_assessment_status(direction_matched, magnitude_matched),
        support_delta=round(support_after - current_support, 4),
    )


def compute_support_update_from_reasoning(
    *,
    current_support: float,
    impact_direction: str,
    impact_strength: float,
    confidence: float,
) -> SupportUpdateOutcome:
    direction_scale = {
        "supports": 1.0,
        "weakens": -1.0,
        "clarifies": 0.35,
    }.get(impact_direction, 0.0)
    support_delta = round(direction_scale * impact_strength * confidence * 0.18, 4)
    support_after = round(min(max(current_support + support_delta, 0.0), 1.0), 4)
    direction_matched = {
        "supports": True,
        "weakens": False,
        "clarifies": "partial",
    }.get(impact_direction, "partial")
    magnitude_matched = True if impact_strength >= 0.6 else "partial"
    status = _status_after_reasoning(support_after, impact_direction)
    return SupportUpdateOutcome(
        support_before=current_support,
        support_after=support_after,
        direction_matched=direction_matched,
        magnitude_matched=magnitude_matched,
        status=status,
        support_delta=support_delta,
    )


def priority_after_action(priority: str, action: str) -> str:
    ordered = ["low", "medium", "high"]
    if priority not in ordered:
        return priority
    index = ordered.index(priority)
    if action == "increase":
        return ordered[min(index + 1, len(ordered) - 1)]
    if action == "decrease":
        return ordered[max(index - 1, 0)]
    return priority


def priority_to_score(priority: str) -> float:
    return {"low": 0.3, "medium": 0.6, "high": 0.9}.get(priority, 0.6)


def signal_from_metric_deltas(rmse_delta: float | None, pearson_delta: float | None) -> str:
    rmse_better = rmse_delta is not None and rmse_delta < 0
    rmse_worse = rmse_delta is not None and rmse_delta > 0
    pearson_better = pearson_delta is not None and pearson_delta > 0
    pearson_worse = pearson_delta is not None and pearson_delta < 0
    if rmse_better and pearson_better:
        return "supports"
    if rmse_worse and pearson_worse:
        return "weakens"
    return "mixed"


def signal_strength(rmse_delta: float | None, pearson_delta: float | None) -> str:
    rmse_gap = abs(rmse_delta or 0.0)
    pearson_gap = abs(pearson_delta or 0.0)
    if rmse_gap >= 1.0 or pearson_gap >= 0.1:
        return "high"
    if rmse_gap >= 0.1 or pearson_gap >= 0.02:
        return "medium"
    return "low"


def _precision_factor(expected_range: list[float] | None, observed_delta: float) -> float:
    if not expected_range:
        return 1.0
    lower, upper = expected_range
    hit = lower <= observed_delta <= upper
    width = abs(upper - lower)
    if hit and width < 0.03:
        return 1.05
    if hit and width > 0.10:
        return 0.98
    return 0.95


def _assessment_status(direction_matched: bool | str, magnitude_matched: bool | str) -> str:
    if direction_matched is True and magnitude_matched is True:
        return "supported"
    if direction_matched is False:
        return "weakened"
    return "partially_supported"


def _status_after_reasoning(after: float, impact_direction: str) -> str:
    if after < 0.20:
        return "pruned"
    if after >= 0.72 and impact_direction in {"supports", "clarifies"}:
        return "converged"
    if impact_direction == "weakens" and after < 0.40:
        return "observing"
    return "active" if after >= 0.40 else "observing"
