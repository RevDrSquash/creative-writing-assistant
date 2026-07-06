"""Workspace pages: scene editor, Story Bible forms, and chat."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import app, ui

from app.graphs.jobs import get_job_manager
from app.ui.components.chat import render_chat
from app.ui.components.markdown_editor import (
    _toggle_icon,
    _toggle_tooltip,
    render_markdown_editor,
)
from app.ui.components.story_bible_forms import (
    render_characters_form,
    render_narrative_style_form,
    render_scene_blueprint_form,
    render_timeline_form,
    render_world_form,
)
from app.ui.layout import render_header
from app.ui.navigation import NavigationItem
from app.ui.save_helpers import save_world_ui
from app.ui.scene_selection import get_current_scene, set_current_scene_id
from app.world.models import Scene
from app.world.scene import create_scene, delete_scene, scene_is_generatable, scene_is_stale
from app.world.store import get_world

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
    if active_path.startswith("/workspace/scenes/"):
        if scene_id is not None:
            active_scene = get_world().get_scene(scene_id)
            if active_scene is None:
                ui.navigate.to("/workspace/narrative-style")
                return
            set_current_scene_id(active_scene.id)

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
                with ui.column().classes("w-full h-full min-h-0 gap-4 pr-4 overflow-y-auto"):
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
            if active_path == "/workspace/narrative-style" or active_path == "/workspace":
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
    manager = get_job_manager()
    path = f"/workspace/scenes/{scene.id}"
    with ui.row().classes("w-full items-center no-wrap gap-1"):
        button = ui.button(
            scene.title or "Untitled",
            on_click=lambda path=path: ui.navigate.to(path),
        )
        button.classes("grow justify-start")
        button.props("unelevated color=primary" if scene.id == active_scene_id else "flat")
        if manager.scene_is_claimed(scene.id):
            ui.spinner(size="xs").mark(f"scene-generating-{scene.id}")


async def _confirm_delete_scene(scene: Scene) -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Delete scene '{scene.title}'? This cannot be undone.")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Delete", color="negative", on_click=lambda: dialog.submit(True))

    if not await dialog:
        return

    current = get_current_scene()
    was_open = current is not None and current.id == scene.id
    try:
        delete_scene(scene.id)
    except ValueError as exc:
        ui.notify(str(exc), type="negative")
        return
    ui.notify(f"Deleted scene '{scene.title}'.")
    if was_open:
        ui.navigate.to("/workspace")


def _scene_snapshot() -> tuple[tuple[str, str, bool], ...]:
    manager = get_job_manager()
    return tuple(
        (scene.id, scene.title, manager.scene_is_claimed(scene.id)) for scene in get_world().scenes
    )


def _render_generation_controls(
    scene: Scene,
    edit_state: dict[str, object],
    *,
    on_generation_started: Callable[[], None] | None = None,
) -> None:
    """Render Generate/Regenerate controls with stale badge and status polling."""

    manager = get_job_manager()

    @ui.refreshable
    def controls() -> None:
        generating = manager.is_generating(scene.id)
        stale = scene_is_stale(scene)
        has_generated = scene.generated.generated_at is not None
        generatable = scene_is_generatable(scene)

        if stale:
            ui.badge("Stale").props("color=warning").mark("scene-stale-badge")

        if generating:
            button = ui.button("Generating...", icon="hourglass_empty")
            button.props("flat disable")
            button.mark("scene-generate-button")
            ui.spinner(size="sm").mark("scene-generate-spinner")
        elif not has_generated:
            button = ui.button("Generate", on_click=lambda: _start_generation(scene))
            button.mark("scene-generate-button")
            if generatable:
                button.props("color=primary")
            else:
                button.props("disable")
                button.tooltip("Set a premise and at least one enacted event first")
        elif stale:
            button = ui.button("Regenerate", on_click=lambda: _confirm_regenerate(scene))
            button.mark("scene-generate-button")
            button.props("color=warning")
        else:
            button = ui.button("Regenerate")
            button.mark("scene-generate-button")
            button.props("disable")
            button.tooltip("Blueprint unchanged since last generation")

        error = manager.last_error(scene.id)
        if error:
            ui.label(error).classes("text-negative text-sm")

    async def _confirm_regenerate(scene: Scene) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(
                "Regenerate this scene? Existing prose, outline, and stances will be discarded."
            )
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Regenerate", color="warning", on_click=lambda: dialog.submit(True))
        if await dialog:
            _start_generation(scene)

    def _start_generation(scene: Scene) -> None:
        edit_state["edit_mode"] = False
        try:
            manager.start_scene_generation(scene.id)
        except RuntimeError as exc:
            ui.notify(str(exc), type="warning")
            return
        if on_generation_started is not None:
            on_generation_started()
        controls.refresh()

    controls()
    ui.timer(1.0, controls.refresh)


def _render_scene_editor(scene: Scene) -> None:
    def save() -> None:
        save_world_ui()

    manager = get_job_manager()

    # Scenes without generated prose open in edit mode with the blueprint
    # expanded, so the writer can review the card and trigger generation.
    never_generated = scene.generated.generated_at is None
    edit_state = {"edit_mode": never_generated and not manager.scene_is_claimed(scene.id)}

    def sync_edit_mode_visibility() -> None:
        edit_mode = edit_state["edit_mode"]
        title_input.set_visibility(edit_mode)
        title_preview.set_visibility(not edit_mode)
        summary_input.set_visibility(edit_mode)
        summary_preview.set_visibility(not edit_mode)
        edit_state["sync_visibility"]()

    def toggle_mode() -> None:
        edit_state["edit_mode"] = not edit_state["edit_mode"]
        toggle_button.set_icon(_toggle_icon(edit_state["edit_mode"]))
        toggle_tooltip.set_text(_toggle_tooltip(edit_state["edit_mode"]))
        sync_edit_mode_visibility()

    with ui.row().classes("w-full items-center no-wrap shrink-0"):
        title_input = ui.input(placeholder="Scene title").classes("text-xl font-semibold")
        title_input.classes("grow").props("outlined dense")
        title_input.mark("scene-title-input")
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
        gen_column = ui.column().classes("inline shrink-0")

        toggle_button = ui.button(icon=_toggle_icon(edit_state["edit_mode"]), on_click=toggle_mode)
        toggle_button.props("flat round dense")
        toggle_button.mark("scene-editor-toggle-button")
        toggle_tooltip = ui.tooltip(_toggle_tooltip(edit_state["edit_mode"]))

        @ui.refreshable
        def edit_lock() -> None:
            claimed = manager.scene_is_claimed(scene.id)
            if claimed:
                if edit_state["edit_mode"]:
                    edit_state["edit_mode"] = False
                    toggle_button.set_icon(_toggle_icon(False))
                    sync_edit_mode_visibility()
                toggle_button.disable()
                toggle_tooltip.set_text("Scene is being generated")
            else:
                toggle_button.enable()
                toggle_tooltip.set_text(_toggle_tooltip(edit_state["edit_mode"]))

        with gen_column:
            _render_generation_controls(
                scene,
                edit_state,
                on_generation_started=edit_lock.refresh,
            )
        delete_button = ui.button(
            icon="delete",
            on_click=lambda scene=scene: _confirm_delete_scene(scene),
        )
        delete_button.props("flat round dense size=sm color=grey-7")
        delete_button.tooltip("Delete scene")
        delete_button.mark("scene-editor-delete-button")

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

    render_scene_blueprint_form(scene, edit_state, expand_blueprint=never_generated)

    render_markdown_editor(
        scene,
        "markdown",
        on_change=save,
        state=edit_state,
        show_toggle=False,
        min_height="min-h-[24rem]",
    )

    sync_edit_mode_visibility()

    edit_lock()
    ui.timer(1.0, edit_lock.refresh)

    with ui.expansion("Notes", icon="sticky_note_2").classes("w-full shrink-0"):
        notes_input = ui.textarea(placeholder="Scene notes...").classes("w-full")
        notes_input.props("outlined autogrow")
        notes_input.bind_value(scene, "notes")
        notes_input.on_value_change(lambda _: save())


@ui.page("/workspace")
def workspace() -> None:
    ui.navigate.to("/workspace/narrative-style")


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
    ui.navigate.to("/workspace/narrative-style")


@ui.page("/workspace/scenes/{scene_id}")
def workspace_scene(scene_id: str) -> None:
    _workspace_page(f"/workspace/scenes/{scene_id}", scene_id=scene_id)
