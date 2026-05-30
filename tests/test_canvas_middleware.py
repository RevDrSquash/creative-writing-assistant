"""Unit tests for canvas append middleware."""

from langchain_core.messages import AIMessage, ToolMessage

from app.graphs.canvas_middleware import CanvasAppendMiddleware


def test_canvas_middleware_ignores_messages_without_blocks() -> None:
    middleware = CanvasAppendMiddleware()
    state = {
        "messages": [AIMessage(content="Just chat.")],
        "current_scene": "Existing scene",
    }

    assert middleware.after_model(state, None) is None
    assert state["current_scene"] == "Existing scene"


def test_canvas_middleware_appends_to_empty_scene() -> None:
    middleware = CanvasAppendMiddleware()

    update = middleware.after_model(
        {"messages": [AIMessage(content="<canvas>First line.</canvas>")], "current_scene": ""},
        None,
    )

    assert update == {"current_scene": "First line."}


def test_canvas_middleware_joins_non_empty_scene_with_blank_line() -> None:
    middleware = CanvasAppendMiddleware()

    update = middleware.after_model(
        {
            "messages": [AIMessage(content="<canvas>New paragraph.</canvas>")],
            "current_scene": "Existing paragraph.",
        },
        None,
    )

    assert update == {"current_scene": "Existing paragraph.\n\nNew paragraph."}


def test_canvas_middleware_joins_scene_ending_with_newline_without_extra_blank_line() -> None:
    middleware = CanvasAppendMiddleware()

    update = middleware.after_model(
        {
            "messages": [AIMessage(content="<canvas>Next line.</canvas>")],
            "current_scene": "Existing line.\n",
        },
        None,
    )

    assert update == {"current_scene": "Existing line.\nNext line."}


def test_canvas_middleware_appends_multiple_blocks_in_order() -> None:
    middleware = CanvasAppendMiddleware()

    update = middleware.after_model(
        {
            "messages": [
                AIMessage(content="Chat <canvas>One.</canvas> more <canvas>Two.</canvas>")
            ],
            "current_scene": "Existing.",
        },
        None,
    )

    assert update == {"current_scene": "Existing.\n\nOne.\n\nTwo."}


def test_canvas_middleware_ignores_non_ai_message() -> None:
    middleware = CanvasAppendMiddleware()

    update = middleware.after_model(
        {
            "messages": [ToolMessage(content="<canvas>Ignored.</canvas>", tool_call_id="tool-1")],
            "current_scene": "Existing.",
        },
        None,
    )

    assert update is None
