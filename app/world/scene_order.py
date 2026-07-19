"""Deterministic scene generation order derived from event chronology.

Builds a scene-level dependency DAG from directed event relations so that
``Generate All Scenes`` can enqueue work with continuity-safe prerequisites.
See ``docs/architecture_async_jobs.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.world.models import Scene, StoryBible, World
from app.world.relations import _directed_adjacency
from app.world.scene import scene_generation_status, scene_is_generatable
from app.world.scene_context import _event_chronological_index, _rank_scenes


@dataclass(frozen=True)
class SceneGenerationPlanItem:
    """One scene in a generate-all plan, with prerequisites and UI defaults."""

    scene_id: str
    title: str
    prerequisite_scene_ids: tuple[str, ...]
    generatable: bool
    not_generatable_reason: str
    status: str
    selected_by_default: bool


@dataclass(frozen=True)
class SceneGenerationPlan:
    """Ordered plan of scenes for bulk generation."""

    items: tuple[SceneGenerationPlanItem, ...] = field(default_factory=tuple)

    def item_for(self, scene_id: str) -> SceneGenerationPlanItem | None:
        return next((item for item in self.items if item.scene_id == scene_id), None)


def _event_ancestor_sets(bible: StoryBible) -> dict[str, set[str]]:
    """Return transitive ancestors (earlier events) for every timeline event."""

    adjacency = _directed_adjacency(bible)
    ancestors: dict[str, set[str]] = {event.id: set() for event in bible.timeline}
    computed: set[str] = set()
    visiting: set[str] = set()

    def collect(event_id: str) -> set[str]:
        if event_id in computed or event_id in visiting:
            return ancestors[event_id]
        visiting.add(event_id)
        collected: set[str] = set()
        for earlier_id in adjacency.get(event_id, []):
            collected.add(earlier_id)
            collected |= collect(earlier_id)
        ancestors[event_id] = collected
        visiting.discard(event_id)
        computed.add(event_id)
        return collected

    for event in bible.timeline:
        collect(event.id)
    return ancestors


def _not_generatable_reason(scene: Scene) -> str:
    if not scene.blueprint.premise.strip():
        return "Missing premise"
    if not scene.blueprint.event_ids:
        return "No enacted events"
    return ""


def _prerequisite_ids_for_scene(
    scene: Scene,
    *,
    ranked_scenes: list[Scene],
    ancestors: dict[str, set[str]],
) -> tuple[str, ...]:
    """Return scene ids that must finish before ``scene`` for continuity."""

    prerequisites: set[str] = set()
    enacted = list(scene.blueprint.event_ids)
    related = set(scene.blueprint.related_event_ids)

    for other in ranked_scenes:
        if other.id == scene.id:
            continue
        other_enacted = set(other.blueprint.event_ids)
        if not other_enacted:
            continue

        # Other scene enacts an ancestor of any of this scene's enacted events.
        if any(
            other_event in ancestors.get(enacted_event, set())
            for enacted_event in enacted
            for other_event in other_enacted
        ):
            prerequisites.add(other.id)
            continue

        # Other scene enacts an event this scene lists as related context.
        if other_enacted & related:
            prerequisites.add(other.id)

    scene_index = {item.id: index for index, item in enumerate(ranked_scenes)}
    return tuple(sorted(prerequisites, key=lambda scene_id: scene_index.get(scene_id, 10**9)))


def build_scene_generation_plan(world: World) -> SceneGenerationPlan:
    """Compute a deterministic generate-all plan from event chronology."""

    bible = world.story_bible
    chrono_index = _event_chronological_index(bible)
    ranked = _rank_scenes(world.scenes, chrono_index)
    ancestors = _event_ancestor_sets(bible)

    items: list[SceneGenerationPlanItem] = []
    for scene in ranked:
        generatable = scene_is_generatable(scene)
        status = scene_generation_status(scene)
        already_generated = scene.generated.generated_at is not None
        prerequisites = _prerequisite_ids_for_scene(
            scene,
            ranked_scenes=ranked,
            ancestors=ancestors,
        )
        items.append(
            SceneGenerationPlanItem(
                scene_id=scene.id,
                title=scene.title or "Untitled",
                prerequisite_scene_ids=prerequisites,
                generatable=generatable,
                not_generatable_reason="" if generatable else _not_generatable_reason(scene),
                status=status,
                selected_by_default=generatable and not already_generated,
            )
        )

    return SceneGenerationPlan(items=tuple(items))
