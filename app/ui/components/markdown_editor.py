"""Reusable Markdown editor with edit and preview modes."""

from __future__ import annotations

from typing import Any

from nicegui import ui


def render_markdown_editor(
    target: Any,
    field: str,
    *,
    placeholder: str = "Write Markdown here...",
    edit_default: bool = True,
) -> None:
    """Render a textarea-backed Markdown editor bound to ``target[field]``."""

    state = {"edit_mode": edit_default}

    def toggle_mode() -> None:
        state["edit_mode"] = not state["edit_mode"]
        toggle_button.set_icon(_toggle_icon(state["edit_mode"]))
        toggle_tooltip.set_text(_toggle_tooltip(state["edit_mode"]))

    with ui.column().classes("w-full h-full min-h-0 gap-2"):
        with ui.row().classes("w-full justify-end items-center shrink-0"):
            toggle_button = ui.button(icon=_toggle_icon(state["edit_mode"]), on_click=toggle_mode)
            toggle_button.props("flat round dense")
            toggle_tooltip = ui.tooltip(_toggle_tooltip(state["edit_mode"]))

        with ui.column().classes("w-full grow min-h-0"):
            textarea = ui.textarea(placeholder=placeholder)
            textarea.bind_value(target, field)
            textarea.bind_visibility_from(state, "edit_mode")
            textarea.props('outlined autogrow=false input-class="h-full" input-style="resize: none;"')
            textarea.classes("w-full h-full")

            preview_scroll = ui.scroll_area().classes("w-full grow min-h-0 border rounded p-3")
            with preview_scroll:
                preview = ui.markdown("").classes("w-full")
                preview.bind_content_from(target, field)
            preview_scroll.bind_visibility_from(
                state,
                "edit_mode",
                backward=lambda edit_mode: not edit_mode,
            )


def _toggle_icon(edit_mode: bool) -> str:
    return "visibility" if edit_mode else "edit"


def _toggle_tooltip(edit_mode: bool) -> str:
    return "Preview Markdown" if edit_mode else "Edit Markdown"
