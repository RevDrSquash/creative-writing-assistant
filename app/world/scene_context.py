"""Cross-scene continuity context for the scene-writing workflow."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.world.models import Scene, StoryBible, World
from app.world.relations import chronological_order

# Defensive cap on previous-scene prose injected into prompts.
PREVIOUS_SCENE_PROSE_CAP = 12_000

_CONTINUITY_INSTRUCTION = (
    "Maintain continuity with the surrounding scenes: location, time of day, who is present, "
    "ongoing action, and emotional carryover. When the previous scene is directly continuous, "
    "open consistent with its ending. Do not re-introduce characters or re-describe settings "
    "already established in neighboring scenes."
)


@dataclass(frozen=True)
class SceneSnapshot:
    """Minimal scene data for continuity prompts."""

    scene_id: str
    title: str
    summary: str
    markdown: str = ""


@dataclass
class SceneContinuityContext:
    """Neighboring scenes selected for continuity context."""

    previous: SceneSnapshot | None = None
    next: SceneSnapshot | None = None
    related: list[SceneSnapshot] = field(default_factory=list)


def build_scene_continuity_context(world: World, scene_id: str) -> SceneContinuityContext:
    """Select previous, next, and related scenes for continuity context."""

    target = world.get_scene(scene_id)
    if target is None:
        return SceneContinuityContext()

    bible = world.story_bible
    chrono_index = _event_chronological_index(bible)
    ranked = _rank_scenes(world.scenes, chrono_index)

    previous = _adjacent_scene(world, ranked, scene_id, offset=-1)
    next_scene = _adjacent_scene(world, ranked, scene_id, offset=1)
    related = _related_scenes(world, target, previous, next_scene)

    return SceneContinuityContext(previous=previous, next=next_scene, related=related)


def format_continuity_context(context: SceneContinuityContext) -> str:
    """Render continuity context as a prompt block, or empty string when none."""

    if context.previous is None and context.next is None and not context.related:
        return ""

    lines = ["## Surrounding scene context", "", _CONTINUITY_INSTRUCTION, ""]

    if context.previous is not None:
        lines.extend(_format_previous_scene(context.previous))
        lines.append("")

    if context.next is not None:
        lines.extend(_format_summary_scene("Next scene", context.next))
        lines.append("")

    for snapshot in context.related:
        lines.extend(_format_summary_scene("Related scene", snapshot))
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def _event_chronological_index(bible: StoryBible) -> dict[str, int]:
    return {event.id: index for index, event in enumerate(chronological_order(bible))}


def _resolved_event_indices(event_ids: list[str], chrono_index: dict[str, int]) -> list[int]:
    return [chrono_index[event_id] for event_id in event_ids if event_id in chrono_index]


def _scene_sort_key(scene: Scene, list_index: int, chrono_index: dict[str, int]) -> tuple[int, int]:
    indices = _resolved_event_indices(scene.blueprint.event_ids, chrono_index)
    if indices:
        return min(indices), list_index
    # Scenes without resolvable enacted events fall back to list order after event-linked scenes.
    return 10**9 + list_index, list_index


def _rank_scenes(scenes: list[Scene], chrono_index: dict[str, int]) -> list[Scene]:
    indexed = list(enumerate(scenes))
    indexed.sort(key=lambda item: _scene_sort_key(item[1], item[0], chrono_index))
    return [scene for _, scene in indexed]


def _adjacent_scene(
    world: World,
    ranked: list[Scene],
    scene_id: str,
    *,
    offset: int,
) -> SceneSnapshot | None:
    positions = [index for index, scene in enumerate(ranked) if scene.id == scene_id]
    if not positions:
        return None
    position = positions[0] + offset
    if position < 0 or position >= len(ranked):
        return None
    return _snapshot(world, ranked[position], include_markdown=offset < 0)


def _related_scenes(
    world: World,
    target: Scene,
    previous: SceneSnapshot | None,
    next_scene: SceneSnapshot | None,
) -> list[SceneSnapshot]:
    excluded = {target.id}
    if previous is not None:
        excluded.add(previous.scene_id)
    if next_scene is not None:
        excluded.add(next_scene.scene_id)

    target_event_ids = {
        event_id
        for event_id in target.blueprint.event_ids
        if world.story_bible.get_event(event_id) is not None
    }
    related_event_ids = _continuity_related_event_ids(world.story_bible, target_event_ids)
    related_event_ids.update(
        event_id
        for event_id in target.blueprint.related_event_ids
        if world.story_bible.get_event(event_id) is not None
    )

    snapshots: list[SceneSnapshot] = []
    seen: set[str] = set()
    for scene in world.scenes:
        if scene.id in excluded or scene.id in seen:
            continue
        enacted = {
            event_id
            for event_id in scene.blueprint.event_ids
            if world.story_bible.get_event(event_id) is not None
        }
        if enacted & related_event_ids:
            snapshots.append(_snapshot(world, scene, include_markdown=False))
            seen.add(scene.id)
    return snapshots


def _continuity_related_event_ids(bible: StoryBible, target_event_ids: set[str]) -> set[str]:
    if not target_event_ids:
        return set()

    related: set[str] = set()
    for relation in bible.event_relations:
        if relation.kind not in ("directly_follows", "during"):
            continue
        pair = {relation.source_id, relation.target_id}
        overlap = pair & target_event_ids
        if not overlap:
            continue
        related.update(pair - target_event_ids)
    return related


def _snapshot(world: World, scene: Scene, *, include_markdown: bool) -> SceneSnapshot:
    resolved = world.get_scene(scene.id) or scene
    markdown = resolved.markdown if include_markdown else ""
    if include_markdown and len(markdown) > PREVIOUS_SCENE_PROSE_CAP:
        markdown = markdown[:PREVIOUS_SCENE_PROSE_CAP] + "\n\n[... truncated ...]"
    return SceneSnapshot(
        scene_id=resolved.id,
        title=resolved.title,
        summary=resolved.summary,
        markdown=markdown,
    )


def _format_previous_scene(snapshot: SceneSnapshot) -> list[str]:
    lines = [
        "### Previous scene (full prose)",
        f"Title: {snapshot.title} [id: {snapshot.scene_id}]",
    ]
    if snapshot.summary:
        lines.append(f"Summary: {snapshot.summary}")
    lines.append("")
    lines.append(snapshot.markdown or "(no prose yet)")
    return lines


def _format_summary_scene(label: str, snapshot: SceneSnapshot) -> list[str]:
    lines = [
        f"### {label}",
        f"Title: {snapshot.title} [id: {snapshot.scene_id}]",
    ]
    if snapshot.summary:
        lines.append(f"Summary: {snapshot.summary}")
    else:
        lines.append("Summary: (none)")
    return lines
