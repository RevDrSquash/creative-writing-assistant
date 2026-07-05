"""Structured Story Bible editing forms for the workspace center panel.

Forms bind directly to the in-memory World object and write through to disk
on change. Derived state panels are read-only views computed by the replay
engine for a selectable timeline position.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from app.world.models import (
    AddIntimacy,
    AddWorldStateEntry,
    Character,
    Event,
    EventRelation,
    Intimacy,
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
from app.world.store import get_world, save_world

_STRENGTH_OPTIONS = {"minor": "Minor", "major": "Major", "defining": "Defining"}
_WORLD_STATE_KIND_OPTIONS = {
    "pressure": "Pressure",
    "thread": "Thread",
    "consequence": "Consequence",
}
_RELATION_KIND_OPTIONS = {
    "follows": "Follows (loose order)",
    "directly_follows": "Directly follows (tight continuity)",
    "during": "During (concurrent)",
}
# For directed kinds the user picks which event is the follower (the later one)
# instead of inferring it from timeline list position.
_RELATION_DIRECTION_OPTIONS = {
    "this_follows": "This event follows the other",
    "other_follows": "The other event follows this one",
}


# --- shared helpers ---------------------------------------------------------


def _save_on_change(element: ui.element) -> None:
    element.on_value_change(lambda _: save_world())


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
        save_world()

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
        save_world()
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
        save_world()
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
                save_world()
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
            save_world()
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
        save_world()
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
            save_world()
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
        _bound_select(intimacy, "strength", _STRENGTH_OPTIONS)

        def delete_intimacy(intimacy: Intimacy = intimacy) -> None:
            intimacies[:] = [item for item in intimacies if item.id != intimacy.id]
            save_world()
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
    save_world()
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
    ui.label("Timeline").classes("text-xl font-semibold")
    ui.label(
        "Ordered story events. Relationships drive chronology; list order breaks ties "
        "among unconnected events."
    ).classes("text-grey-7")

    if bible.timeline:
        mermaid_source = _build_timeline_mermaid(bible)
        with ui.card().classes("w-full"):
            ui.label("Event graph").classes("text-lg font-semibold")
            ui.mermaid(mermaid_source)
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

    def insert_event(index: int) -> None:
        event = Event()
        event.id = unique_slug("event_", "", {item.id for item in bible.timeline})
        bible.timeline.insert(index, event)
        save_world()
        ui.navigate.to(f"/workspace/events/{event.id}")

    @ui.refreshable
    def rows() -> None:
        ordered = chronological_order(bible)
        if not ordered:
            ui.label("No events yet.").classes("text-grey-7")
        for chron_index, event in enumerate(ordered):
            list_index = bible.event_index(event.id) or 0
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    ui.label(f"{chron_index + 1}.").classes("text-grey-7 font-mono")
                    ui.label(event.title or "Untitled event").classes("grow font-semibold")
                    insert_button = ui.button(
                        icon="north",
                        on_click=lambda index=list_index: insert_event(index),
                    )
                    insert_button.props("flat round dense size=sm color=grey-7")
                    insert_button.tooltip("Insert event before this one")
                    ui.button(
                        "Open",
                        on_click=lambda event=event: ui.navigate.to(
                            f"/workspace/events/{event.id}"
                        ),
                    ).props("flat")

    rows()
    ui.button(
        "Add event",
        icon="add",
        on_click=lambda: insert_event(len(bible.timeline)),
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

    with ui.card().classes("w-full"):
        _field_label("Title")
        _bound_input(event, "title", placeholder="What happens, objectively...")
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
            save_world()
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
            save_world()
            signals_section.refresh()

        ui.button("Add signal", icon="add", on_click=add_signal).props("flat")

    with ui.card().classes("w-full"):
        ui.label("Relationships").classes("text-lg font-semibold")
        ui.label(
            "Typed links to other events. For 'follows' kinds, choose which event is the "
            "follower (the later one); 'during' marks concurrent events."
        ).classes("text-grey-7 text-sm")

        @ui.refreshable
        def relations_section() -> None:
            relations = bible.relations_for_event(event.id)
            all_relations = relations.incoming + relations.outgoing + relations.concurrent
            if not all_relations:
                ui.label("No relationships.").classes("text-grey-7")
            for relation in all_relations:
                _render_event_relation_row(event, relation, relations_section.refresh)

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
                    save_world()
                    relations_section.refresh()

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


def _build_timeline_mermaid(bible: StoryBible) -> str:
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
        else:
            continue
        if relation.id in conflict_ids:
            conflict_link_indices.append(link_index)
        link_index += 1

    for subgraph_id in subgraph_ids:
        lines.append(f"  style {subgraph_id} fill:none,stroke:#9c6ade,stroke-dasharray:4 4")

    for idx in conflict_link_indices:
        lines.append(f"  linkStyle {idx} stroke:{_CONFLICT_EDGE_COLOR},stroke-width:2px;")

    return "\n".join(lines)


def _render_timeline_legend() -> None:
    """Minimal legend mapping graph styles to relation kinds."""

    items = (
        ("follows", "display:inline-block;width:28px;border-top:2px solid #555;"),
        ("directly follows", "display:inline-block;width:28px;border-top:4px solid #555;"),
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
            save_world()
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
            save_world()
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
                save_world()
                refresh_signals()

            character_select.on_value_change(on_character_change)

            def delete_signal(signal: Signal = signal) -> None:
                event.signals = [item for item in event.signals if item.id != signal.id]
                save_world()
                refresh_signals()

            _delete_button(delete_signal, "Remove signal")

        _field_label("Interpretation")
        _bound_textarea(
            signal, "interpretation", placeholder="How the character reads this event..."
        )

        intimacy_options = _intimacy_options_before(bible, chron_index, signal.character_id)

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
            signal.effects.append(effect)
            save_world()
            effects_section.refresh()

        with ui.button("Add state effect", icon="add").props("flat"):
            with ui.menu():
                ui.menu_item("Add intimacy", on_click=lambda: add_effect(AddIntimacy()))
                ui.menu_item(
                    "Set intimacy strength",
                    on_click=lambda: add_effect(SetIntimacyStrength()),
                )
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
            _bound_select(effect.intimacy, "strength", _STRENGTH_OPTIONS)
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
            save_world()
            refresh()

        _delete_button(delete_effect, "Remove effect")


async def _confirm_delete_event(event: Event) -> None:
    title = event.title or "this event"
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Delete '{title}' and its signals? This cannot be undone.")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Delete", color="negative", on_click=lambda: dialog.submit(True))

    if not await dialog:
        return

    bible = get_world().story_bible
    bible.timeline = [item for item in bible.timeline if item.id != event.id]
    bible.event_relations = [
        item
        for item in bible.event_relations
        if item.source_id != event.id and item.target_id != event.id
    ]
    save_world()
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
            save_world()
            refresh()

        with ui.row().classes("w-full items-center no-wrap gap-2"):
            text = ui.input(placeholder=placeholder, value=value).classes("grow")
            text.props("dense outlined")

            def apply_item(event, index: int = index) -> None:
                items[index] = event.value or ""
                save_world()

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
                "Editable scene card inputs: premise, purpose, POV, arc, characters, events, "
                "constraints, and notes."
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
            _field_label("Arc beats")
            ui.label("Three-point (or more) arc guidance for generation.").classes(
                "text-grey-7 text-sm"
            )

            @ui.refreshable
            def arc_section() -> None:
                _render_string_list_editor(
                    blueprint.arc,
                    placeholder="Arc beat...",
                    refresh=arc_section.refresh,
                )

            arc_section()

            def add_arc_beat() -> None:
                blueprint.arc.append("")
                save_world()
                arc_section.refresh()

            ui.button("Add arc beat", icon="add", on_click=add_arc_beat).props("flat")

            _field_label("Participating characters")
            character_select = ui.select(
                _character_select_options(bible),
                value=list(blueprint.character_ids),
                multiple=True,
            ).classes("w-full")
            character_select.props("dense outlined use-chips")

            def on_characters_change(event) -> None:
                blueprint.character_ids = list(event.value or [])
                save_world()

            character_select.on_value_change(on_characters_change)

            _field_label("Enacted events")
            enacted_select = ui.select(
                _event_select_options(bible),
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
                save_world()

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
                save_world()

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
                save_world()
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
                save_world()
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
                save_world()
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
                    save_world()
                    mood_section.refresh()

                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    text = ui.input(
                        placeholder="Mood statement...",
                        value=stance.mood[index],
                    ).classes("grow")
                    text.props("dense outlined")

                    def apply_statement(event, index: int = index) -> None:
                        stance.mood[index] = event.value or ""
                        save_world()

                    text.on_value_change(apply_statement)
                    _delete_button(delete_statement, "Remove statement")

        mood_section()

        def add_statement() -> None:
            stance.mood.append("")
            save_world()
            mood_section.refresh()

        ui.button("Add mood statement", icon="add", on_click=add_statement).props("flat")

        _field_label("Intent")
        _bound_input(stance, "intent", placeholder="What they want in this scene...")
        _field_label("Tactics")
        _bound_input(stance, "tactics", placeholder="How they pursue it...")
        _field_label("Stakes")
        _bound_input(stance, "stakes", placeholder="What is at risk for them...")
