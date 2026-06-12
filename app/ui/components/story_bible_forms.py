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
    Intimacy,
    RemoveIntimacy,
    RemoveWorldStateEntry,
    SetGoal,
    SetIntimacyStrength,
    SetStatus,
    Signal,
    StoryBible,
    UpdateIntimacy,
    UpdateWorldStateEntry,
    WorldFact,
    WorldStateEntry,
)
from app.world.replay import derive_state_at
from app.world.store import get_world, save_world

_STRENGTH_OPTIONS = {"minor": "Minor", "major": "Major", "defining": "Defining"}
_WORLD_STATE_KIND_OPTIONS = {
    "pressure": "Pressure",
    "thread": "Thread",
    "consequence": "Consequence",
}
_EVENT_KIND_OPTIONS = {"scene": "Scene", "time_passage": "Time passage"}


# --- shared helpers ---------------------------------------------------------


def _save_on_change(element: ui.element) -> None:
    element.on_value_change(lambda _: save_world())


def _bound_input(target: object, field: str, *, placeholder: str = "") -> ui.input:
    element = ui.input(placeholder=placeholder).classes("w-full").props("dense outlined")
    element.bind_value(target, field)
    _save_on_change(element)
    return element


def _bound_textarea(target: object, field: str, *, placeholder: str = "") -> ui.textarea:
    element = (
        ui.textarea(placeholder=placeholder).classes("w-full").props("dense outlined autogrow")
    )
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
    for index, event in enumerate(bible.timeline):
        options[index + 1] = f"After {index + 1}. {event.title or 'Untitled event'}"
    return options


# --- narrative style --------------------------------------------------------


def render_narrative_style_form() -> None:
    bible = get_world().story_bible
    ui.label("Narrative Style").classes("text-xl font-semibold")
    ui.label("The intended tone, themes, and writing style for this project.").classes(
        "text-grey-7"
    )
    _bound_textarea(bible, "narrative_style", placeholder="Describe tone, themes, style...")


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
        bible.world_facts.append(WorldFact())
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
        bible.baseline_world_state.append(WorldStateEntry())
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

    position = {"value": len(bible.timeline)}
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
                        if character.baseline_state.goal:
                            ui.label(character.baseline_state.goal).classes("text-grey-7 text-sm")
                    ui.button(
                        "Open",
                        on_click=lambda character=character: ui.navigate.to(
                            f"/workspace/characters/{character.id}"
                        ),
                    ).props("flat")

    rows()

    def add_character() -> None:
        character = Character()
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
        _field_label("Goal")
        _bound_input(character.baseline_state, "goal", placeholder="Current goal...")
        _field_label("Status")
        _bound_input(character.baseline_state, "status", placeholder="Current status...")
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
            character.baseline_state.intimacies.append(Intimacy())
            save_world()
            intimacies_section.refresh()

        ui.button("Add intimacy", icon="add", on_click=add_intimacy).props("flat")

    with ui.card().classes("w-full"):
        ui.label("Stance").classes("text-lg font-semibold")
        ui.label("Temporary scene-level posture; not affected by the timeline.").classes(
            "text-grey-7 text-sm"
        )
        _field_label("Mood")
        _bound_input(character.stance, "mood", placeholder="Emotional state...")
        _field_label("Intent")
        _bound_input(character.stance, "intent", placeholder="What they want in this scene...")
        _field_label("Tactics")
        _bound_input(character.stance, "tactics", placeholder="How they pursue it...")
        _field_label("Stakes")
        _bound_input(character.stance, "stakes", placeholder="What is at risk for them...")

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

        position = {"value": len(bible.timeline)}
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
            ui.label(f"Goal: {derived.goal or '-'}")
            ui.label(f"Status: {derived.status or '-'}")
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
    ui.label("Ordered story events. Events update world state and signal characters.").classes(
        "text-grey-7"
    )

    def insert_event(index: int) -> None:
        event = Event()
        bible.timeline.insert(index, event)
        save_world()
        ui.navigate.to(f"/workspace/events/{event.id}")

    @ui.refreshable
    def rows() -> None:
        if not bible.timeline:
            ui.label("No events yet.").classes("text-grey-7")
        for index, event in enumerate(bible.timeline):
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    ui.label(f"{index + 1}.").classes("text-grey-7 font-mono")
                    ui.badge(_EVENT_KIND_OPTIONS[event.kind]).props("outline color=primary")
                    ui.label(event.title or "Untitled event").classes("grow font-semibold")
                    insert_button = ui.button(
                        icon="north",
                        on_click=lambda index=index: insert_event(index),
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
    event_index = bible.event_index(event.id) or 0

    with ui.row().classes("w-full items-center no-wrap gap-2"):
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/workspace/timeline")).props(
            "flat round dense"
        )
        ui.label(f"Event {event_index + 1} of {len(bible.timeline)}").classes("text-grey-7")
        ui.space()
        _delete_button(lambda: _confirm_delete_event(event), "Delete event")

    with ui.card().classes("w-full"):
        _field_label("Title")
        _bound_input(event, "title", placeholder="What happens, objectively...")
        _field_label("Kind")
        _bound_select(event, "kind", _EVENT_KIND_OPTIONS)
        _field_label("Description")
        _bound_textarea(event, "description", placeholder="The objective story beat...")

    entry_options = _entry_options_before(bible, event_index)

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
                _render_signal_card(event, signal, event_index, signals_section.refresh)

        signals_section()

        def add_signal() -> None:
            characters = get_world().story_bible.characters
            signal = Signal(character_id=characters[0].id if characters else "")
            event.signals.append(signal)
            save_world()
            signals_section.refresh()

        ui.button("Add signal", icon="add", on_click=add_signal).props("flat")


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
    event_index: int,
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

        intimacy_options = _intimacy_options_before(bible, event_index, signal.character_id)

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
                ui.menu_item("Set goal", on_click=lambda: add_effect(SetGoal()))
                ui.menu_item("Set status", on_click=lambda: add_effect(SetStatus()))
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
        if isinstance(effect, SetGoal):
            ui.badge("Set goal").props("outline color=primary")
            goal = ui.input(placeholder="New goal...").classes("grow").props("dense outlined")
            goal.bind_value(effect, "goal")
            _save_on_change(goal)
        elif isinstance(effect, SetStatus):
            ui.badge("Set status").props("outline color=primary")
            status = ui.input(placeholder="New status...").classes("grow").props("dense outlined")
            status.bind_value(effect, "status")
            _save_on_change(status)
        elif isinstance(effect, AddIntimacy):
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
    save_world()
    ui.navigate.to("/workspace/timeline")


def _entry_options_before(bible: StoryBible, event_index: int) -> dict[str, str]:
    derived = derive_state_at(bible, event_index)
    return {entry.id: f"{entry.text or entry.id} ({entry.kind})" for entry in derived.world_state}


def _intimacy_options_before(
    bible: StoryBible,
    event_index: int,
    character_id: str,
) -> dict[str, str]:
    derived = derive_state_at(bible, event_index).characters.get(character_id)
    if derived is None:
        return {}
    return {intimacy.id: intimacy.text or intimacy.id for intimacy in derived.intimacies}


def _with_current(options: dict[str, str], current: str) -> dict[str, str]:
    """Include a dangling current value so the select can still display it."""

    if current and current not in options:
        return {**options, current: f"{current} (missing)"}
    return dict(options)
