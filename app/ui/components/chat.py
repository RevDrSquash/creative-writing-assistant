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
from app.ui.scene_selection import set_current_scene_id
from app.world.scene import resolve_scene, set_scene_text


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
        start_scene = resolve_scene()
        run_scene_id = start_scene.id if start_scene is not None else ""
        stream_failed = False
        try:
            messages = conversation.agent_messages()
            async for stream_name, payload in get_chat_agent().astream(
                {
                    "messages": messages,
                    "current_scene": start_scene.markdown if start_scene is not None else "",
                    "current_scene_id": run_scene_id,
                },
                stream_mode=["messages", "updates"],
            ):
                if stream_name == "updates":
                    run_scene_id = _scene_id_from_payload(payload, run_scene_id)
                    continue
                if stream_name != "messages":
                    continue

                token, _metadata = payload
                content = _token_text(token)
                if not content:
                    continue
                assistant_text = _append_streamed_chat_text(
                    assistant_text,
                    content,
                    assistant_markdown,
                )

        except Exception as exc:
            stream_failed = True
            error_text = f"Chat agent error: {exc}"
            _safe_ui_update(lambda: assistant_markdown.set_content(error_text))
            _safe_ui_update(lambda: ui.notify(error_text, type="negative"))
        finally:
            _safe_ui_update(spinner.delete)
            if assistant_text and not stream_failed:
                conversation.add_assistant_message(assistant_text)
            _safe_ui_update(message_input.enable)
            _safe_ui_update(send_button.enable)
            is_streaming = False

        if run_scene_id and (start_scene is None or run_scene_id != start_scene.id):
            set_current_scene_id(run_scene_id)
            _safe_ui_update(lambda: ui.navigate.to(f"/workspace/scenes/{run_scene_id}"))

    send_button.on_click(send_message)


def _safe_ui_update(action: Callable[[], None]) -> None:
    """Apply a UI update that may race page teardown."""

    try:
        action()
    except RuntimeError:
        pass


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
        content = content.lstrip()
        if not content:
            return assistant_text

    assistant_text += content
    assistant_markdown.set_content(assistant_text)
    return assistant_text


def _scene_id_from_payload(
    payload: Any,
    current_id: str,
    scene_setter: Callable[[str, str], None] = set_scene_text,
) -> str:
    """Return the scene id from graph updates, persisting scene text when present."""

    if not isinstance(payload, dict):
        return current_id

    for node_updates in payload.values():
        if not isinstance(node_updates, dict):
            continue
        new_id = node_updates.get("current_scene_id")
        if isinstance(new_id, str) and new_id:
            current_id = new_id
        new_scene = node_updates.get("current_scene")
        if isinstance(new_scene, str):
            scene_setter(current_id, new_scene)
    return current_id
