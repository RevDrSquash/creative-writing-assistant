"""Scene-reading and scene-editing tools for the writing agent."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, ToolException, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.world.models import Scene, SceneBlueprint, unique_slug
from app.world.scene import (
    delete_scene as world_delete_scene,
)
from app.world.scene import (
    enacting_scenes,
    scene_generation_status,
    set_scene_metadata,
    set_scene_text,
)
from app.world.scene import (
    update_scene_blueprint as world_update_scene_blueprint,
)
from app.world.store import get_world, world_transaction


@tool
def read_scene(
    state: Annotated[dict[str, Any], InjectedState],
    scene_id: str = "",
) -> str:
    """Return the full Markdown text of a scene.

    Without `scene_id`, reads the scene currently open in the workspace.
    Call this before edits to anchor on the actual current wording.
    """

    current_id = state.get("current_scene_id", "")
    if scene_id and scene_id != current_id:
        scene = get_world().get_scene(scene_id)
        if scene is None:
            raise ToolException(f"No scene with id {scene_id}; call list_scenes for valid ids.")
        return scene.markdown

    current_scene = state.get("current_scene", "")
    return current_scene if isinstance(current_scene, str) else ""


@tool
def list_scenes(state: Annotated[dict[str, Any], InjectedState]) -> str:
    """List all scenes in order with their ids, titles, and summaries.

    The scene currently open in the workspace is marked with `(open)`.
    """

    current_id = state.get("current_scene_id", "")
    lines = []
    for position, scene in enumerate(get_world().scenes, start=1):
        marker = " (open)" if scene.id == current_id else ""
        summary = f" - {scene.summary}" if scene.summary else ""
        lines.append(f"{position}. {scene.title} [id: {scene.id}]{marker}{summary}")
    return "\n".join(lines)


@tool
def select_scene(
    scene_id: str,
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Open a different scene in the workspace so subsequent edits target it."""

    scene = get_world().get_scene(scene_id)
    if scene is None:
        raise ToolException(f"No scene with id {scene_id}; call list_scenes for valid ids.")

    current_id = state.get("current_scene_id", "")
    if isinstance(current_id, str) and current_id:
        _reject_if_scene_claimed(current_id)
    _persist_open_scene_text(state)
    return Command(
        update={
            "current_scene_id": scene.id,
            "current_scene": scene.markdown,
            "messages": [
                ToolMessage(
                    content=f"Opened scene '{scene.title}' (id: {scene.id}).",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def update_scene(
    state: Annotated[dict[str, Any], InjectedState],
    scene_id: str = "",
    title: str | None = None,
    summary: str | None = None,
) -> str:
    """Update an existing scene's title and/or summary.

    Without ``scene_id``, updates the scene currently open in the workspace.
    """

    target_id = scene_id or state.get("current_scene_id", "")
    if not target_id:
        raise ToolException("No scene specified and none is open; call list_scenes.")

    scene = get_world().get_scene(target_id)
    if scene is None:
        raise ToolException(f"No scene with id {target_id}; call list_scenes for valid ids.")

    _reject_if_scene_claimed(target_id)

    if title is None and summary is None:
        return "No changes requested (provide title and/or summary)."

    set_scene_metadata(target_id, title=title, summary=summary)

    parts = []
    if title is not None:
        parts.append(f"title to '{title}'")
    if summary is not None:
        parts.append(f"summary to '{summary}'")
    return f"Updated scene '{scene.title}' (id: {scene.id}): set {' and '.join(parts)}."


@tool
def delete_scene(
    scene_id: str,
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Delete a scene permanently.

    If the deleted scene was open, the first remaining scene is opened, or
    no scene is open when none remain.
    """

    world = get_world()
    scene = world.get_scene(scene_id)
    if scene is None:
        raise ToolException(f"No scene with id {scene_id}; call list_scenes for valid ids.")

    _reject_if_scene_claimed(scene_id)

    try:
        world_delete_scene(scene_id)
    except ValueError as exc:
        raise ToolException(str(exc)) from exc

    update: dict[str, Any] = {
        "messages": [
            ToolMessage(
                content=f"Deleted scene '{scene.title}' (id: {scene.id}).",
                tool_call_id=tool_call_id,
            )
        ]
    }
    if state.get("current_scene_id") == scene_id:
        if world.scenes:
            fallback = world.scenes[0]
            update["current_scene_id"] = fallback.id
            update["current_scene"] = fallback.markdown
        else:
            update["current_scene_id"] = ""
            update["current_scene"] = ""
    return Command(update=update)


def _persist_open_scene_text(state: dict[str, Any]) -> None:
    """Write the open scene's in-run text to the world before switching scenes."""

    current_id = state.get("current_scene_id", "")
    current_text = state.get("current_scene")
    if not isinstance(current_id, str) or not current_id or not isinstance(current_text, str):
        return
    scene = get_world().get_scene(current_id)
    if scene is not None and scene.markdown != current_text:
        _reject_if_scene_claimed(current_id)
        set_scene_text(current_id, current_text)


@tool
def read_scene_blueprint(
    state: Annotated[dict[str, Any], InjectedState],
    scene_id: str = "",
) -> str:
    """Return a scene's blueprint, generated artifacts, and generation status.

    Without `scene_id`, reads the scene currently open in the workspace.
    """

    target_id = scene_id or state.get("current_scene_id", "")
    if not target_id:
        raise ToolException("No scene specified and none is open; call list_scenes.")

    world = get_world()
    scene = world.get_scene(target_id)
    if scene is None:
        raise ToolException(f"No scene with id {target_id}; call list_scenes for valid ids.")

    blueprint = scene.blueprint
    generated = scene.generated
    bible = world.story_bible
    status = scene_generation_status(scene)
    lines = [
        f"# Scene card: {scene.title or 'Untitled'} [scene id: {scene.id}]",
        "",
        f"Generation status: {status}",
        "",
        "## Blueprint (editable inputs)",
        "",
        f"POV: {blueprint.pov.strip() or '(not set)'}",
        "",
        "### Premise",
        blueprint.premise.strip() or "(not set)",
        "",
        "### Purpose",
        blueprint.purpose.strip() or "(not set)",
        "",
        "### Starting state",
        blueprint.starting_state.strip() or "(not set)",
        "",
        "### Central conflict",
        blueprint.central_conflict.strip() or "(not set)",
        "",
        "### Required resolution",
        blueprint.required_resolution.strip() or "(not set)",
        "",
        "### Participating characters",
    ]
    if not blueprint.character_ids:
        lines.append("(none)")
    else:
        for character_id in blueprint.character_ids:
            character = bible.get_character(character_id)
            name = character.identity.name if character else f"unknown ({character_id})"
            lines.append(f"- {name} [character id: {character_id}]")

    lines.extend(["", "### Enacted events"])
    lines.extend(_event_lines(blueprint.event_ids, bible))
    lines.extend(["", "### Related events (context only)"])
    lines.extend(_event_lines(blueprint.related_event_ids, bible))

    lines.extend(
        [
            "",
            f"Constraints: {blueprint.constraints.strip() or '(none)'}",
            f"Notes: {blueprint.notes.strip() or '(none)'}",
            "",
            "## Generated (from workflow; regenerate overwrites)",
            "",
            "### Outline",
        ]
    )
    if not generated.outline:
        lines.append("(none)")
    else:
        for position, beat in enumerate(generated.outline, start=1):
            lines.append(f"{position}. {beat.strip() or '(empty)'}")

    lines.append("")
    lines.append("### Character Stances")
    if not generated.stances:
        lines.append("(none)")
    for stance in generated.stances:
        character = bible.get_character(stance.character_id)
        name = character.identity.name if character else f"unknown ({stance.character_id})"
        lines.append(f"#### {name} [character id: {stance.character_id}]")
        if stance.mood:
            lines.append("Mood:")
            for statement in stance.mood:
                lines.append(f"- {statement}")
        else:
            lines.append("Mood: (none)")
        lines.append(f"Intent: {stance.intent or '-'}")
        lines.append(f"Tactics: {stance.tactics or '-'}")
        lines.append(f"Stakes: {stance.stakes or '-'}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _event_lines(event_ids: list[str], bible: Any) -> list[str]:
    if not event_ids:
        return ["(none)"]
    lines: list[str] = []
    for event_id in event_ids:
        event = bible.get_event(event_id)
        if event is None:
            lines.append(f"- unknown id: {event_id}")
        else:
            title = event.title or "Untitled"
            lines.append(f"- {title} [event id: {event_id}]")
    return lines


@tool
def propose_scene(
    title: str,
    premise: str,
    purpose: str,
    pov: str,
    starting_state: str,
    central_conflict: str,
    required_resolution: str,
    character_ids: list[str],
    event_ids: list[str],
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    related_event_ids: list[str] | None = None,
    constraints: str = "",
    notes: str = "",
) -> Command:
    """Create a new titled scene with a populated blueprint and open it.

    ``title`` identifies the proposed scene in the UI before any prose exists.
    Does not run generation; the user triggers that from the scene editor.
    ``event_ids`` must include at least one enacted timeline event — every event
    dramatized on-page in this scene. Each event may be enacted by only one scene;
    use ``related_event_ids`` for context from events enacted elsewhere.
    ``character_ids`` and event ids are validated against the Story Bible.

    Scene frame (``starting_state``, ``central_conflict``, ``required_resolution``):
    one or two sentences each. Specify only what is necessary for the scene to fit the
    story — how it opens given what came before, the conflict it exists to dramatize, and
    the outcome later scenes depend on. Do not restate ``premise`` or ``purpose``, and do
    not pre-plan beats; the generation workflow owns beat-level decisions.
    """

    if not title.strip():
        raise ToolException("Provide a non-empty scene title.")
    for field_name, value in (
        ("starting_state", starting_state),
        ("central_conflict", central_conflict),
        ("required_resolution", required_resolution),
    ):
        if not value.strip():
            raise ToolException(f"Provide a non-empty {field_name}.")
    resolved_characters = _resolve_scene_character_ids(character_ids)
    enacted_ids, related_ids = _resolve_scene_event_ids(event_ids, related_event_ids or [])

    current_id = state.get("current_scene_id", "")
    if isinstance(current_id, str) and current_id:
        _reject_if_scene_claimed(current_id)
    _persist_open_scene_text(state)
    with world_transaction() as world:
        scene = Scene(
            title=title.strip(),
            blueprint=SceneBlueprint(
                premise=premise,
                purpose=purpose,
                pov=pov,
                starting_state=starting_state.strip(),
                central_conflict=central_conflict.strip(),
                required_resolution=required_resolution.strip(),
                character_ids=resolved_characters,
                event_ids=enacted_ids,
                related_event_ids=related_ids,
                constraints=constraints,
                notes=notes,
            ),
        )
        scene.id = unique_slug("scene_", scene.title, {item.id for item in world.scenes})
        world.scenes.append(scene)

    return Command(
        update={
            "current_scene_id": scene.id,
            "current_scene": scene.markdown,
            "messages": [
                ToolMessage(
                    content=(
                        f"Proposed scene '{scene.title}' (id: {scene.id}) with blueprint "
                        "and opened it. The user can generate prose from the editor."
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def update_scene_blueprint(
    state: Annotated[dict[str, Any], InjectedState],
    scene_id: str = "",
    premise: str | None = None,
    purpose: str | None = None,
    pov: str | None = None,
    starting_state: str | None = None,
    central_conflict: str | None = None,
    required_resolution: str | None = None,
    character_ids: list[str] | None = None,
    event_ids: list[str] | None = None,
    related_event_ids: list[str] | None = None,
    constraints: str | None = None,
    notes: str | None = None,
) -> str:
    """Partially update a scene blueprint on an existing scene.

    Without ``scene_id``, updates the scene currently open in the workspace.
    Changing the blueprint after generation marks the scene stale until regenerated.
    When updating ``event_ids``, enact every event dramatized on-page; each event may be
    enacted by only one scene.
    """

    target_id = scene_id or state.get("current_scene_id", "")
    if not target_id:
        raise ToolException("No scene specified and none is open; call list_scenes.")

    scene = get_world().get_scene(target_id)
    if scene is None:
        raise ToolException(f"No scene with id {target_id}; call list_scenes for valid ids.")

    _reject_if_scene_claimed(target_id)

    resolved_characters = (
        _resolve_scene_character_ids(character_ids) if character_ids is not None else None
    )
    resolved_enacted: list[str] | None = None
    resolved_related: list[str] | None = None
    if event_ids is not None:
        related = related_event_ids if related_event_ids is not None else []
        resolved_enacted, resolved_related = _resolve_scene_event_ids(
            event_ids,
            related,
            exclude_scene_id=target_id,
        )
    elif related_event_ids is not None:
        resolved_related = _validate_event_ids(related_event_ids)
        enacted_set = set(get_world().get_scene(target_id).blueprint.event_ids)
        resolved_related = [
            event_id for event_id in resolved_related if event_id not in enacted_set
        ]

    if (
        premise is None
        and purpose is None
        and pov is None
        and starting_state is None
        and central_conflict is None
        and required_resolution is None
        and character_ids is None
        and event_ids is None
        and related_event_ids is None
        and constraints is None
        and notes is None
    ):
        return "No changes requested."

    world_update_scene_blueprint(
        target_id,
        premise=premise,
        purpose=purpose,
        pov=pov,
        starting_state=starting_state,
        central_conflict=central_conflict,
        required_resolution=required_resolution,
        character_ids=resolved_characters,
        event_ids=resolved_enacted,
        related_event_ids=resolved_related,
        constraints=constraints,
        notes=notes,
    )
    return (
        f"Updated blueprint for scene '{scene.title}' (id: {scene.id}). "
        f"Generation status is now: {scene_generation_status(get_world().get_scene(target_id))}."
    )


def _resolve_scene_character_ids(character_ids: list[str]) -> list[str]:
    """Resolve provided ids to real character ids, rejecting unknown ones."""

    bible = get_world().story_bible
    resolved: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw_id in character_ids:
        match = bible.resolve_character_id(raw_id)
        if match is None:
            unknown.append(raw_id)
        elif match not in seen:
            seen.add(match)
            resolved.append(match)
    if unknown:
        raise ToolException(_unknown_character_detail(unknown))
    return resolved


def _unknown_character_detail(unknown_ids: list[str]) -> str:
    bible = get_world().story_bible
    unknown = ", ".join(unknown_ids)
    if bible.characters:
        listing = ", ".join(
            f"{character.identity.name or 'Unnamed'} [{character.id}]"
            for character in bible.characters
        )
        detail = f"Valid characters: {listing}"
    else:
        detail = "No characters exist yet; create one first."
    return f"Unknown character_id(s): {unknown}. {detail}"


def _resolve_scene_event_ids(
    event_ids: list[str],
    related_event_ids: list[str],
    *,
    exclude_scene_id: str | None = None,
) -> tuple[list[str], list[str]]:
    """Validate enacted and related event ids, rejecting unknown or duplicate enactments."""

    enacted = _validate_event_ids(event_ids)
    if not enacted:
        raise ToolException(
            "A scene must enact at least one event; pass event_ids from read_timeline."
        )
    world = get_world()
    for event_id in enacted:
        for scene in enacting_scenes(world, event_id):
            if exclude_scene_id and scene.id == exclude_scene_id:
                continue
            raise ToolException(
                f"Event '{event_id}' is already enacted by scene "
                f"'{scene.title}' (id: {scene.id}). Each event may be enacted by only one "
                "scene; use related_event_ids for context from events enacted elsewhere."
            )
    enacted_set = set(enacted)
    related = [
        event_id
        for event_id in _validate_event_ids(related_event_ids)
        if event_id not in enacted_set
    ]
    return enacted, related


def _validate_event_ids(event_ids: list[str]) -> list[str]:
    """Return de-duplicated, existing event ids, rejecting unknown ones."""

    bible = get_world().story_bible
    resolved: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw_id in event_ids:
        if bible.get_event(raw_id) is None:
            unknown.append(raw_id)
        elif raw_id not in seen:
            seen.add(raw_id)
            resolved.append(raw_id)
    if unknown:
        raise ToolException(_unknown_event_detail(unknown))
    return resolved


def _unknown_event_detail(unknown_ids: list[str]) -> str:
    bible = get_world().story_bible
    unknown = ", ".join(unknown_ids)
    if bible.timeline:
        listing = ", ".join(f"{event.title or 'Untitled'} [{event.id}]" for event in bible.timeline)
        detail = f"Valid events: {listing}"
    else:
        detail = "No events exist yet; add one to the timeline first."
    return f"Unknown event_id(s): {unknown}. {detail}"


SCENE_TOOLS = [
    read_scene,
    read_scene_blueprint,
    list_scenes,
    propose_scene,
    update_scene_blueprint,
    select_scene,
    update_scene,
    delete_scene,
]


def _reject_if_scene_claimed(scene_id: str) -> None:
    """Raise when a running job holds a claim on ``scene_id``."""

    from app.graphs.jobs import get_job_manager, scene_claim_key

    job = get_job_manager().claim_for(scene_claim_key(scene_id))
    if job is None:
        return
    world = get_world()
    scene = world.get_scene(scene_id)
    title = scene.title if scene is not None else scene_id
    raise ToolException(
        f"Scene '{title}' is currently being generated; wait for the job to finish."
    )
