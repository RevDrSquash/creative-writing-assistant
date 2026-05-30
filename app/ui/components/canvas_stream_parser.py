"""Streaming parser for assistant text that contains canvas append blocks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

OPEN_TAG = "<canvas>"
CLOSE_TAG = "</canvas>"


@dataclass(frozen=True)
class ParseEvents:
    """Text fragments that are safe to emit after parsing a stream chunk."""

    chat_text: str = ""
    canvas_text: str = ""
    unterminated_canvas: bool = False


class _ParserState(Enum):
    OUTSIDE = "outside"
    INSIDE = "inside"


class CanvasStreamParser:
    """Separate chat text from ``<canvas>`` append text in token streams."""

    def __init__(self) -> None:
        self._state = _ParserState.OUTSIDE
        self._pending = ""

    def feed(self, text: str) -> ParseEvents:
        """Parse one token chunk and return safe-to-emit text fragments."""

        self._pending += text
        chat_parts: list[str] = []
        canvas_parts: list[str] = []

        while self._pending:
            if self._state is _ParserState.OUTSIDE:
                if self._consume_until_tag(OPEN_TAG, chat_parts):
                    self._state = _ParserState.INSIDE
                    continue
                break

            if self._consume_until_tag(CLOSE_TAG, canvas_parts):
                self._state = _ParserState.OUTSIDE
                continue
            break

        return ParseEvents(chat_text="".join(chat_parts), canvas_text="".join(canvas_parts))

    def flush(self) -> ParseEvents:
        """Drain pending chat text or signal that a canvas block was unterminated."""

        if self._state is _ParserState.INSIDE:
            self._pending = ""
            self._state = _ParserState.OUTSIDE
            return ParseEvents(unterminated_canvas=True)

        chat_text = self._pending
        self._pending = ""
        return ParseEvents(chat_text=chat_text)

    def _consume_until_tag(self, tag: str, output_parts: list[str]) -> bool:
        tag_index = self._pending.find(tag)
        if tag_index >= 0:
            output_parts.append(self._pending[:tag_index])
            self._pending = self._pending[tag_index + len(tag) :]
            return True

        hold_length = _partial_tag_suffix_length(self._pending, tag)
        if hold_length:
            output_parts.append(self._pending[:-hold_length])
            self._pending = self._pending[-hold_length:]
        else:
            output_parts.append(self._pending)
            self._pending = ""
        return False


def _partial_tag_suffix_length(text: str, tag: str) -> int:
    max_length = min(len(text), len(tag) - 1)
    for length in range(max_length, 0, -1):
        if tag.startswith(text[-length:]):
            return length
    return 0
