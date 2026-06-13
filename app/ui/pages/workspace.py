"""Workspace pages: scene editor, Story Bible forms, and chat."""

from __future__ import annotations

from nicegui import app, ui

from app.ui.components.chat import render_chat
from app.ui.components.markdown_editor import (
    _toggle_icon,
    _toggle_tooltip,
    render_markdown_editor,
)
from app.ui.components.story_bible_forms import (
    render_characters_form,
    render_narrative_style_form,
    render_timeline_form,
    render_world_form,
)
from app.ui.layout import render_header
from app.ui.navigation import NavigationItem
from app.ui.scene_selection import get_current_scene, set_current_scene_id
from app.world.models import Scene
from app.world.scene import create_scene, delete_scene
from app.world.store import get_world, save_world

WORKSPACE_SPLIT_KEY = "workspace_split"
WORKSPACE_SPLIT_DEFAULT = 75

WORKSPACE_STORY_BIBLE_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem(
        "Narrative Style",
        "/workspace/narrative-style",
        "Tone, themes, and writing style",
    ),
    NavigationItem("World", "/workspace/world", "World facts and world state"),
    NavigationItem("Characters", "/workspace/characters", "Character identities and states"),
    NavigationItem("Timeline", "/workspace/timeline", "Ordered events and signals"),
)


def _workspace_page(active_path: str, scene_id: str | None = None) -> None:
    active_scene: Scene | None = None
    if active_path == "/workspace" or active_path.startswith("/workspace/scenes/"):
        if scene_id is not None:
            active_scene = get_world().get_scene(scene_id)
            if active_scene is None:
                ui.navigate.to("/workspace")
                return
            set_current_scene_id(active_scene.id)
        else:
            active_scene = get_current_scene()

    render_header("/workspace")
    _render_workspace_sidebar(active_path, active_scene.id if active_scene else None)

    # Make the page content fill the viewport beneath the header without the
    # default 1em padding/gap so the splitter can use the full height and
    # children (chat input, etc.) can pin to the bottom edge.
    ui.query(".nicegui-content").classes("p-0 gap-0 no-wrap").style(
        "height: calc(100vh - 80px); overflow: hidden;"
    )

    app.storage.user.setdefault(WORKSPACE_SPLIT_KEY, WORKSPACE_SPLIT_DEFAULT)

    with ui.column().classes("w-full h-full min-h-0 overflow-hidden px-4 py-3 gap-0"):
        splitter = ui.splitter(value=app.storage.user[WORKSPACE_SPLIT_KEY])
        splitter.bind_value(app.storage.user, WORKSPACE_SPLIT_KEY)
        with splitter.classes("w-full h-full min-h-0"):
            with splitter.before:
                with ui.column().classes("w-full h-full min-h-0 gap-4 pr-4"):
                    if active_scene is not None:
                        _render_scene_editor(active_scene)
                    else:
                        _render_story_bible_panel(active_path)

            with splitter.after:
                with ui.column().classes("w-full h-full min-h-0 gap-4 pl-4"):
                    render_chat()


def _render_story_bible_panel(active_path: str) -> None:
    with ui.scroll_area().classes("w-full h-full min-h-0"):
        with ui.column().classes("w-full gap-4 pr-4"):
            if active_path == "/workspace/narrative-style":
                render_narrative_style_form()
            elif active_path == "/workspace/world":
                render_world_form()
            elif active_path.startswith("/workspace/characters"):
                render_characters_form(active_path)
            else:
                render_timeline_form(active_path)


def _render_workspace_sidebar(active_path: str, active_scene_id: str | None) -> None:
    heading_classes = "px-3 pt-2 text-xs font-semibold uppercase tracking-wide text-grey-7"

    with ui.left_drawer(value=True).props("bordered").classes("bg-grey-1"):
        with ui.column().classes("w-full gap-1"):
            ui.label("Story Bible").classes(heading_classes)
            for item in WORKSPACE_STORY_BIBLE_ITEMS:
                is_active = active_path == item.path or active_path.startswith(item.path + "/")
                button = ui.button(item.label, on_click=lambda path=item.path: ui.navigate.to(path))
                button.classes("w-full justify-start")
                button.props("unelevated color=primary" if is_active else "flat")

            ui.separator().classes("my-2")
            ui.label("Scenes").classes(heading_classes)
            _render_scenes_section(active_scene_id)


def _render_scenes_section(active_scene_id: str | None) -> None:
    @ui.refreshable
    def scene_rows() -> None:
        for scene in get_world().scenes:
            _render_scene_row(scene, active_scene_id)

    scene_rows()

    def create_scene_and_open() -> None:
        scene = create_scene()
        set_current_scene_id(scene.id)
        ui.navigate.to(f"/workspace/scenes/{scene.id}")

    new_scene_button = ui.button("New Scene", icon="add", on_click=create_scene_and_open)
    new_scene_button.classes("w-full justify-start")
    new_scene_button.props("flat")
    new_scene_button.mark("new-scene-button")

    snapshot = {"value": _scene_snapshot()}

    def maybe_refresh() -> None:
        current = _scene_snapshot()
        if current == snapshot["value"]:
            return
        snapshot["value"] = current
        try:
            scene_rows.refresh()
        except RuntimeError:
            # The client may be tearing down between the timer tick and the
            # refresh; the next page load rebuilds the sidebar anyway.
            pass

    ui.timer(1.0, maybe_refresh)


