"""Interim intimacy-rank fold from signal evidence.

Replay calls these helpers so derived rank stays defined after the v8→v9
migration converts ``set_intimacy_strength`` into evidence entries. The
formula is a last-write / step-down stand-in; DEF-9 replaces it with the
deterministic accumulation and threshold engine.
"""

from __future__ import annotations

from app.world.models import (
    DerivedIntimacyStrength,
    EvidenceStrength,
    Intimacy,
    IntimacyEvidence,
)

_RANK_ORDER: tuple[DerivedIntimacyStrength, ...] = ("dormant", "minor", "major", "defining")
_SUPPORTS_TO_RANK: dict[int, DerivedIntimacyStrength] = {
    1: "minor",
    2: "minor",
    3: "major",
    4: "major",
    5: "defining",
}
_RANK_TO_EVIDENCE_STRENGTH: dict[str, EvidenceStrength] = {
    "minor": 2,
    "major": 3,
    "defining": 5,
}


def evidence_from_strength_effect(intimacy_id: str, strength: str) -> IntimacyEvidence:
    """Build the evidence entry equivalent to a ``set_intimacy_strength`` effect."""

    return IntimacyEvidence(
        intimacy_id=intimacy_id,
        direction="supports",
        strength=_RANK_TO_EVIDENCE_STRENGTH.get(strength, 3),
        rationale=f"Migrated from set_intimacy_strength ({strength}).",
    )


def apply_evidence_entry(intimacy: Intimacy, entry: IntimacyEvidence) -> None:
    """Apply one evidence entry to an intimacy's derived rank.

    ``supports`` is last-write using the 1-5 to rank mapping so migrated
    ``set_intimacy_strength`` effects reconstruct the same rank. ``contradicts``
    steps the rank down (1-2 no change, 3-4 one step, 5 two steps), eroding
    below ``minor`` to ``dormant``.
    """

    if entry.direction == "supports":
        intimacy.strength = _SUPPORTS_TO_RANK[entry.strength]
        return

    steps = 0 if entry.strength <= 2 else 1 if entry.strength <= 4 else 2
    if not steps:
        return
    current = intimacy.strength if intimacy.strength in _RANK_ORDER else "minor"
    index = max(0, _RANK_ORDER.index(current) - steps)
    intimacy.strength = _RANK_ORDER[index]
