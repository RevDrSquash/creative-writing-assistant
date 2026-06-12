"""LLM debug call log pages."""

from __future__ import annotations

import json
from typing import Any

from nicegui import ui

from app.persistence import LLMCallRecord, get_llm_call_log_store
from app.ui.layout import find_item, render_header
from app.ui.navigation import NavigationItem


def _debug_sidebar_items() -> tuple[NavigationItem, ...]:
    return tuple(
        NavigationItem(
            _call_label(record),
            f"/debug/calls/{record.run_id}",
            f"{record.status} LLM call",
        )
        for record in get_llm_call_log_store().list()
    )


def _render_debug_shell(active_path: str) -> NavigationItem:
    render_header("/debug")

    @ui.refreshable
    def sidebar() -> None:
        sidebar_items = _debug_sidebar_items()
        if not sidebar_items:
            ui.label("No LLM calls yet.").classes("px-3 py-2 text-sm text-grey-7")
            return

        with ui.column().classes("w-full gap-1"):
            for item in sidebar_items:
                button = ui.button(item.label, on_click=lambda path=item.path: ui.navigate.to(path))
                button.classes("w-full justify-start")
                button.props("flat" if item.path != active_path else "unelevated color=primary")

    with ui.left_drawer(value=True).props("bordered").classes("bg-grey-1"):
        sidebar()
        ui.timer(2.0, sidebar.refresh)

    return find_item(
        _debug_sidebar_items(),
        active_path,
        NavigationItem("Debug", "/debug", "LLM call debug logs"),
    )


def _debug_index_page() -> None:
    newest = next(iter(get_llm_call_log_store().list()), None)
    if newest is not None:
        ui.navigate.to(f"/debug/calls/{newest.run_id}")
        return

    _render_debug_shell("/debug")
    with ui.column().classes("w-full max-w-4xl gap-4 p-4"):
        ui.label("Debug").classes("text-2xl font-semibold")
        ui.label("LLM calls will appear here after the chat agent invokes a model.").classes(
            "text-grey-7"
        )


def _debug_call_page(run_id: str) -> None:
    active_path = f"/debug/calls/{run_id}"
    active_item = _render_debug_shell(active_path)
    record = get_llm_call_log_store().get(run_id)

    with ui.column().classes("w-full max-w-5xl gap-4 p-4"):
        ui.label(active_item.label).classes("text-2xl font-semibold")
        if record is None:
            ui.label(f"No LLM call exists for '{run_id}'.").classes("text-negative")
            return

        with ui.row().classes("items-center gap-3"):
            ui.badge(record.status, color=_status_color(record.status))
            ui.label(f"Started: {_display_timestamp(record.started_at)}").classes(
                "text-sm text-grey-7"
            )
            if record.duration_ms is not None:
                ui.label(f"Duration: {record.duration_ms} ms").classes("text-sm text-grey-7")
            for label, count in _token_counts(record.response_metadata).items():
                if count is not None:
                    ui.label(f"{label}: {count}").classes("text-sm text-grey-7")

        _render_mapping_section("Params", record.params, expanded=False)
        _render_prompt_section(record)
        if record.status == "error":
            _render_code_section("Error", record.error or "(no error captured)")
        else:
            _render_markdown_section("Response", record.response_text or "_(no response captured)_")
            _render_mapping_section("Response Metadata", record.response_metadata, expanded=False)


SECTION_BORDER_STYLE = "border: 1px solid #d1d5db"


def _section_expansion(title: str, *, expanded: bool) -> ui.expansion:
    expansion = ui.expansion(title, value=expanded)
    expansion.classes("w-full rounded-md overflow-hidden")
    expansion.style(SECTION_BORDER_STYLE)
    expansion.props('header-class="text-lg font-semibold"')
    return expansion


def _block_expansion(title: str, *, expanded: bool) -> ui.expansion:
    expansion = ui.expansion(title, value=expanded)
    expansion.classes("w-full rounded-md overflow-hidden")
    expansion.style(SECTION_BORDER_STYLE)
    expansion.props('header-class="text-sm font-semibold uppercase tracking-wide text-grey-8"')
    return expansion


