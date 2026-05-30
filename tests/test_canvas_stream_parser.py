"""Unit tests for parsing streamed canvas append blocks."""

import pytest

from app.ui.components.canvas_stream_parser import CanvasStreamParser


def _parse_chunks(chunks: list[str]) -> tuple[str, str, bool]:
    parser = CanvasStreamParser()
    chat_text = ""
    canvas_text = ""
    for chunk in chunks:
        events = parser.feed(chunk)
        chat_text += events.chat_text
        canvas_text += events.canvas_text

    events = parser.flush()
    chat_text += events.chat_text
    canvas_text += events.canvas_text
    return chat_text, canvas_text, events.unterminated_canvas


def test_chat_only_stream_passes_through() -> None:
    assert _parse_chunks(["Hello", " writer."]) == ("Hello writer.", "", False)


def test_single_canvas_block_in_one_chunk() -> None:
    assert _parse_chunks(["Intro <canvas>Draft text.</canvas> Outro"]) == (
        "Intro  Outro",
        "Draft text.",
        False,
    )


@pytest.mark.parametrize("split_index", range(len("Hi <canvas>Draft</canvas> bye") + 1))
def test_single_canvas_block_split_at_every_position(split_index: int) -> None:
    text = "Hi <canvas>Draft</canvas> bye"

    assert _parse_chunks([text[:split_index], text[split_index:]]) == (
        "Hi  bye",
        "Draft",
        False,
    )


def test_open_tag_split_across_chunks() -> None:
    assert _parse_chunks(["Before <ca", "nvas>new prose</canvas> after"]) == (
        "Before  after",
        "new prose",
        False,
    )


def test_close_tag_split_across_chunks() -> None:
    assert _parse_chunks(["<canvas>new prose</can", "vas> done"]) == (
        " done",
        "new prose",
        False,
    )


def test_multiple_canvas_blocks_append_in_order() -> None:
    assert _parse_chunks(["A<canvas>one</canvas>B<canvas>two</canvas>C"]) == (
        "ABC",
        "onetwo",
        False,
    )


def test_back_to_back_canvas_blocks_append_in_order() -> None:
    assert _parse_chunks(["A<canvas>one</canvas><canvas>two</canvas>C"]) == (
        "AC",
        "onetwo",
        False,
    )


def test_unterminated_canvas_block_flush_signals_rollback() -> None:
    parser = CanvasStreamParser()

    events = parser.feed("Chat <canvas>draft")
    flush_events = parser.flush()

    assert events.chat_text == "Chat "
    assert events.canvas_text == "draft"
    assert flush_events.unterminated_canvas is True
    assert flush_events.chat_text == ""
    assert flush_events.canvas_text == ""


def test_single_character_tag_prefix_is_held_until_flush() -> None:
    parser = CanvasStreamParser()

    events = parser.feed("<")
    flush_events = parser.flush()

    assert events.chat_text == ""
    assert events.canvas_text == ""
    assert flush_events.chat_text == "<"
    assert flush_events.unterminated_canvas is False
