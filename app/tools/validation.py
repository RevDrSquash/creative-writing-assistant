"""Guards for agent-authored tool arguments.

Models trained on XML function-calling sometimes concatenate later parameters
into an earlier string (``...prose</themes>\\n<parameter name="writing_style">``).
Write tools must reject that markup instead of persisting it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from langchain_core.tools import ToolException

_TOOL_CALL_MARKUP_RE = re.compile(
    r"""
    <\s*/?\s*parameter\b
    | <\s*/?\s*function\b
    | <\s*/?\s*tool_call\b
    | <\s*/?\s*tool_calls\b
    | <\s*/?\s*arguments\b
    | <\s*/?\s*invoke\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def reject_leaked_tool_markup(
    value: str | None,
    field: str,
    *,
    sibling_fields: tuple[str, ...] = (),
) -> str | None:
    """Pass through ``None``; raise ``ToolException`` if *value* has tool-call XML."""

    if value is None:
        return None
    if _TOOL_CALL_MARKUP_RE.search(value):
        raise ToolException(_markup_error(field))
    for name in (field, *sibling_fields):
        if re.search(rf"<\s*/?\s*{re.escape(name)}\s*>", value, re.IGNORECASE):
            raise ToolException(_markup_error(field))
    return value


def reject_leaked_tool_markup_fields(fields: Mapping[str, str | None]) -> None:
    """Reject leaked markup across a set of sibling prose fields."""

    names = tuple(fields)
    for name, value in fields.items():
        reject_leaked_tool_markup(value, name, sibling_fields=names)


def _markup_error(field: str) -> str:
    return (
        f"Field '{field}' contains leftover tool-call markup (XML tags such as "
        f"<parameter name=...> or </{field}>). Each argument is a separate JSON "
        "property containing only that field's plain prose — do not wrap values "
        "in XML, and do not concatenate later fields into this one. Retry with "
        "clean prose for this field and pass other fields as their own arguments."
    )
