"""Structured Story Bible editing forms for the workspace center panel.

Forms bind directly to the in-memory World object and write through to disk
on change. Derived state panels are read-only views computed by the replay
engine for a selectable timeline position.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from app.ui.save_helpers import save_world_ui
from app.world.models import (
    AddIntimacy,
    AddWorldStateEntry,
    Character,
    Event,
    EventRelation,
    EventRelationKind,
    Intimacy,
    IntimacyEvidence,
    RemoveIntimacy,
    RemoveWorldStateEntry,
    Scene,
    SceneCharacterStance,
    SetIntimacyStrength,
    Signal,
    StoryBible,
    UpdateIntimacy,
    UpdateWorldStateEntry,
    WorldFact,
    WorldStateEntry,
    unique_slug,
)
from app.world.relations import (
    RelationValidationError,
    chronological_order,
    diagnostics_for_relation,
    normalize_relation,
    relation_diagnostics,
)
from app.world.replay import derive_state_at, effect_diagnostics
from app.world.scene import enacting_scenes, prune_event_links
from app.world.store import get_world

_STRENGTH_OPTIONS = {
    "dormant": "Dormant",
    "minor": "Minor",
    "major": "Major",
    "defining": "Defining",
}
_BASELINE_STRENGTH_OPTIONS = {"minor": "Minor", "major": "Major", "defining": "Defining"}
_EVIDENCE_DIRECTION_OPTIONS = {
    "supports": "Supports",
    "contradicts": "Contradicts",
}
_EVIDENCE_STRENGTH_OPTIONS = {
    1: "1 · Incidental",
    2: "2 · Noticeable",
    3: "3 · Meaningful",
    4: "4 · Pivotal",
    5: "5 · Identity-shaking",
}
_WORLD_STATE_KIND_OPTIONS = {
    "pressure": "Pressure",
    "thread": "Thread",
    "consequence": "Consequence",
}
_RELATION_KIND_OPTIONS = {
    "follows": "Follows (loose order)",
    "directly_follows": "Directly follows (tight continuity)",
    "depends_on": "Depends on (causal)",
    "during": "During (concurrent)",
}
# For directed kinds the user picks which event is the follower (the later one)
# instead of inferring it from timeline list position.
_RELATION_DIRECTION_OPTIONS = {
    "this_follows": "This event follows the other",
    "other_follows": "The other event follows this one",
}
_CONNECT_KIND_BUTTONS: dict[EventRelationKind, str] = {
    "follows": "Follows…",
    "directly_follows": "Directly follows…",
    "depends_on": "Depends on…",
    "during": "During…",
}
_SELECTED_NODE_STYLE = "fill:#e3f2fd,stroke:#1976d2,stroke-width:3px"
_GRAPH_ZOOM_MIN = 0.5
_GRAPH_ZOOM_MAX = 2.0
_GRAPH_ZOOM_STEP = 0.25
_GRAPH_ZOOM_DEFAULT = 1.0
_MERMAID_CONFIG = {"flowchart": {"useMaxWidth": False}}
# Wheel over the graph scrolls it horizontally; Ctrl+wheel zooms (emitted to the
# server as +1/-1 steps). preventDefault stops the page from scrolling instead.
_GRAPH_WHEEL_JS = """(e) => {
    if (e.ctrlKey) {
        e.preventDefault();
        emit(e.deltaY < 0 ? 1 : -1);
    } else if (e.deltaY !== 0 && !e.shiftKey) {
        e.preventDefault();
        e.currentTarget.scrollLeft += e.deltaY;
    }
}"""


# --- shared helpers ---------------------------------------------------------


def _save_on_change(element: ui.element) -> None:
    element.on_value_change(lambda _: save_world_ui())


def _bound_input(target: object, field: str, *, placeholder: str = "") -> ui.input:
    element = ui.input(placeholder=placeholder).classes("w-full").props("dense outlined")
    element.bind_value(target, field)
    _save_on_change(element)
    return element


def _bound_textarea(
    target: object,
    field: str,
    *,
    placeholder: str = "",
    rows: int | None = None,
) -> ui.textarea:
    props = "dense outlined autogrow"
    if rows is not None:
        props = f"{props} rows={rows}"
    element = ui.textarea(placeholder=placeholder).classes("w-full").props(props)
    element.bind_value(target, field)
    _save_on_change(element)
    return element


def _bound_select(target: object, field: str, options: dict) -> ui.select:
    element = ui.select(options).props("dense outlined")
    element.bind_value(target, field)
    _save_on_change(element)
    return element


def _bound_int_select(target: object, field: str, options: dict[int, str]) -> ui.select:
    """Bind a select whose option keys are ints (NiceGUI may emit them as strings)."""

    element = ui.select(options).props("dense outlined")
    element.bind_value(target, field)

    def on_change(event) -> None:
        raw = event.value
        if raw is not None and not isinstance(raw, int):
            try:
                setattr(target, field, int(raw))
            except (TypeError, ValueError):
                pass
        save_world_ui()

    element.on_value_change(on_change)
    return element


def _field_label(text: str) -> None:
    ui.label(text).classes("text-sm font-medium text-grey-8")


def _render_tags_input(target: object, field: str = "tags") -> None:
    tags_input = (
        ui.input(
            placeholder="Tags (comma-separated)",
            value=", ".join(getattr(target, field)),
        )
        .classes("w-full")
        .props("dense outlined")
    )

    def apply(event) -> None:
        raw = event.value or ""
        setattr(target, field, [tag.strip() for tag in raw.split(",") if tag.strip()])
        save_world_ui()

    tags_input.on_value_change(apply)


def _delete_button(on_click: Callable, tooltip: str) -> ui.button:
    button = ui.button(icon="delete", on_click=on_click)
    button.props("flat round dense size=sm color=grey-7")
    button.tooltip(tooltip)
    return button


def _timeline_position_options(bible: StoryBible) -> dict[int, str]:
    options = {0: "Baseline (before any events)"}
    for index, event in enumerate(chronological_order(bible)):
        options[index + 1] = f"After {index + 1}. {event.title or 'Untitled event'}"
    return options


def _chronological_event_index(bible: StoryBible, event_id: str) -> int:
    for index, event in enumerate(chronological_order(bible)):
        if event.id == event_id:
            return index
    return 0


# --- narrative style --------------------------------------------------------


def render_narrative_style_form() -> None:
    bible = get_world().story_bible
    ui.label("Narrative Style").classes("text-xl font-semibold")
    ui.label("The intended premise, tone, themes, and writing style for this project.").classes(
        "text-grey-7"
    )
    _field_label("Premise")
    _bound_textarea(bible, "premise", placeholder="What is the story about?")
    _field_label("Tone")
    _bound_textarea(bible, "tone", placeholder="Mood, atmosphere, narrative voice...")
    _field_label("Themes")
    _bound_textarea(bible, "themes", placeholder="Recurring ideas and motifs...")
    _field_label("Writing style")
    _bound_textarea(bible, "writing_style", placeholder="Prose rhythm, sentence style, POV...")


# --- world facts and world state --------------------------------------------


def render_world_form() -> None:
    bible = get_world().story_bible
    ui.label("World").classes("text-xl font-semibold")

    ui.label("World Facts").classes("text-lg font-semibold mt-2")
    ui.label("Stable setting facts. Locations and lore are world facts.").classes(
        "text-grey-7 text-sm"
    )

    @ui.refreshable
    def facts_section() -> None:
        if not bible.world_facts:
            ui.label("No world facts yet.").classes("text-grey-7")
        for fact in bible.world_facts:
            _render_world_fact_card(fact, facts_section.refresh)

    facts_section()

    def add_fact() -> None:
        fact = WorldFact()
        fact.id = unique_slug("fact_", "", {item.id for item in bible.world_facts})
        bible.world_facts.append(fact)
        save_world_ui()
        facts_section.refresh()

    ui.button("Add world fact", icon="add", on_click=add_fact).props("flat")

    ui.separator()
    ui.label("Baseline World State").classes("text-lg font-semibold")
    ui.label(
        "Pressures, open threads, and consequences in effect before any timeline events."
    ).classes("text-grey-7 text-sm")

    @ui.refreshable
    def baseline_section() -> None:
        if not bible.baseline_world_state:
            ui.label("No baseline world state entries yet.").classes("text-grey-7")
        for entry in bible.baseline_world_state:
            _render_world_state_entry_row(
                entry, bible.baseline_world_state, baseline_section.refresh
            )

    baseline_section()

    def add_entry() -> None:
        entry = WorldStateEntry()
        entry.id = unique_slug(
            "wse_",
            "",
            {item.id for item in bible.baseline_world_state},
        )
        bible.baseline_world_state.append(entry)
        save_world_ui()
        baseline_section.refresh()

    ui.button("Add world state entry", icon="add", on_click=add_entry).props("flat")

    ui.separator()
    _render_derived_world_state(bible)


def _render_world_fact_card(fact: WorldFact, refresh: Callable[[], None]) -> None:
    with ui.card().classes("w-full"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            title = ui.input(placeholder="Fact title").classes("grow").props("dense outlined")
            title.bind_value(fact, "title")
            _save_on_change(title)

            def delete_fact(fact: WorldFact = fact) -> None:
                bible = get_world().story_bible
                bible.world_facts = [item for item in bible.world_facts if item.id != fact.id]
                save_world_ui()
                refresh()

            _delete_button(delete_fact, "Delete fact")
        _bound_textarea(fact, "text", placeholder="What is true about the world?")
        _render_tags_input(fact)


def _render_world_state_entry_row(
    entry: WorldStateEntry,
    entries: list[WorldStateEntry],
    refresh: Callable[[], None],
) -> None:
    with ui.row().classes("w-full items-center no-wrap gap-2"):
        _bound_select(entry, "kind", _WORLD_STATE_KIND_OPTIONS)
        text = ui.input(placeholder="What is active or changing?").classes("grow")
        text.props("dense outlined")
        text.bind_value(entry, "text")
        _save_on_change(text)

        def delete_entry(entry: WorldStateEntry = entry) -> None:
            entries[:] = [item for item in entries if item.id != entry.id]
            save_world_ui()
            refresh()

        _delete_button(delete_entry, "Remove entry")


def _render_derived_world_state(bible: StoryBible) -> None:
    ui.label("Derived World State").classes("text-lg font-semibold")
    ui.label("Read-only view of the world state at a timeline position.").classes(
        "text-grey-7 text-sm"
    )

    position = {"value": len(chronological_order(bible))}
    options = _timeline_position_options(bible)
    select = ui.select(options, value=position["value"], label="As of").classes("w-full")
    select.props("dense outlined")

    @ui.refreshable
    def derived_view() -> None:
        derived = derive_state_at(bible, position["value"])
        if not derived.world_state:
            ui.label("No active world state entries.").classes("text-grey-7")
        for entry in derived.world_state:
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.badge(_WORLD_STATE_KIND_OPTIONS[entry.kind]).props("outline color=primary")
                ui.label(entry.text)

    def on_position_change(event) -> None:
        if isinstance(event.value, int):
            position["value"] = event.value
            derived_view.refresh()

    select.on_value_change(on_position_change)
    derived_view()


# --- characters --------------------------------------------------------------


def render_characters_form(active_path: str) -> None:
    if active_path == "/workspace/characters":
        _render_character_list()
        return

    character_id = active_path.rsplit("/", maxsplit=1)[-1]
    character = get_world().story_bible.get_character(character_id)
    if character is None:
        ui.label("Character not found.").classes("text-negative")
        ui.button("Back to characters", on_click=lambda: ui.navigate.to("/workspace/characters"))
        return
    _render_character_detail(character)


def _character_list_subtitle(character: Character) -> str | None:
    intimacies = character.baseline_state.intimacies
    if intimacies and intimacies[0].text.strip():
        return intimacies[0].text.strip()
    traits = character.identity.traits.strip()
    return traits or None


def _render_character_list() -> None:
    bible = get_world().story_bible
    ui.label("Characters").classes("text-xl font-semibold")

    @ui.refreshable
    def rows() -> None:
        if not bible.characters:
            ui.label("No characters yet.").classes("text-grey-7")
        for character in bible.characters:
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    with ui.column().classes("gap-0"):
                        ui.label(character.identity.name or "Unnamed character").classes(
                            "font-semibold"
                        )
                        subtitle = _character_list_subtitle(character)
                        if subtitle:
                            ui.label(subtitle).classes("text-grey-7 text-sm")
                    ui.button(
                        "Open",
                        on_click=lambda character=character: ui.navigate.to(
                            f"/workspace/characters/{character.id}"
                        ),
                    ).props("flat")

    rows()

    def add_character() -> None:
        character = Character()
        character.id = unique_slug("char_", "", {item.id for item in bible.characters})
        bible.characters.append(character)
        save_world_ui()
        ui.navigate.to(f"/workspace/characters/{character.id}")

    ui.button("Add character", icon="add", on_click=add_character).props("flat")


def _render_character_detail(character: Character) -> None:
    with ui.row().classes("w-full items-center no-wrap gap-2"):
        ui.button(
            icon="arrow_back", on_click=lambda: ui.navigate.to("/workspace/characters")
        ).props("flat round dense")
        name = ui.input(placeholder="Character name").classes("grow text-xl font-semibold")
        name.props("borderless dense")
        name.bind_value(character.identity, "name")
        _save_on_change(name)
        _delete_button(lambda: _confirm_delete_character(character), "Delete character")

    with ui.card().classes("w-full"):
        ui.label("Identity").classes("text-lg font-semibold")
        ui.label("Stable identity; not affected by the timeline.").classes("text-grey-7 text-sm")
        _field_label("Traits")
        _bound_textarea(character.identity, "traits", placeholder="Personality traits...")
        _field_label("Appearance")
        _bound_textarea(character.identity, "appearance", placeholder="Physical appearance...")
        _field_label("Background")
        _bound_textarea(character.identity, "background", placeholder="History and background...")
        _field_label("Voice")
        _bound_textarea(character.identity, "voice", placeholder="Speech patterns, diction...")

    with ui.card().classes("w-full"):
        ui.label("Baseline State").classes("text-lg font-semibold")
        ui.label("The character's state at the start of the timeline.").classes(
            "text-grey-7 text-sm"
        )
        _field_label("Intimacies")

        @ui.refreshable
        def intimacies_section() -> None:
            intimacies = character.baseline_state.intimacies
            if not intimacies:
                ui.label("No intimacies yet.").classes("text-grey-7")
            for intimacy in intimacies:
                _render_intimacy_row(intimacy, intimacies, intimacies_section.refresh)

        intimacies_section()

        def add_intimacy() -> None:
            intimacy = Intimacy()
            intimacy.id = unique_slug(
                "intim_",
                "",
                {item.id for item in character.baseline_state.intimacies},
            )
            character.baseline_state.intimacies.append(intimacy)
            save_world_ui()
            intimacies_section.refresh()

        ui.button("Add intimacy", icon="add", on_click=add_intimacy).props("flat")

    _render_derived_character_state(character)


def _render_intimacy_row(
    intimacy: Intimacy,
    intimacies: list[Intimacy],
    refresh: Callable[[], None],
) -> None:
    with ui.row().classes("w-full items-center no-wrap gap-2"):
        text = ui.input(placeholder="e.g. Hungry for knowledge").classes("grow")
        text.props("dense outlined")
        text.bind_value(intimacy, "text")
        _save_on_change(text)
        _bound_select(intimacy, "strength", _BASELINE_STRENGTH_OPTIONS)

        def delete_intimacy(intimacy: Intimacy = intimacy) -> None:
            intimacies[:] = [item for item in intimacies if item.id != intimacy.id]
            save_world_ui()
            refresh()

        _delete_button(delete_intimacy, "Remove intimacy")


def _render_derived_character_state(character: Character) -> None:
    bible = get_world().story_bible
    with ui.card().classes("w-full"):
        ui.label("Derived State").classes("text-lg font-semibold")
        ui.label("Read-only view of this character at a timeline position.").classes(
            "text-grey-7 text-sm"
        )

        position = {"value": len(chronological_order(bible))}
        select = ui.select(
            _timeline_position_options(bible),
            value=position["value"],
            label="As of",
        ).classes("w-full")
        select.props("dense outlined")

        @ui.refreshable
        def derived_view() -> None:
            derived = derive_state_at(bible, position["value"]).characters.get(character.id)
            if derived is None:
                ui.label("Character not present in derived state.").classes("text-grey-7")
                return
            if not derived.intimacies:
                ui.label("No intimacies.").classes("text-grey-7")
            for intimacy in derived.intimacies:
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    ui.badge(_STRENGTH_OPTIONS[intimacy.strength]).props("outline color=primary")
                    ui.label(intimacy.text)

        def on_position_change(event) -> None:
            if isinstance(event.value, int):
                position["value"] = event.value
                derived_view.refresh()

        select.on_value_change(on_position_change)
        derived_view()


async def _confirm_delete_character(character: Character) -> None:
    name = character.identity.name or "this character"
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Delete {name}? Events keep their signals; replay will skip them.")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Delete", color="negative", on_click=lambda: dialog.submit(True))

    if not await dialog:
        return

    bible = get_world().story_bible
    bible.characters = [item for item in bible.characters if item.id != character.id]
    save_world_ui()
    ui.navigate.to("/workspace/characters")


# --- timeline and events ------------------------------------------------------


def render_timeline_form(active_path: str) -> None:
    if active_path == "/workspace/timeline":
        _render_timeline_list()
        return

    event_id = active_path.rsplit("/", maxsplit=1)[-1]
    event = get_world().story_bible.get_event(event_id)
    if event is None:
        ui.label("Event not found.").classes("text-negative")
        ui.button("Back to timeline", on_click=lambda: ui.navigate.to("/workspace/timeline"))
        return
    _render_event_detail(event)


def _render_timeline_list() -> None:
    bible = get_world().story_bible
    state: dict[str, object] = {
        "selected_id": None,
        "connect_kind": None,
        "zoom": _GRAPH_ZOOM_DEFAULT,
    }

    ui.label("Timeline").classes("text-xl font-semibold")
    ui.label(
        "Story events linked by relationships. Chronology is derived from relations; "
        "unrelated events fall back to creation order. Click a graph node to edit it."
    ).classes("text-grey-7")

    def refresh_graph_and_pane() -> None:
        graph_section.refresh()
        selection_pane.refresh()

    def on_structure_change() -> None:
        # Title/relation changes update node labels and edges; keep the editor mounted.
        graph_section.refresh()

    def select_event(event_id: str | None) -> None:
        state["selected_id"] = event_id
        state["connect_kind"] = None
        refresh_graph_and_pane()

    def apply_connect(target_id: str) -> None:
        selected_id = state["selected_id"]
        connect_kind = state["connect_kind"]
        if not isinstance(selected_id, str) or not isinstance(connect_kind, str):
            return
        try:
            normalize_relation(bible, connect_kind, selected_id, target_id)
        except RelationValidationError as exc:
            ui.notify(str(exc), type="negative")
            return
        bible.event_relations.append(
            EventRelation(kind=connect_kind, source_id=selected_id, target_id=target_id)
        )
        save_world_ui()
        state["connect_kind"] = None
        refresh_graph_and_pane()

    def on_node_click(event_args) -> None:
        # In the browser the mermaid DOM id is "<element>_mermaid-flowchart-<id>-<n>";
        # NiceGUI strips the outer parts but leaves the "flowchart-" diagram prefix.
        node_id = event_args.node_id.removeprefix("flowchart-")
        if bible.get_event(node_id) is None:
            return
        if state["connect_kind"] is not None:
            apply_connect(node_id)
            return
        select_event(node_id)

    def current_zoom() -> float:
        zoom = state["zoom"]
        return float(zoom) if isinstance(zoom, (int, float)) else _GRAPH_ZOOM_DEFAULT

    def set_zoom(factor: float) -> None:
        clamped = max(_GRAPH_ZOOM_MIN, min(_GRAPH_ZOOM_MAX, factor))
        state["zoom"] = round(clamped, 2)
        # Restyle the existing diagram in place so zooming does not re-render the
        # SVG or reset the horizontal scroll position.
        diagram = state.get("diagram")
        zoom_label = state.get("zoom_label")
        if isinstance(diagram, ui.mermaid) and not diagram.is_deleted:
            diagram.style(f"zoom: {state['zoom']}")
        if isinstance(zoom_label, ui.button) and not zoom_label.is_deleted:
            zoom_label.set_text(f"{int(current_zoom() * 100)}%")

    def step_zoom(steps: int) -> None:
        set_zoom(current_zoom() + steps * _GRAPH_ZOOM_STEP)

    @ui.refreshable
    def graph_section() -> None:
        if not bible.timeline:
            return
        selected_id = state["selected_id"] if isinstance(state["selected_id"], str) else None
        zoom = current_zoom()
        mermaid_source = _build_timeline_mermaid(bible, selected_id=selected_id)
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.label("Event graph").classes("text-lg font-semibold")
                ui.button(
                    icon="zoom_out",
                    on_click=lambda: step_zoom(-1),
                ).props("flat round dense").tooltip("Zoom out (Ctrl+wheel)")
                zoom_label = ui.button(
                    f"{int(zoom * 100)}%",
                    on_click=lambda: set_zoom(_GRAPH_ZOOM_DEFAULT),
                ).props("flat dense")
                zoom_label.tooltip("Reset zoom")
                ui.button(
                    icon="zoom_in",
                    on_click=lambda: step_zoom(1),
                ).props("flat round dense").tooltip("Zoom in (Ctrl+wheel)")
            container = ui.element("div").classes("w-full overflow-x-auto")
            container.mark("timeline-graph-scroll")
            container.on(
                "wheel",
                handler=lambda e: step_zoom(int(e.args)),
                js_handler=_GRAPH_WHEEL_JS,
                throttle=0.05,
            )
            with container:
                diagram = ui.mermaid(
                    mermaid_source,
                    config=_MERMAID_CONFIG,
                    on_node_click=on_node_click,
                )
                diagram.mark("timeline-graph")
                diagram.style(f"zoom: {zoom}; transform-origin: top left;")
            state["diagram"] = diagram
            state["zoom_label"] = zoom_label
            _render_timeline_legend()

        relation_warnings = relation_diagnostics(bible)
        effect_warnings = effect_diagnostics(bible)
        if relation_warnings or effect_warnings:
            with ui.card().classes("w-full bg-orange-1"):
                ui.label("Timeline warnings").classes("text-warning font-semibold")
                for warning in relation_warnings:
                    ui.label(warning.message).classes("text-sm")
                for warning in effect_warnings:
                    ui.label(warning.message).classes("text-sm")

    graph_section()

    def append_event() -> None:
        event = Event()
        event.id = unique_slug("event_", "", {item.id for item in bible.timeline})
        bible.timeline.append(event)
        save_world_ui()
        select_event(event.id)

    def start_connect(kind: EventRelationKind) -> None:
        state["connect_kind"] = kind
        selection_pane.refresh()

    def cancel_connect() -> None:
        state["connect_kind"] = None
        selection_pane.refresh()

    @ui.refreshable
    def selection_pane() -> None:
        selected_id = state["selected_id"] if isinstance(state["selected_id"], str) else None
        event = bible.get_event(selected_id) if selected_id else None
        if event is None:
            if not bible.timeline:
                ui.label("No events yet.").classes("text-grey-7")
            else:
                ui.label("Click an event in the graph to view and edit it.").classes("text-grey-7")
            return

        chron_index = _chronological_event_index(bible, event.id)
        connect_kind = state["connect_kind"]

        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.label(f"Event {chron_index + 1} of {len(chronological_order(bible))}").classes(
                "text-grey-7"
            )
            ui.space()
            _delete_button(
                lambda: _confirm_delete_event(
                    event,
                    on_deleted=lambda: select_event(None),
                ),
                "Delete event",
            )
            ui.button(
                icon="close",
                on_click=lambda: select_event(None),
            ).props("flat round dense").tooltip("Deselect")

        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
            ui.label("Connect:").classes("text-sm text-grey-7")
            for kind, label in _CONNECT_KIND_BUTTONS.items():
                button = ui.button(
                    label,
                    on_click=lambda kind=kind: start_connect(kind),
                ).props("flat dense")
                button.mark(f"connect-{kind}")
                if connect_kind == kind:
                    button.props("color=primary")

        if isinstance(connect_kind, str):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.label("Click the other event in the graph to create the connection...").classes(
                    "text-sm text-primary grow"
                )
                ui.button("Cancel", on_click=cancel_connect).props("flat dense")

        _render_event_editor(event, on_structure_change=on_structure_change)

    selection_pane()
    ui.button(
        "Add event",
        icon="add",
        on_click=append_event,
    ).props("flat")


def _render_event_detail(event: Event) -> None:
    bible = get_world().story_bible
    chron_index = _chronological_event_index(bible, event.id)

    with ui.row().classes("w-full items-center no-wrap gap-2"):
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/workspace/timeline")).props(
            "flat round dense"
        )
        ui.label(f"Event {chron_index + 1} of {len(chronological_order(bible))}").classes(
            "text-grey-7"
        )
        ui.space()
        _delete_button(lambda: _confirm_delete_event(event), "Delete event")

    _render_event_editor(event)


def _render_event_editor(
    event: Event,
    *,
    on_structure_change: Callable[[], None] | None = None,
) -> None:
    """Render the editable body of an event (title, effects, signals, relationships).

    ``on_structure_change`` is called when graph-visible fields change (title, relations)
    so the timeline Mermaid diagram can refresh without unmounting this editor.
    """

    bible = get_world().story_bible
    chron_index = _chronological_event_index(bible, event.id)
    notify_structure = on_structure_change or (lambda: None)

    with ui.card().classes("w-full"):
        _field_label("Title")
        title_input = _bound_input(event, "title", placeholder="What happens, objectively...")
        title_input.on_value_change(lambda _: notify_structure())
        _field_label("Description")
        _bound_textarea(event, "description", placeholder="The objective story beat...")

    entry_options = _entry_options_before(bible, chron_index)

    with ui.card().classes("w-full"):
        ui.label("World State Effects").classes("text-lg font-semibold")
        ui.label("How this event changes the active world state.").classes("text-grey-7 text-sm")

        @ui.refreshable
        def effects_section() -> None:
            if not event.world_state_effects:
                ui.label("No world state effects.").classes("text-grey-7")
            for effect in event.world_state_effects:
                _render_world_state_effect_row(
                    event, effect, entry_options, effects_section.refresh
                )

        effects_section()

        def add_effect(effect) -> None:
            event.world_state_effects.append(effect)
            save_world_ui()
            effects_section.refresh()

        with ui.button("Add effect", icon="add").props("flat"):
            with ui.menu():
                ui.menu_item(
                    "Add world state entry",
                    on_click=lambda: add_effect(AddWorldStateEntry()),
                )
                ui.menu_item(
                    "Update world state entry",
                    on_click=lambda: add_effect(UpdateWorldStateEntry(text="")),
                )
                ui.menu_item(
                    "Remove world state entry",
                    on_click=lambda: add_effect(RemoveWorldStateEntry()),
                )

    with ui.card().classes("w-full"):
        ui.label("Signals").classes("text-lg font-semibold")
        ui.label("How specific characters interpret this event.").classes("text-grey-7 text-sm")

        @ui.refreshable
        def signals_section() -> None:
            if not event.signals:
                ui.label("No signals.").classes("text-grey-7")
            for signal in event.signals:
                _render_signal_card(event, signal, chron_index, signals_section.refresh)

        signals_section()

        def add_signal() -> None:
            characters = get_world().story_bible.characters
            signal = Signal(character_id=characters[0].id if characters else "")
            event.signals.append(signal)
            save_world_ui()
            signals_section.refresh()

        ui.button("Add signal", icon="add", on_click=add_signal).props("flat")

    with ui.card().classes("w-full"):
        ui.label("Relationships").classes("text-lg font-semibold")
        ui.label(
            "Typed links to other events. For directed kinds, choose which event is "
            "the follower (the later one); depends_on marks causal dependency; "
            "during marks concurrent events."
        ).classes("text-grey-7 text-sm")

        @ui.refreshable
        def relations_section() -> None:
            relations = bible.relations_for_event(event.id)
            all_relations = relations.incoming + relations.outgoing + relations.concurrent
            if not all_relations:
                ui.label("No relationships.").classes("text-grey-7")

            def refresh_relations() -> None:
                relations_section.refresh()
                notify_structure()

            for relation in all_relations:
                _render_event_relation_row(event, relation, refresh_relations)

        relations_section()

        other_event_options = {
            other.id: other.title or "Untitled event"
            for other in bible.timeline
            if other.id != event.id
        }

        if other_event_options:
            add_state = {
                "kind": "follows",
                "direction": "this_follows",
                "other_id": next(iter(other_event_options)),
            }

            with ui.row().classes("w-full items-end no-wrap gap-2"):
                kind_select = ui.select(
                    _RELATION_KIND_OPTIONS,
                    label="Kind",
                    value=add_state["kind"],
                ).classes("grow")
                kind_select.props("dense outlined")
                direction_select = ui.select(
                    _RELATION_DIRECTION_OPTIONS,
                    label="Direction",
                    value=add_state["direction"],
                ).classes("grow")
                direction_select.props("dense outlined")
                direction_select.mark("relation-direction-select")
                other_select = ui.select(
                    other_event_options,
                    label="Other event",
                    value=add_state["other_id"],
                ).classes("grow")
                other_select.props("dense outlined")

                def on_kind_change(event_change) -> None:
                    add_state["kind"] = event_change.value
                    # Direction is meaningless for the symmetric ``during`` kind.
                    direction_select.set_visibility(event_change.value != "during")

                def on_direction_change(event_change) -> None:
                    add_state["direction"] = event_change.value

                def on_other_change(event_change) -> None:
                    add_state["other_id"] = event_change.value

                kind_select.on_value_change(on_kind_change)
                direction_select.on_value_change(on_direction_change)
                other_select.on_value_change(on_other_change)

                def add_relation() -> None:
                    kind = add_state["kind"]
                    other_id = add_state["other_id"]
                    if not other_id:
                        return
                    if kind == "during" or add_state["direction"] == "this_follows":
                        # Source is the follower (later) event; for ``during`` the
                        # pair is unordered so endpoint order does not matter.
                        source_id, target_id = event.id, other_id
                    else:
                        source_id, target_id = other_id, event.id
                    try:
                        normalize_relation(bible, kind, source_id, target_id)
                    except RelationValidationError as exc:
                        ui.notify(str(exc), type="negative")
                        return
                    relation = EventRelation(
                        kind=kind,
                        source_id=source_id,
                        target_id=target_id,
                    )
                    bible.event_relations.append(relation)
                    save_world_ui()
                    relations_section.refresh()
                    notify_structure()

                ui.button("Add relationship", icon="add", on_click=add_relation).props("flat")


def _mermaid_escape_label(text: str) -> str:
    cleaned = text.replace('"', "'").replace("\n", " ").strip()
    return cleaned or "Untitled"


_CONFLICT_EDGE_COLOR = "#e53935"


def _during_groups(bible: StoryBible) -> list[list[str]]:
    """Cluster timeline events linked (transitively) by ``during`` relations.

    Returns groups of 2+ event ids, ordered by timeline position, so the graph
    builder can place concurrent events in a shared vertical band.
    """

    order = [event.id for event in chronological_order(bible)]
    parent = {event_id: event_id for event_id in order}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    known = set(order)
    for relation in bible.event_relations:
        if (
            relation.kind == "during"
            and relation.source_id in known
            and relation.target_id in known
        ):
            parent[find(relation.source_id)] = find(relation.target_id)

    groups: dict[str, list[str]] = {}
    for event_id in order:
        groups.setdefault(find(event_id), []).append(event_id)
    return [members for members in groups.values() if len(members) >= 2]


def _build_timeline_mermaid(bible: StoryBible, selected_id: str | None = None) -> str:
    ordered = chronological_order(bible)
    conflict_ids = {
        diagnostic.relation_id
        for diagnostic in relation_diagnostics(bible)
        if diagnostic.kind == "cycle"
    }
    labels = {
        event.id: _mermaid_escape_label(event.title or f"Event {index + 1}")
        for index, event in enumerate(ordered)
    }

    groups = _during_groups(bible)
    grouped_ids = {event_id for group in groups for event_id in group}

    lines = ["flowchart LR"]
    for event in ordered:
        if event.id not in grouped_ids:
            lines.append(f'  {event.id}["{labels[event.id]}"]')

    # Concurrent (``during``) events are wrapped in an outlined subgraph instead
    # of being joined by an edge. With no edge forcing a rank gap, dagre lets the
    # group's members settle on the same rank (a shared vertical band in this
    # left-to-right graph) while the box keeps them visually connected.
    subgraph_ids: list[str] = []
    for group_index, members in enumerate(groups):
        subgraph_id = f"during_group_{group_index}"
        subgraph_ids.append(subgraph_id)
        lines.append(f'  subgraph {subgraph_id}["during"]')
        for event_id in members:
            lines.append(f'    {event_id}["{labels[event_id]}"]')
        lines.append("  end")

    # Directed edges are drawn earlier -> later so the graph flows left-to-right
    # in chronological order (``source`` is the later follower, ``target`` the
    # earlier event it follows). ``during`` carries no edge -- it is shown by the
    # group box above.
    conflict_link_indices: list[int] = []
    link_index = 0
    for relation in bible.event_relations:
        if relation.kind == "follows":
            lines.append(f"  {relation.target_id} --> {relation.source_id}")
        elif relation.kind == "directly_follows":
            lines.append(f"  {relation.target_id} ==> {relation.source_id}")
        elif relation.kind == "depends_on":
            lines.append(f"  {relation.target_id} -.-> {relation.source_id}")
        else:
            continue
        if relation.id in conflict_ids:
            conflict_link_indices.append(link_index)
        link_index += 1

    for subgraph_id in subgraph_ids:
        lines.append(f"  style {subgraph_id} fill:none,stroke:#9c6ade,stroke-dasharray:4 4")

    for idx in conflict_link_indices:
        lines.append(f"  linkStyle {idx} stroke:{_CONFLICT_EDGE_COLOR},stroke-width:2px;")

    known_ids = {event.id for event in ordered}
    if selected_id is not None and selected_id in known_ids:
        lines.append(f"  style {selected_id} {_SELECTED_NODE_STYLE}")

    return "\n".join(lines)


def _render_timeline_legend() -> None:
    """Minimal legend mapping graph styles to relation kinds."""

    items = (
        ("follows", "display:inline-block;width:28px;border-top:2px solid #555;"),
        ("directly follows", "display:inline-block;width:28px;border-top:4px solid #555;"),
        ("depends on", "display:inline-block;width:28px;border-top:2px dotted #555;"),
        (
            "during",
            "display:inline-block;width:24px;height:14px;"
            "border:1px dashed #9c6ade;border-radius:2px;",
        ),
        (
            "conflict",
            f"display:inline-block;width:28px;border-top:2px solid {_CONFLICT_EDGE_COLOR};",
        ),
    )
    with ui.row().classes("gap-4 items-center q-mt-sm"):
        for label, sample_style in items:
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.html(f'<span style="{sample_style}"></span>')
                ui.label(label).classes("text-grey-7 text-sm")


def _render_event_relation_row(
    event: Event,
    relation: EventRelation,
    refresh: Callable[[], None],
) -> None:
    bible = get_world().story_bible
    if relation.kind == "during":
        other_id = relation.target_id if relation.source_id == event.id else relation.source_id
        other = bible.get_event(other_id)
        other_title = other.title if other else other_id
        label = f"during with {other_title or 'Untitled'}"
    elif relation.source_id == event.id:
        other = bible.get_event(relation.target_id)
        other_title = other.title if other else relation.target_id
        label = f"{relation.kind} → {other_title or 'Untitled'}"
    else:
        other = bible.get_event(relation.source_id)
        other_title = other.title if other else relation.source_id
        label = f"{relation.kind} ← {other_title or 'Untitled'}"

    warnings = diagnostics_for_relation(bible, relation.id)

    with ui.row().classes("w-full items-center no-wrap gap-2"):
        ui.label(label).classes("grow")
        if warnings:
            ui.badge("warning").props("color=warning")

        def delete_relation(relation_id: str = relation.id) -> None:
            bible.event_relations = [
                item for item in bible.event_relations if item.id != relation_id
            ]
            save_world_ui()
            refresh()

        _delete_button(delete_relation, "Remove relationship")


def _render_world_state_effect_row(
    event: Event,
    effect,
    entry_options: dict[str, str],
    refresh: Callable[[], None],
) -> None:
    with ui.row().classes("w-full items-center no-wrap gap-2"):
        if isinstance(effect, AddWorldStateEntry):
            ui.badge("Add").props("color=positive outline")
            _bound_select(effect.entry, "kind", _WORLD_STATE_KIND_OPTIONS)
            text = ui.input(placeholder="New world state entry...").classes("grow")
            text.props("dense outlined")
            text.bind_value(effect.entry, "text")
            _save_on_change(text)
        elif isinstance(effect, UpdateWorldStateEntry):
            ui.badge("Update").props("color=warning outline")
            _bound_select(effect, "entry_id", _with_current(entry_options, effect.entry_id))
            text = ui.input(placeholder="New text...").classes("grow").props("dense outlined")
            text.bind_value(effect, "text")
            _save_on_change(text)
        else:
            ui.badge("Remove").props("color=negative outline")
            select = _bound_select(
                effect, "entry_id", _with_current(entry_options, effect.entry_id)
            )
            select.classes("grow")

        def delete_effect(effect=effect) -> None:
            event.world_state_effects = [
                item for item in event.world_state_effects if item is not effect
            ]
            save_world_ui()
            refresh()

        _delete_button(delete_effect, "Remove effect")


def _render_signal_card(
    event: Event,
    signal: Signal,
    chron_index: int,
    refresh_signals: Callable[[], None],
) -> None:
    bible = get_world().story_bible
    character_options = {
        character.id: character.identity.name or "Unnamed character"
        for character in bible.characters
    }

    with ui.card().classes("w-full bg-grey-1"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            character_select = ui.select(
                _with_current(character_options, signal.character_id),
                label="Character",
            ).classes("grow")
            character_select.props("dense outlined")
            character_select.bind_value(signal, "character_id")

            def on_character_change(_event) -> None:
                save_world_ui()
                refresh_signals()

            character_select.on_value_change(on_character_change)

            def delete_signal(signal: Signal = signal) -> None:
                event.signals = [item for item in event.signals if item.id != signal.id]
                save_world_ui()
                refresh_signals()

            _delete_button(delete_signal, "Remove signal")

        _field_label("Interpretation")
        _bound_textarea(
            signal, "interpretation", placeholder="How the character reads this event..."
        )

        intimacy_options = _intimacy_options_for_signal(bible, chron_index, signal)

        _field_label("Evidence")

        @ui.refreshable
        def evidence_section() -> None:
            if not signal.evidence:
                ui.label("No evidence entries.").classes("text-grey-7")
            for entry in signal.evidence:
                _render_evidence_row(signal, entry, intimacy_options, evidence_section.refresh)

        evidence_section()

        def add_evidence() -> None:
            default_id = next(iter(intimacy_options), "")
            signal.evidence.append(IntimacyEvidence(intimacy_id=default_id))
            save_world_ui()
            evidence_section.refresh()

        ui.button("Add evidence", icon="add", on_click=add_evidence).props("flat")

        _field_label("State Effects")

        @ui.refreshable
        def effects_section() -> None:
            if not signal.effects:
                ui.label("No state effects.").classes("text-grey-7")
            for effect in signal.effects:
                _render_character_effect_row(
                    signal, effect, intimacy_options, effects_section.refresh
                )

        effects_section()

        def add_effect(effect) -> None:
            if isinstance(effect, AddIntimacy):
                effect.intimacy.strength = "minor"
                effect.intimacy.id = unique_slug(
                    "intim_",
                    effect.intimacy.text,
                    set(bible.intimacy_ids()),
                )
            signal.effects.append(effect)
            save_world_ui()
            effects_section.refresh()

        with ui.button("Add state effect", icon="add").props("flat"):
            with ui.menu():
                ui.menu_item("Add intimacy", on_click=lambda: add_effect(AddIntimacy()))
                ui.menu_item("Update intimacy", on_click=lambda: add_effect(UpdateIntimacy()))
                ui.menu_item("Remove intimacy", on_click=lambda: add_effect(RemoveIntimacy()))


def _render_character_effect_row(
    signal: Signal,
    effect,
    intimacy_options: dict[str, str],
    refresh: Callable[[], None],
) -> None:
    with ui.row().classes("w-full items-center no-wrap gap-2"):
        if isinstance(effect, AddIntimacy):
            ui.badge("Add intimacy").props("outline color=positive")
            text = ui.input(placeholder="e.g. Wary of outsiders").classes("grow")
            text.props("dense outlined")
            text.bind_value(effect.intimacy, "text")
            _save_on_change(text)
            ui.badge("minor").props("outline")
        elif isinstance(effect, SetIntimacyStrength):
            ui.badge("Set strength").props("outline color=warning")
            select = _bound_select(
                effect, "intimacy_id", _with_current(intimacy_options, effect.intimacy_id)
            )
            select.classes("grow")
            _bound_select(effect, "strength", _STRENGTH_OPTIONS)
        elif isinstance(effect, UpdateIntimacy):
            ui.badge("Update intimacy").props("outline color=warning")
            _bound_select(
                effect, "intimacy_id", _with_current(intimacy_options, effect.intimacy_id)
            )
            text = ui.input(placeholder="New text...").classes("grow").props("dense outlined")
            text.bind_value(effect, "text")
            _save_on_change(text)
        else:
            ui.badge("Remove intimacy").props("outline color=negative")
            select = _bound_select(
                effect, "intimacy_id", _with_current(intimacy_options, effect.intimacy_id)
            )
            select.classes("grow")

        def delete_effect(effect=effect) -> None:
            signal.effects = [item for item in signal.effects if item is not effect]
            save_world_ui()
            refresh()

        _delete_button(delete_effect, "Remove effect")


def _render_evidence_row(
    signal: Signal,
    entry: IntimacyEvidence,
    intimacy_options: dict[str, str],
    refresh: Callable[[], None],
) -> None:
    with ui.row().classes("w-full items-center no-wrap gap-2"):
        _bound_select(entry, "direction", _EVIDENCE_DIRECTION_OPTIONS)
        select = _bound_select(
            entry, "intimacy_id", _with_current(intimacy_options, entry.intimacy_id)
        )
        select.classes("grow")
        _bound_int_select(entry, "strength", _EVIDENCE_STRENGTH_OPTIONS)
        rationale = ui.input(placeholder="Why this signal bears on the intimacy...").classes("grow")
        rationale.props("dense outlined")
        rationale.bind_value(entry, "rationale")
        _save_on_change(rationale)

        def delete_entry(entry: IntimacyEvidence = entry) -> None:
            signal.evidence = [item for item in signal.evidence if item is not entry]
            save_world_ui()
            refresh()

        _delete_button(delete_entry, "Remove evidence")


async def _confirm_delete_event(
    event: Event,
    *,
    on_deleted: Callable[[], None] | None = None,
) -> None:
    title = event.title or "this event"
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Delete '{title}' and its signals? This cannot be undone.")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Delete", color="negative", on_click=lambda: dialog.submit(True))

    if not await dialog:
        return

    world = get_world()
    prune_event_links(world, event.id)
    bible = world.story_bible
    bible.timeline = [item for item in bible.timeline if item.id != event.id]
    bible.event_relations = [
        item
        for item in bible.event_relations
        if item.source_id != event.id and item.target_id != event.id
    ]
    save_world_ui()
    if on_deleted is not None:
        on_deleted()
    else:
        ui.navigate.to("/workspace/timeline")


def _entry_options_before(bible: StoryBible, chron_index: int) -> dict[str, str]:
    derived = derive_state_at(bible, chron_index)
    return {entry.id: f"{entry.text or entry.id} ({entry.kind})" for entry in derived.world_state}


def _intimacy_options_before(
    bible: StoryBible,
    chron_index: int,
    character_id: str,
) -> dict[str, str]:
    derived = derive_state_at(bible, chron_index).characters.get(character_id)
    if derived is None:
        return {}
    return {intimacy.id: intimacy.text or intimacy.id for intimacy in derived.intimacies}


def _intimacy_options_for_signal(
    bible: StoryBible,
    chron_index: int,
    signal: Signal,
) -> dict[str, str]:
    options = _intimacy_options_before(bible, chron_index, signal.character_id)
    for effect in signal.effects:
        if isinstance(effect, AddIntimacy) and effect.intimacy.id:
            options[effect.intimacy.id] = effect.intimacy.text or effect.intimacy.id
    return options


def _with_current(options: dict[str, str], current: str) -> dict[str, str]:
    """Include a dangling current value so the select can still display it."""

    if current and current not in options:
        return {**options, current: f"{current} (missing)"}
    return dict(options)


# --- scene blueprint ---------------------------------------------------------


def _render_linked_events(label: str, event_ids: list[str], bible: StoryBible) -> None:
    """Render a read-only list of linked events by title, tolerating stale ids."""

    _field_label(label)
    if not event_ids:
        ui.label("(none)").classes("text-grey-7 text-sm")
        return
    for event_id in event_ids:
        event = bible.get_event(event_id)
        if event is None:
            ui.label(f"Unknown event [{event_id}]").classes("text-grey-7 text-sm")
        else:
            ui.label(f"{event.title or 'Untitled'} [{event_id}]").classes("text-sm")


def _event_select_options(bible: StoryBible) -> dict[str, str]:
    return {event.id: f"{event.title or 'Untitled'} [{event.id}]" for event in bible.timeline}


def _enacted_event_select_options(bible: StoryBible, scene: Scene) -> dict[str, str]:
    """Return timeline events available to enact in ``scene`` (exclude elsewhere-enacted)."""

    world = get_world()
    current_enacted = set(scene.blueprint.event_ids)
    options: dict[str, str] = {}
    for event in bible.timeline:
        if event.id in current_enacted:
            options[event.id] = f"{event.title or 'Untitled'} [{event.id}]"
            continue
        if enacting_scenes(world, event.id):
            continue
        options[event.id] = f"{event.title or 'Untitled'} [{event.id}]"
    return options


def _character_select_options(bible: StoryBible) -> dict[str, str]:
    return {
        character.id: character.identity.name or "Unnamed character"
        for character in bible.characters
    }


def _render_string_list_editor(
    items: list[str],
    *,
    placeholder: str,
    refresh: Callable[[], None],
) -> None:
    if not items:
        ui.label("(none)").classes("text-grey-7")
    for index, value in enumerate(items):

        def delete_item(index: int = index) -> None:
            items.pop(index)
            save_world_ui()
            refresh()

        with ui.row().classes("w-full items-center no-wrap gap-2"):
            text = ui.input(placeholder=placeholder, value=value).classes("grow")
            text.props("dense outlined")

            def apply_item(event, index: int = index) -> None:
                items[index] = event.value or ""
                save_world_ui()

            text.on_value_change(apply_item)
            _delete_button(delete_item, "Remove")


def render_scene_blueprint_form(
    scene: Scene,
    edit_state: dict,
    *,
    expand_blueprint: bool = False,
) -> None:
    """Render the scene blueprint and generated-content editors, visible in edit mode."""

    blueprint = scene.blueprint
    generated = scene.generated
    bible = get_world().story_bible

    with ui.column().classes("w-full gap-4 shrink-0") as blueprint_block:
        blueprint_block.bind_visibility_from(edit_state, "edit_mode")

        with ui.expansion("Blueprint", icon="description", value=expand_blueprint).classes(
            "w-full"
        ):
            ui.label(
                "Editable scene card inputs: premise, purpose, POV, scene frame, characters, "
                "events, constraints, and notes."
            ).classes("text-grey-7 text-sm")
            _field_label("POV")
            _bound_input(blueprint, "pov", placeholder="Point-of-view character or narrator...")
            _field_label("Premise")
            _bound_textarea(
                blueprint,
                "premise",
                placeholder="What happens in this scene?",
                rows=3,
            )
            _field_label("Purpose")
            _bound_textarea(
                blueprint,
                "purpose",
                placeholder="Why this scene exists in the story...",
                rows=3,
            )
            _field_label("Starting state")
            ui.label("How the scene opens given what came before.").classes("text-grey-7 text-sm")
            _bound_textarea(
                blueprint,
                "starting_state",
                placeholder="The initial state when the scene begins...",
                rows=2,
            )
            _field_label("Central conflict")
            ui.label("The conflict this scene exists to dramatize.").classes("text-grey-7 text-sm")
            _bound_textarea(
                blueprint,
                "central_conflict",
                placeholder="The primary conflict driving the scene...",
                rows=2,
            )
            _field_label("Required resolution")
            ui.label("The outcome later scenes depend on.").classes("text-grey-7 text-sm")
            _bound_textarea(
                blueprint,
                "required_resolution",
                placeholder="How the scene must resolve for the story to make sense...",
                rows=2,
            )

            _field_label("Participating characters")
            character_select = ui.select(
                _character_select_options(bible),
                value=list(blueprint.character_ids),
                multiple=True,
            ).classes("w-full")
            character_select.props("dense outlined use-chips")

            def on_characters_change(event) -> None:
                blueprint.character_ids = list(event.value or [])
                save_world_ui()

            character_select.on_value_change(on_characters_change)

            _field_label("Enacted events")
            enacted_select = ui.select(
                _enacted_event_select_options(bible, scene),
                value=list(blueprint.event_ids),
                multiple=True,
            ).classes("w-full")
            enacted_select.props("dense outlined use-chips")

            def on_enacted_change(event) -> None:
                blueprint.event_ids = list(event.value or [])
                enacted = set(blueprint.event_ids)
                blueprint.related_event_ids = [
                    event_id for event_id in blueprint.related_event_ids if event_id not in enacted
                ]
                save_world_ui()

            enacted_select.on_value_change(on_enacted_change)

            _field_label("Related events (context only)")
            related_select = ui.select(
                _event_select_options(bible),
                value=list(blueprint.related_event_ids),
                multiple=True,
            ).classes("w-full")
            related_select.props("dense outlined use-chips")

            def on_related_change(event) -> None:
                enacted = set(blueprint.event_ids)
                blueprint.related_event_ids = [
                    event_id for event_id in (event.value or []) if event_id not in enacted
                ]
                save_world_ui()

            related_select.on_value_change(on_related_change)

            _field_label("Constraints")
            _bound_textarea(
                blueprint,
                "constraints",
                placeholder="Hard limits for this scene...",
                rows=2,
            )
            _field_label("Notes")
            _bound_textarea(
                blueprint,
                "notes",
                placeholder="Free-form planning notes...",
                rows=2,
            )

        with ui.expansion("Generated", icon="auto_awesome", value=False).classes("w-full"):
            ui.label(
                "Workflow output: outline and stances. Regenerating overwrites these fields."
            ).classes("text-grey-7 text-sm")

            ui.label("Outline").classes("text-sm font-medium")
            ui.label("Concise beats that structure the scene.").classes("text-grey-7 text-sm")

            @ui.refreshable
            def outline_section() -> None:
                _render_string_list_editor(
                    generated.outline,
                    placeholder="Outline beat...",
                    refresh=outline_section.refresh,
                )

            outline_section()

            def add_beat() -> None:
                generated.outline.append("")
                save_world_ui()
                outline_section.refresh()

            ui.button("Add beat", icon="add", on_click=add_beat).props("flat")

            ui.label("Character Stances").classes("text-sm font-medium mt-2")
            ui.label("Ephemeral posture for characters in this scene.").classes(
                "text-grey-7 text-sm"
            )

            @ui.refreshable
            def stances_section() -> None:
                if not generated.stances:
                    ui.label("No character stances yet.").classes("text-grey-7")
                for stance in generated.stances:
                    _render_scene_stance_card(
                        stance,
                        generated.stances,
                        bible,
                        stances_section.refresh,
                    )

            stances_section()

            def add_stance() -> None:
                characters = bible.characters
                character_id = characters[0].id if characters else ""
                generated.stances.append(SceneCharacterStance(character_id=character_id))
                save_world_ui()
                stances_section.refresh()

            ui.button("Add stance", icon="add", on_click=add_stance).props("flat")


def _render_scene_stance_card(
    stance: SceneCharacterStance,
    stances: list[SceneCharacterStance],
    bible: StoryBible,
    refresh: Callable[[], None],
) -> None:
    character_options = {
        character.id: character.identity.name or "Unnamed character"
        for character in bible.characters
    }

    with ui.card().classes("w-full bg-grey-1"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            character_select = ui.select(
                _with_current(character_options, stance.character_id),
                label="Character",
            ).classes("grow")
            character_select.props("dense outlined")
            character_select.bind_value(stance, "character_id")
            _save_on_change(character_select)

            def delete_stance(stance: SceneCharacterStance = stance) -> None:
                stances[:] = [item for item in stances if item is not stance]
                save_world_ui()
                refresh()

            _delete_button(delete_stance, "Remove stance")

        _field_label("Mood")

        @ui.refreshable
        def mood_section() -> None:
            if not stance.mood:
                ui.label("No mood statements yet.").classes("text-grey-7")
            for index, _statement in enumerate(stance.mood):

                def delete_statement(index: int = index) -> None:
                    stance.mood.pop(index)
                    save_world_ui()
                    mood_section.refresh()

                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    text = ui.input(
                        placeholder="Mood statement...",
                        value=stance.mood[index],
                    ).classes("grow")
                    text.props("dense outlined")

                    def apply_statement(event, index: int = index) -> None:
                        stance.mood[index] = event.value or ""
                        save_world_ui()

                    text.on_value_change(apply_statement)
                    _delete_button(delete_statement, "Remove statement")

        mood_section()

        def add_statement() -> None:
            stance.mood.append("")
            save_world_ui()
            mood_section.refresh()

        ui.button("Add mood statement", icon="add", on_click=add_statement).props("flat")

        _field_label("Intent")
        _bound_input(stance, "intent", placeholder="What they want in this scene...")
        _field_label("Tactics")
        _bound_input(stance, "tactics", placeholder="How they pursue it...")
        _field_label("Stakes")
        _bound_input(stance, "stakes", placeholder="What is at risk for them...")
