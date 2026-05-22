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
USER_NAME = "You"
ASSISTANT_NAME = "Writing Agent"


def render_chat() -> None:
    """Render a simple streaming chat interface."""

    app.storage.user.setdefault(CHAT_HISTORY_KEY, [])
    assembler = ContextAssembler()
    configuration_error = _chat_configuration_error()
    is_streaming = False

    with ui.column().classes("w-full h-full gap-3"):
        ui.label("AI Chat Interface").classes("text-xl font-semibold")
        ui.label("Ask for brainstorming, drafting, revision, or continuity help.").classes(
            "text-grey-7"
        )
        if configuration_error:
            with ui.card().classes("w-full bg-red-1 text-negative"):
                ui.label("Chat is disabled because model settings are invalid.").classes(
                    "font-semibold"
                )
                ui.label(configuration_error)

        with ui.scroll_area().classes("w-full h-[60vh] border rounded p-3 bg-grey-1"):
            with ui.column().classes("w-full gap-3") as message_column:
                for message in app.storage.user[CHAT_HISTORY_KEY]:
                    _render_stored_message(message)

        with ui.row().classes("w-full items-end gap-2"):
            message_input = ui.textarea(placeholder="Message the writing agent...").classes("grow")
            message_input.props("outlined autogrow")
            send_button = ui.button("Send", color="primary")
            if configuration_error:
                message_input.disable()
                send_button.disable()

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

            assistant_message = ui.chat_message(name=ASSISTANT_NAME, sent=False)
            with assistant_message:
                assistant_markdown = ui.markdown("")
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
    message_input.on("keydown.enter.exact.prevent", send_message)


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
    is_user = role == "user"
    name = USER_NAME if is_user else ASSISTANT_NAME
    with ui.chat_message(name=name, sent=is_user):
        ui.markdown(message["content"])


def _token_text(token: BaseMessageChunk | Any) -> str:
    content = getattr(token, "content", "")
    return content if isinstance(content, str) else ""