def _render_mapping_section(title: str, values: dict[str, Any], *, expanded: bool = True) -> None:
    with _section_expansion(title, expanded=expanded):
        if not values:
            ui.label("No values captured.").classes("text-sm text-grey-7")
            return
        ui.code(json.dumps(values, indent=2), language="json").classes("w-full")


def _render_code_section(title: str, value: str, *, expanded: bool = True) -> None:
    with _section_expansion(title, expanded=expanded):
        ui.code(value).classes("w-full whitespace-pre-wrap")


def _render_markdown_section(title: str, value: str, *, expanded: bool = True) -> None:
    with _section_expansion(title, expanded=expanded):
        ui.markdown(_escape_html(value)).classes("w-full")


def _render_prompt_section(record: LLMCallRecord) -> None:
    with _section_expansion("Compiled Prompt", expanded=True):
        blocks = _prompt_blocks(record.prompt_messages)
        if not blocks:
            ui.markdown(_escape_html(record.prompt) or "_(empty)_").classes("w-full")
            return
        with ui.column().classes("w-full gap-3"):
            for title, kind, content in blocks:
                with _block_expansion(title, expanded=True):
                    if kind == "json":
                        ui.code(content, language="json").classes("w-full")
                    else:
                        ui.markdown(_escape_html(content) or "_(empty)_").classes("w-full")


def _prompt_blocks(messages: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    blocks: list[tuple[str, str, str]] = []
    for message in messages:
        role = str(message.get("role") or "unknown")
        content = str(message.get("content") or "").strip()
        if role == "system":
            if content:
                blocks.append(("System Prompt", "markdown", content))
        elif role == "user":
            if content:
                blocks.append(("User Message", "markdown", content))
        elif role == "assistant":
            if content:
                blocks.append(("Assistant Message", "markdown", content))
            for call in message.get("tool_calls") or []:
                name = str(call.get("name") or "tool")
                blocks.append((f"Tool Call: {name}", "json", _tool_call_json(call)))
        elif role == "tool":
            name = str(message.get("name") or "tool")
            blocks.append((f"Tool Response: {name}", "markdown", content))
        elif content:
            blocks.append((role.replace("_", " ").title(), "markdown", content))
    return blocks


def _tool_call_json(call: dict[str, Any]) -> str:
    payload: dict[str, Any] = {"name": call.get("name"), "args": call.get("args")}
    if call.get("id"):
        payload["id"] = call.get("id")
    return json.dumps(payload, indent=2)


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _token_counts(metadata: dict[str, Any]) -> dict[str, int | None]:
    usage = metadata.get("usage_metadata")
    if isinstance(usage, dict):
        details = usage.get("output_token_details")
        reasoning = details.get("reasoning") if isinstance(details, dict) else None
        return {
            "Input": _as_int(usage.get("input_tokens")),
            "Output": _as_int(usage.get("output_tokens")),
            "Reasoning": _as_int(reasoning),
            "Total": _as_int(usage.get("total_tokens")),
        }

    token_usage = metadata.get("token_usage")
    if isinstance(token_usage, dict):
        details = token_usage.get("completion_tokens_details")
        reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
        return {
            "Input": _as_int(token_usage.get("prompt_tokens")),
            "Output": _as_int(token_usage.get("completion_tokens")),
            "Reasoning": _as_int(reasoning),
            "Total": _as_int(token_usage.get("total_tokens")),
        }

    return {"Input": None, "Output": None, "Reasoning": None, "Total": None}


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _call_label(record: LLMCallRecord) -> str:
    marker = {"running": "RUN", "success": "OK", "error": "ERR"}[record.status]
    model = record.model or "unknown model"
    timestamp = _display_timestamp(record.started_at)
    return f"{marker} {model} {timestamp}"


def _display_timestamp(value: str) -> str:
    return value.replace("T", " ").split(".", maxsplit=1)[0]


def _status_color(status: str) -> str:
    return {
        "running": "warning",
        "success": "positive",
        "error": "negative",
    }.get(status, "grey")


@ui.page("/debug")
def debug() -> None:
    _debug_index_page()


@ui.page("/debug/calls/{run_id}")
def debug_call(run_id: str) -> None:
    _debug_call_page(run_id)
