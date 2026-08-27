"""Deterministic intimacy-rank accumulation from signal evidence.

Pure functions: observations in, rank state out. Replay is one caller; the same
entry point is the what-if oracle for hypothetical evidence sets. See
``docs/story_bible_model.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.world.models import (
    DerivedIntimacyStrength,
    EvidenceDirection,
    EvidenceNovelty,
    EvidenceStrength,
    IntimacyEvidence,
)

RANK_ORDER: tuple[DerivedIntimacyStrength, ...] = (
    "dormant",
    "minor",
    "moderate",
    "major",
    "defining",
)
STRENGTH_WEIGHTS: dict[int, float] = {1: 1.0, 2: 2.0, 3: 3.5, 4: 5.5, 5: 9.0}
RANK_SEEDS: dict[DerivedIntimacyStrength, float] = {
    "dormant": 0.0,
    "minor": 5.0,
    "moderate": 8.5,
    "major": 13.0,
    "defining": 20.0,
}
PROMOTE_AT: dict[DerivedIntimacyStrength, float] = {
    "dormant": 3.5,
    "minor": 9.5,
    "moderate": 15.5,
    "major": 22.0,
}
DEMOTE_AT: dict[DerivedIntimacyStrength, float] = {
    "minor": 1.5,
    "moderate": 5.0,
    "major": 9.5,
    "defining": 10.0,
}
SCENARIO_REPEAT_FACTOR = 0.4
DUPLICATE_FACTOR = 0.35
MOMENTUM_WINDOW = 3
MOMENTUM_BLEND = 0.25
_RANK_TO_EVIDENCE_STRENGTH: dict[str, EvidenceStrength] = {
    "minor": 2,
    "moderate": 3,
    "major": 3,
    "defining": 5,
}


@dataclass(frozen=True)
class EvidenceObservation:
    """One scored intimacy relationship, with the metadata the accumulator needs.

    Callers (replay or a what-if oracle) supply scenario and novelty; this type
    does not read the world.
    """

    intimacy_id: str
    direction: EvidenceDirection
    strength: EvidenceStrength
    event_id: str = ""
    signal_id: str = ""
    chronological_index: int = 0
    scenario_id: str = ""
    novelty: EvidenceNovelty = "novel"
    rationale: str = ""


@dataclass(frozen=True)
class EvidenceContribution:
    """How one observation was weighted in a rank decision."""

    event_id: str
    signal_id: str
    direction: EvidenceDirection
    strength: EvidenceStrength
    weight: float
    signed_weight: float
    scenario_id: str
    novelty: EvidenceNovelty
    rationale: str
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class RankCrossing:
    """One inspectable promotion or demotion during the fold."""

    event_id: str
    signal_id: str
    previous_rank: DerivedIntimacyStrength
    new_rank: DerivedIntimacyStrength
    effective_net: float
    reason: str


@dataclass(frozen=True)
class RankState:
    """Derived rank plus the scores and explanation a planner can inspect."""

    intimacy_id: str
    rank: DerivedIntimacyStrength
    baseline_rank: DerivedIntimacyStrength
    standing_support: float
    standing_contradict: float
    standing_net: float
    momentum_support: float
    momentum_contradict: float
    momentum_net: float
    effective_net: float
    distance_to_promote: float | None
    distance_to_demote: float | None
    contributions: tuple[EvidenceContribution, ...] = ()
    crossings: tuple[RankCrossing, ...] = ()

    @property
    def next_rank(self) -> DerivedIntimacyStrength | None:
        index = RANK_ORDER.index(self.rank)
        if index >= len(RANK_ORDER) - 1:
            return None
        return RANK_ORDER[index + 1]

    @property
    def previous_rank(self) -> DerivedIntimacyStrength | None:
        index = RANK_ORDER.index(self.rank)
        if index <= 0:
            return None
        return RANK_ORDER[index - 1]


@dataclass
class IntimacyEvidenceTrack:
    """Running observation list for one intimacy during a replay fold."""

    baseline_rank: DerivedIntimacyStrength
    observations: list[EvidenceObservation] = field(default_factory=list)

    def reset(self, baseline_rank: DerivedIntimacyStrength) -> None:
        self.baseline_rank = baseline_rank
        self.observations.clear()


def evidence_from_strength_effect(intimacy_id: str, strength: str) -> IntimacyEvidence:
    """Build the evidence entry equivalent to a ``set_intimacy_strength`` effect."""

    return IntimacyEvidence(
        intimacy_id=intimacy_id,
        direction="supports",
        strength=_RANK_TO_EVIDENCE_STRENGTH.get(strength, 3),
        rationale=f"Migrated from set_intimacy_strength ({strength}).",
    )


def observation_from_entry(
    entry: IntimacyEvidence,
    *,
    event_id: str,
    signal_id: str,
    chronological_index: int,
    scenario_id: str,
) -> EvidenceObservation:
    """Lift a stored evidence entry into an accumulator observation."""

    return EvidenceObservation(
        intimacy_id=entry.intimacy_id,
        direction=entry.direction,
        strength=entry.strength,
        event_id=event_id,
        signal_id=signal_id,
        chronological_index=chronological_index,
        scenario_id=scenario_id or event_id,
        novelty=entry.novelty,
        rationale=entry.rationale,
    )


def accumulate_rank(
    baseline_rank: DerivedIntimacyStrength,
    observations: Sequence[EvidenceObservation],
    *,
    intimacy_id: str = "",
) -> RankState:
    """Fold evidence observations into a derived rank.

    Pure and side-effect-free: no persistence or world access. ``observations``
    may be hypothetical. Rank changes at most one step per observation.
    """

    rank: DerivedIntimacyStrength = baseline_rank if baseline_rank in RANK_ORDER else "minor"
    seed = RANK_SEEDS[rank]
    standing_support = 0.0
    standing_contradict = 0.0
    contributions: list[EvidenceContribution] = []
    crossings: list[RankCrossing] = []
    scenario_seen: dict[str, int] = {}
    event_ids: set[str] = set()

    for observation in observations:
        contribution = _contribution_for(observation, scenario_seen)
        contributions.append(contribution)
        if observation.direction == "supports":
            standing_support += contribution.weight
        else:
            standing_contradict += contribution.weight
        if observation.event_id:
            event_ids.add(observation.event_id)
        elif observation.signal_id:
            event_ids.add(observation.signal_id)
        else:
            event_ids.add(f"obs-{len(event_ids)}")

        standing_net = seed + standing_support - standing_contradict
        momentum_support, momentum_contradict = _momentum_totals(contributions, observations)
        momentum_net = momentum_support - momentum_contradict
        effective_net = standing_net + MOMENTUM_BLEND * momentum_net
        new_rank = _step_rank(rank, effective_net, event_ids, observation)
        if new_rank != rank:
            crossings.append(
                RankCrossing(
                    event_id=observation.event_id,
                    signal_id=observation.signal_id,
                    previous_rank=rank,
                    new_rank=new_rank,
                    effective_net=effective_net,
                    reason=_crossing_reason(rank, new_rank, observation, event_ids),
                )
            )
            rank = new_rank

    standing_net = seed + standing_support - standing_contradict
    momentum_support, momentum_contradict = _momentum_totals(contributions, observations)
    momentum_net = momentum_support - momentum_contradict
    effective_net = standing_net + MOMENTUM_BLEND * momentum_net
    return RankState(
        intimacy_id=intimacy_id or (observations[0].intimacy_id if observations else ""),
        rank=rank,
        baseline_rank=baseline_rank if baseline_rank in RANK_ORDER else "minor",
        standing_support=standing_support,
        standing_contradict=standing_contradict,
        standing_net=standing_net,
        momentum_support=momentum_support,
        momentum_contradict=momentum_contradict,
        momentum_net=momentum_net,
        effective_net=effective_net,
        distance_to_promote=_distance_to_promote(rank, effective_net),
        distance_to_demote=_distance_to_demote(rank, effective_net),
        contributions=tuple(contributions),
        crossings=tuple(crossings),
    )


def format_threshold_distance(state: RankState) -> str:
    """Human-readable distance-to-threshold for tools and character-arc rendering.

    A met-but-gated threshold (score crossed, rank held back by the hard rules,
    e.g. a single ordinary event never changes rank) is annotated rather than
    rendered as a confusing negative distance.
    """

    parts: list[str] = []
    next_rank = state.next_rank
    if next_rank is not None and state.distance_to_promote is not None:
        if state.distance_to_promote <= 0:
            parts.append(f"score met for {next_rank}; needs another event to cross")
        else:
            parts.append(f"{state.distance_to_promote:.1f} from {next_rank}")
    previous_rank = state.previous_rank
    if previous_rank is not None and state.distance_to_demote is not None:
        if state.distance_to_demote <= 0:
            parts.append(f"eroded to the {previous_rank} threshold; needs another event to cross")
        else:
            parts.append(f"{state.distance_to_demote:.1f} above {previous_rank}")
    if not parts:
        return "at defining ceiling"
    return ", ".join(parts)


def _contribution_for(
    observation: EvidenceObservation,
    scenario_seen: dict[str, int],
) -> EvidenceContribution:
    scenario_key = observation.scenario_id or observation.event_id or observation.signal_id
    seen = scenario_seen.get(scenario_key, 0)
    scenario_seen[scenario_key] = seen + 1

    weight = STRENGTH_WEIGHTS[observation.strength]
    modifiers: list[str] = []
    if seen:
        weight *= SCENARIO_REPEAT_FACTOR
        modifiers.append("scenario_repeat")
    if observation.novelty == "duplicate":
        weight *= DUPLICATE_FACTOR
        modifiers.append("duplicate")
    if observation.strength == 5:
        modifiers.append("identity_shaking")

    signed = weight if observation.direction == "supports" else -weight
    return EvidenceContribution(
        event_id=observation.event_id,
        signal_id=observation.signal_id,
        direction=observation.direction,
        strength=observation.strength,
        weight=weight,
        signed_weight=signed,
        scenario_id=scenario_key,
        novelty=observation.novelty,
        rationale=observation.rationale,
        modifiers=tuple(modifiers),
    )


def _momentum_totals(
    contributions: Sequence[EvidenceContribution],
    observations: Sequence[EvidenceObservation],
) -> tuple[float, float]:
    if not contributions:
        return 0.0, 0.0
    paired = list(zip(contributions, observations, strict=False))
    keys = [
        _position_key(observation, index) for index, (_contrib, observation) in enumerate(paired)
    ]
    recent = set(_unique_in_order(keys)[-MOMENTUM_WINDOW:])
    support = 0.0
    contradict = 0.0
    for (contribution, _observation), key in zip(paired, keys, strict=True):
        if key not in recent:
            continue
        if contribution.direction == "supports":
            support += contribution.weight
        else:
            contradict += contribution.weight
    return support, contradict


def _position_key(observation: EvidenceObservation, fallback_index: int) -> str:
    if observation.event_id:
        return f"event:{observation.event_id}"
    if observation.chronological_index:
        return f"index:{observation.chronological_index}"
    return f"obs:{fallback_index}"


def _unique_in_order(keys: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _step_rank(
    rank: DerivedIntimacyStrength,
    effective_net: float,
    event_ids: set[str],
    observation: EvidenceObservation,
) -> DerivedIntimacyStrength:
    index = RANK_ORDER.index(rank)
    if rank in PROMOTE_AT and effective_net >= PROMOTE_AT[rank]:
        target = RANK_ORDER[index + 1]
        if _may_change_rank(rank, target, event_ids, observation):
            return target
    if rank in DEMOTE_AT and effective_net <= DEMOTE_AT[rank]:
        target = RANK_ORDER[index - 1]
        if _may_change_rank(rank, target, event_ids, observation):
            return target
    return rank


def _may_change_rank(
    current: DerivedIntimacyStrength,
    target: DerivedIntimacyStrength,
    event_ids: set[str],
    observation: EvidenceObservation,
) -> bool:
    if len(event_ids) >= 2:
        return True
    if observation.strength < 5:
        return False
    return current != "defining" and target != "defining"


def _crossing_reason(
    previous: DerivedIntimacyStrength,
    new_rank: DerivedIntimacyStrength,
    observation: EvidenceObservation,
    event_ids: set[str],
) -> str:
    verb = "Promoted" if RANK_ORDER.index(new_rank) > RANK_ORDER.index(previous) else "Demoted"
    events = f"{len(event_ids)} distinct events"
    return (
        f"{verb} {previous} to {new_rank} after {events} "
        f"({observation.direction} {observation.strength})"
    )


def _distance_to_promote(rank: DerivedIntimacyStrength, effective_net: float) -> float | None:
    threshold = PROMOTE_AT.get(rank)
    if threshold is None:
        return None
    return threshold - effective_net


def _distance_to_demote(rank: DerivedIntimacyStrength, effective_net: float) -> float | None:
    threshold = DEMOTE_AT.get(rank)
    if threshold is None:
        return None
    return effective_net - threshold