def _render_scene_row(scene: Scene, active_scene_id: str | None) -> None:
    path = f"/workspace/scenes/{scene.id}"
    with ui.row().classes("w-full items-center no-wrap gap-0"):
        button = ui.button(
            scene.title or "Untitled",
            on_click=lambda path=path: ui.navigate.to(path),
        )
        button.classes("grow justify-start")
        button.props("unelevated color=primary" if scene.id == active_scene_id else "flat")
        delete_button = ui.button(
            icon="delete",
            on_click=lambda scene=scene: _confirm_delete_scene(scene),
        )
        delete_button.props("flat round dense size=sm color=grey-7")
        delete_button.tooltip("Delete scene")


async def _confirm_delete_scene(scene: Scene) -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Delete scene '{scene.title}'? This cannot be undone.")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Delete", color="negative", on_click=lambda: dialog.submit(True))

    if not await dialog:
        return

    was_open = get_current_scene().id == scene.id
    try:
        delete_scene(scene.id)
    except ValueError as exc:
        ui.notify(str(exc), type="negative")
        return
    ui.notify(f"Deleted scene '{scene.title}'.")
    if was_open:
        ui.navigate.to("/workspace")


def _scene_snapshot() -> tuple[tuple[str, str], ...]:
    return tuple((scene.id, scene.title) for scene in get_world().scenes)


def _render_scene_editor(scene: Scene) -> None:
    def save() -> None:
        save_world()

    edit_state = {"edit_mode": True}

    def toggle_mode() -> None:
        edit_state["edit_mode"] = not edit_state["edit_mode"]
        toggle_button.set_icon(_toggle_icon(edit_state["edit_mode"]))
        toggle_tooltip.set_text(_toggle_tooltip(edit_state["edit_mode"]))

    with ui.row().classes("w-full items-center no-wrap"):
        title_input = ui.input(placeholder="Scene title").classes("text-xl font-semibold")
        title_input.classes("grow").props("outlined dense")
        title_input.bind_value(scene, "title")
        title_input.bind_visibility_from(edit_state, "edit_mode")
        title_input.on_value_change(lambda _: save())

        title_preview = ui.label("").classes("text-xl font-semibold grow")
        title_preview.bind_text_from(scene, "title", backward=lambda title: title or "Untitled")
        title_preview.bind_visibility_from(
            edit_state,
            "edit_mode",
            backward=lambda edit_mode: not edit_mode,
        )

        ui.space()
        toggle_button = ui.button(icon=_toggle_icon(edit_state["edit_mode"]), on_click=toggle_mode)
        toggle_button.props("flat round dense")
        toggle_tooltip = ui.tooltip(_toggle_tooltip(edit_state["edit_mode"]))

    summary_input = ui.input(placeholder="Scene summary").classes("w-full shrink-0")
    summary_input.props("dense outlined")
    summary_input.bind_value(scene, "summary")
    summary_input.bind_visibility_from(edit_state, "edit_mode")
    summary_input.on_value_change(lambda _: save())

    summary_preview = ui.label("").classes("w-full shrink-0")
    summary_preview.bind_text_from(scene, "summary")
    summary_preview.bind_visibility_from(
        edit_state,
        "edit_mode",
        backward=lambda edit_mode: not edit_mode,
    )

    render_markdown_editor(
        scene,
        "markdown",
        on_change=save,
        state=edit_state,
        show_toggle=False,
    )

    with ui.expansion("Notes", icon="sticky_note_2").classes("w-full shrink-0"):
        notes_input = ui.textarea(placeholder="Scene notes...").classes("w-full")
        notes_input.props("outlined autogrow")
        notes_input.bind_value(scene, "notes")
        notes_input.on_value_change(lambda _: save())


@ui.page("/workspace")
def workspace() -> None:
    _workspace_page("/workspace")


@ui.page("/workspace/story-bible")
def workspace_story_bible() -> None:
    ui.navigate.to("/workspace/characters")


@ui.page("/workspace/narrative-style")
def workspace_narrative_style() -> None:
    _workspace_page("/workspace/narrative-style")


@ui.page("/workspace/world")
def workspace_world() -> None:
    _workspace_page("/workspace/world")


@ui.page("/workspace/characters")
def workspace_characters() -> None:
    _workspace_page("/workspace/characters")


@ui.page("/workspace/characters/{character_id}")
def workspace_character(character_id: str) -> None:
    _workspace_page(f"/workspace/characters/{character_id}")


@ui.page("/workspace/timeline")
def workspace_timeline() -> None:
    _workspace_page("/workspace/timeline")


@ui.page("/workspace/events/{event_id}")
def workspace_event(event_id: str) -> None:
    _workspace_page(f"/workspace/events/{event_id}")


@ui.page("/workspace/scenes")
def workspace_scenes() -> None:
    ui.navigate.to("/workspace")


@ui.page("/workspace/scenes/{scene_id}")
def workspace_scene(scene_id: str) -> None:
    _workspace_page(f"/workspace/scenes/{scene_id}", scene_id=scene_id)
