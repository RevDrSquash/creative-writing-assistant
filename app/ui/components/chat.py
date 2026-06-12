"""Reusable NiceGUI chat panel for the LangGraph writing agent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessageChunk
from nicegui import ui
from pydantic import ValidationError

from app.graphs import get_chat_agent
from app.models import ModelSettings
from app.persistence import ChatConversation, StoredChatMessage, get_chat_conversation
from app.ui.components.canvas_stream_parser import CanvasStreamParser, ParseEvents
from app.world.scene import get_current_scene_text, set_current_scene_text


def render_chat(conversation: ChatConversation | None = None) -> None:
    """Render a simple streaming chat interface."""

    conversation = conversation or get_chat_conversation()
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
                for message in conversation.history():
                    _render_stored_message(message)

        with ui.row().classes("w-full shrink-0 items-end gap-2"):
            message_input = ui.textarea(placeholder="Message the writing agent...").classes("grow")
            message_input.props('outlined autogrow rows=3 input-style="max-height: 12rem"')
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

        conversation.clear()
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

        user_message = conversation.add_user_message(user_text)
        with message_column:
            _render_stored_message(user_message)

            with ui.column().classes(_message_classes("assistant")):
                assistant_markdown = ui.markdown("").classes("w-full")
                spinner = ui.spinner(size="sm")

        assistant_text = ""
        pre_stream_scene = get_current_scene_text()
        parser = CanvasStreamParser()
        stream_failed = False
        try:
            messages = conversation.agent_messages()
            async for stream_name, payload in get_chat_agent().astream(
                {
                    "messages": messages,
                    "current_scene": pre_stream_scene,
                },
                stream_mode=["messages", "updates"],
            ):
                if stream_name == "updates":
                    _write_scene_updates_from_payload(payload)
                    continue
                if stream_name != "messages":
                    continue

                token, _metadata = payload
                content = _token_text(token)
                if not content:
                    continue
                events = parser.feed(content)
                if events.canvas_text:
                    set_current_scene_text(get_current_scene_text() + events.canvas_text)
                assistant_text = _append_streamed_chat_text(
                    assistant_text,
                    events.chat_text,
                    assistant_markdown,
                )

            flush_events = parser.flush()
            if _apply_canvas_flush_events(flush_events, pre_stream_scene):
                pass
            else:
                assistant_text = _append_streamed_chat_text(
                    assistant_text,
                    flush_events.chat_text,
                    assistant_markdown,
                )
        except Exception as exc:
            stream_failed = True
            error_text = f"Chat agent error: {exc}"
            assistant_markdown.set_content(error_text)
            ui.notify(error_text, type="negative")
        finally:
            spinner.delete()
            # Only persist genuine assistant output; never store error messages
            # as assistant turns, since they would poison subsequent model context.
            if assistant_text and not stream_failed:
                conversation.add_assistant_message(assistant_text)
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
    # stream_mode="messages" emits every message added to the graph's
    # `messages` channel, including the SystemMessage our middleware writes
    # in `before_model`. Only LLM-generated `AIMessageChunk`s should reach
    # the assistant markdown; everything else (system/remove/tool messages)
    # is graph plumbing, not assistant output.
    if not isinstance(token, AIMessageChunk):
        return ""
    content = getattr(token, "content", "")
    return content if isinstance(content, str) else ""


def _append_streamed_chat_text(
    assistant_text: str,
    content: str,
    assistant_markdown: Any,
) -> str:
    if not content:
        return assistant_text
    if not assistant_text:
        # Models frequently start a stream with a stray leading space. NiceGUI's
        # markdown auto-dedent would then chew the first character off every
        # subsequent line during live rendering, so trim it before storing.
        content = content.lstrip()
        if not content:
            return assistant_text

    assistant_text += content
    assistant_markdown.set_content(assistant_text)
    return assistant_text


def _apply_canvas_flush_events(
    events: ParseEvents,
    pre_stream_scene: str,
    scene_setter: Callable[[str], None] = set_current_scene_text,
) -> bool:
    if not events.unterminated_canvas:
        return False

    scene_setter(pre_stream_scene)
    return True


def _write_scene_updates_from_payload(
    payload: Any,
    scene_setter: Callable[[str], None] = set_current_scene_text,
) -> None:
    if not isinstance(payload, dict):
        return

    for node_updates in payload.values():
        if not isinstance(node_updates, dict):
            continue
        new_scene = node_updates.get("current_scene")
        if isinstance(new_scene, str):
            scene_setter(new_scene)
