"""Reusable NiceGUI chat panel for the LangGraph writing agent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import BaseMessageChunk
from nicegui import app, ui
from pydantic import ValidationError

from app.graphs import ContextAssembler, get_chat_agent
from app.graphs.context import StoredChatMessage
from app.models import ModelSettings

CHAT_HISTORY_KEY = "chat_history"


def render_chat() -> None:
    """Render a simple streaming chat interface."""

    app.storage.user.setdefault(CHAT_HISTORY_KEY, [])
    assembler = ContextAssembler()
    configuration_error = _chat_configuration_error()
    is_streaming = False

    with ui.column().classes("w-full h-full min-h-0 gap-3"):
        if configuration_error:
            with ui.card().classes("w-full bg-red-1 text-negative"):
                ui.label("Chat is disabled because model settings are invalid.").classes(
                    "font-semibold"
                )
                ui.label(configuration_error)

        with ui.scroll_area().classes("w-full grow min-h-0 border rounded p-2 bg-grey-1"):
            with ui.column().classes("w-full gap-2") as message_column:
                for message in app.storage.user[CHAT_HISTORY_KEY]:
                    _render_stored_message(message)

        with ui.row().classes("w-full shrink-0 items-end gap-2"):
            message_input = ui.textarea(placeholder="Message the writing agent...").classes("grow")
            message_input.props(
                'outlined autogrow rows=3 input-style="max-height: 12rem"'
            )
            send_button = ui.button("Send", color="primary")
            with ui.button(icon="settings").props("flat round"):
                with ui.menu():
                    ui.menu_item("Clear chat history", on_click=lambda: clear_chat_history())
            if configuration_error:
                message_input.disable()
                send_button.disable()

    def clear_chat_history() -> None:
        if is_streaming:
            ui.notify("Wait for the current response to finish before clearing chat history.")
            return

        app.storage.user[CHAT_HISTORY_KEY] = []
        message_column.clear()
        ui.notify("Chat history cleared.")

    async def send_message() -> None:
        nonlocal is_streaming
        if configuration_error:
            ui.notify(configuration_error, type="negative")
            return
        if is_streaming:
            return

        user_text = (message_input.value or "").strip()
        if not user_text:
            return

        is_streaming = True
        message_input.disable()
        send_button.disable()
        message_input.set_value("")

        user_message: StoredChatMessage = {"role": "user", "content": user_text}
        app.storage.user[CHAT_HISTORY_KEY].append(user_message)
        with message_column:
            _render_stored_message(user_message)

            with ui.column().classes(_message_classes("assistant")):
                assistant_markdown = ui.markdown("").classes("w-full")
                spinner = ui.spinner(size="sm")

        assistant_text = ""
        try:
            stored_history = app.storage.user[CHAT_HISTORY_KEY]
            messages = assembler.assemble(assembler.from_storage(stored_history))
            async for token, _metadata in get_chat_agent().astream(
                {"messages": messages},
                stream_mode="messages",
            ):
                content = _token_text(token)
                if not content:
                    continue
                assistant_text += content
                assistant_markdown.set_content(assistant_text)
        except Exception as exc:
            assistant_text = f"Chat agent error: {exc}"
            assistant_markdown.set_content(assistant_text)
            ui.notify(assistant_text, type="negative")
        finally:
            spinner.delete()
            if assistant_text:
                app.storage.user[CHAT_HISTORY_KEY].append(
                    {"role": "assistant", "content": assistant_text}
                )
            message_input.enable()
            send_button.enable()
            is_streaming = False

    send_button.on_click(send_message)


def _chat_configuration_error(
    settings_factory: Callable[[], ModelSettings] = ModelSettings,
) -> str | None:
    try:
        settings_factory()
    except ValidationError as exc:
        first_error = exc.errors()[0]
        return str(first_error["msg"])
    return None


def _render_stored_message(message: StoredChatMessage) -> None:
    role = message["role"]
    with ui.column().classes(_message_classes(role)):
        ui.markdown(message["content"]).classes("w-full")


def _message_classes(role: str) -> str:
    if role == "user":
        return "w-full rounded border border-grey-4 bg-grey-2 px-2 py-2"
    return "w-full px-2 py-1"


def _token_text(token: BaseMessageChunk | Any) -> str:
    content = getattr(token, "content", "")
    return content if isinstance(content, str) else ""
