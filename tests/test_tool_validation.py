"""Tests for leaked tool-call markup rejection."""

from __future__ import annotations

import pytest
from langchain_core.tools import ToolException

from app.tools.validation import reject_leaked_tool_markup, reject_leaked_tool_markup_fields


def test_reject_leaked_tool_markup_allows_none_and_plain_prose() -> None:
    assert reject_leaked_tool_markup(None, "themes") is None
    assert reject_leaked_tool_markup("Loyalty, consent, found family.", "themes") == (
        "Loyalty, consent, found family."
    )
    assert reject_leaked_tool_markup("He was <30 and still green.", "tone") == (
        "He was <30 and still green."
    )


def test_reject_leaked_tool_markup_flags_parameter_tags() -> None:
    leaked = 'consent.\n</themes>\n<parameter name="writing_style">Close third.'
    with pytest.raises(ToolException, match="leftover tool-call markup"):
        reject_leaked_tool_markup(leaked, "themes", sibling_fields=("writing_style",))


def test_reject_leaked_tool_markup_flags_sibling_field_tags() -> None:
    with pytest.raises(ToolException, match="leftover tool-call markup"):
        reject_leaked_tool_markup(
            "Noir comedy.</writing_style>",
            "tone",
            sibling_fields=("writing_style",),
        )


def test_reject_leaked_tool_markup_fields_checks_every_sibling() -> None:
    with pytest.raises(ToolException, match="Field 'background'"):
        reject_leaked_tool_markup_fields(
            {
                "name": "Mira",
                "background": 'Reach-born.</parameter>\n<parameter name="voice">Soft.',
                "voice": None,
            }
        )
