"""Reusable NiceGUI chat panel for the LangGraph writing agent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui
from pydantic import ValidationError

from app.graphs.jobs import ChatLive, get_job_manager
from app.models import ModelSettings
from app.persistence import ChatConversation, StoredChatMessage, get_chat_conversation
from app.ui.scene_selection import set_current_scene_id


def render_chat(conversation: ChatConversation | None = None) -> None:
    """Render a simple streaming chat interface."""

    conversation = conversation or get_chat_conversation()
    manager = get_job_manager()
    configuration_error = _chat_configuration_error()
    already_finished = {job.id for job in manager.finished_jobs() if job.kind == "chat_turn"}
    handled_navigations: set[str] = set(already_finished)
    rendered_finished_jobs: set[str] = set(already_finished)

    with ui.column().classes("w-full h-full min-h-0 gap-3"):
        if configuration_error:
            with ui.card().classes("w-full bg-red-1 text-negative"):
                ui.label("Chat is disabled because model settings are invalid.").classes(
                    "font-semibold"
                )
                ui.label(configuration_error)

        with ui.scroll_area().classes("w-full grow min-h-0 border rounded p-2 bg-grey-1"):
            with ui.column().classes("w-full gap-2").mark("chat-message-column") as message_column:
                for message in conversation.history():
                    _render_stored_message(message)

                @ui.refreshable
                def live_assistant_message() -> None:
                    job = manager.active_chat_job()
                    if job is None or not isinstance(job.live, ChatLive):
                        return
                    live = job.live
                    if not live.assistant_text and job.status == "running":
                        with ui.column().classes(_message_classes("assistant")):
                            ui.spinner(size="sm").mark("chat-live-spinner")
                        return
                    if live.assistant_text:
                        with ui.column().classes(_message_classes("assistant")):
                            ui.markdown(live.assistant_text).classes("w-full").mark(
                                "chat-live-assistant"
                            )
                            if job.status == "running":
                                ui.spinner(size="sm").mark("chat-live-spinner")

                with ui.column().classes("w-full") as live_container:
                    live_assistant_message()

        with ui.row().classes("w-full shrink-0 items-end gap-2"):
            message_input = ui.textarea(placeholder="Message the writing agent...").classes("grow")
            message_input.props('outlined autogrow rows=3 input-style="max-height: 12rem"')
            send_button = ui.button("Send", color="primary")
            send_button.mark("chat-send-button")
            with ui.button(icon="settings").props("flat round"):
                with ui.menu():
                    ui.menu_item("Clear chat history", on_click=lambda: clear_chat_history())
            if configuration_error:
                message_input.disable()
                send_button.disable()

    @ui.refreshable
    def send_controls() -> None:
        if configuration_error or manager.chat_is_claimed():
            message_input.disable()
            send_button.disable()
        else:
            message_input.enable()
            send_button.enable()

    send_controls()

    def clear_chat_history() -> None:
        if manager.chat_is_claimed():
            ui.notify("Wait for the current response to finish before clearing chat history.")
            return

        conversation.clear()
        message_column.clear()
        ui.notify("Chat history cleared.")

    async def send_message() -> None:
        if configuration_error:
            ui.notify(configuration_error, type="negative")
            return
        if manager.chat_is_claimed():
            return

        user_text = (message_input.value or "").strip()
        if not user_text:
            return

        message_input.set_value("")
        try:
            manager.start_chat_turn(user_text, conversation)
        except RuntimeError as exc:
            ui.notify(str(exc), type="warning")
            return

        user_message = conversation.history()[-1]
        with message_column:
            _render_stored_message(user_message)

        live_container.move(message_column)
        send_controls.refresh()
        live_assistant_message.refresh()

    send_button.on_click(send_message)

    live_snapshot = {"version": -1, "job_id": ""}

    def poll_chat_job() -> None:
        job = manager.active_chat_job()
        if job is None:
            finished = _latest_finished_chat_job(manager)
            if finished is not None:
                if finished.id not in rendered_finished_jobs and isinstance(
                    finished.live, ChatLive
                ):
                    rendered_finished_jobs.add(finished.id)
                    if finished.live.assistant_text and finished.status == "finished":
                        with message_column:
                            _render_stored_message(
                                {
                                    "role": "assistant",
                                    "content": finished.live.assistant_text,
                                }
                            )
                    live_assistant_message.refresh()
                if isinstance(finished.live, ChatLive):
                    nav_id = finished.live.pending_navigation_scene_id
                    if nav_id and finished.id not in handled_navigations:
                        handled_navigations.add(finished.id)
                        set_current_scene_id(nav_id)
                        ui.navigate.to(f"/workspace/scenes/{nav_id}")
            if live_snapshot["job_id"]:
                live_snapshot["job_id"] = ""
                live_snapshot["version"] = -1
                send_controls.refresh()
            return

        if not isinstance(job.live, ChatLive):
            return

        if job.live.version != live_snapshot["version"] or job.id != live_snapshot["job_id"]:
            live_snapshot["version"] = job.live.version
            live_snapshot["job_id"] = job.id
            live_assistant_message.refresh()

        if job.status != "running":
            send_controls.refresh()

        if isinstance(job.live, ChatLive):
            nav_id = job.live.pending_navigation_scene_id
            if nav_id and job.id not in handled_navigations:
                handled_navigations.add(job.id)
                set_current_scene_id(nav_id)
                ui.navigate.to(f"/workspace/scenes/{nav_id}")

    ui.timer(0.25, poll_chat_job)


def _latest_finished_chat_job(manager: Any) -> Any | None:
    for job in reversed(manager.finished_jobs()):
        if job.kind == "chat_turn":
            return job
    return None


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
