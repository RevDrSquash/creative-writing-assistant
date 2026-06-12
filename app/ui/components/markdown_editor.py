"""Reusable Markdown editor with edit and preview modes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui

# Quasar's q-input (type=textarea) wraps the native <textarea> in several
# layers (.q-field__inner > .q-field__control > .q-field__control-container).
# Setting `h-full` on the outer field and `input-class="h-full"` on the native
# input only pins the two ends of that chain; the intermediate wrappers
# default to auto height, so the native textarea's height: 100% resolves to
# the wrappers' intrinsic size (~`rows` lines). Force the chain to inherit
# full height, scoped to a marker class so chat-style autogrow textareas are
# unaffected.
ui.add_css(
    """
    .nicegui-fill-textarea .q-field__inner,
    .nicegui-fill-textarea .q-field__control,
    .nicegui-fill-textarea .q-field__control-container {
        height: 100%;
    }
    """,
    shared=True,
)


def render_markdown_editor(
    target: Any,
    field: str,
    *,
    placeholder: str = "Write Markdown here...",
    edit_default: bool = True,
    on_change: Callable[[], None] | None = None,
) -> None:
    """Render a textarea-backed Markdown editor bound to ``target[field]``.

    ``on_change`` is invoked (throttled) as the user edits, after the bound
    value has been updated; use it to write the change through to disk.
    """

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
            if on_change is not None:
                textarea.on("update:model-value", lambda _: on_change(), throttle=1.0)
            textarea.bind_visibility_from(state, "edit_mode")
            textarea.props(
                "outlined autogrow=false hide-bottom-space"
                ' input-class="h-full" input-style="resize: none;"'
            )
            textarea.classes("w-full h-full nicegui-fill-textarea")

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
