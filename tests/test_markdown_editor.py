"""Tests for the reusable Markdown editor component."""

from collections.abc import Callable
from typing import TypeVar

from nicegui import binding, ui
from nicegui.element import Element
from nicegui.elements.button import Button
from nicegui.elements.column import Column
from nicegui.elements.expansion import Expansion
from nicegui.elements.markdown import Markdown
from nicegui.elements.textarea import Textarea

from app.ui.components import render_markdown_editor
from app.ui.components.story_bible_forms import render_scene_blueprint_form
from app.world.scene import DEFAULT_SCENE_MARKDOWN, create_scene

ElementT = TypeVar("ElementT", bound=Element)


def test_markdown_editor_is_exported() -> None:
    assert callable(render_markdown_editor)


def test_markdown_editor_binding_round_trips() -> None:
    target = {"body": "# Initial"}

    elements = _render_new_elements(lambda: render_markdown_editor(target, "body"))
    textarea = _only_element(elements, Textarea)
    markdown = _only_element(elements, Markdown)

    assert textarea.value == "# Initial"
    assert markdown.content == "# Initial"

    textarea.set_value("## Edited")

    assert target["body"] == "## Edited"
    assert markdown.content == "## Edited"

    target["body"] = "**External edit**"
    binding._refresh_step()

    assert textarea.value == "**External edit**"
    assert markdown.content == "**External edit**"


def test_default_scene_markdown_is_non_empty() -> None:
    assert DEFAULT_SCENE_MARKDOWN.strip()


def test_markdown_editor_shared_state_without_toggle() -> None:
    target = {"body": "# Shared"}
    edit_state = {"edit_mode": True}

    elements = _render_new_elements(
        lambda: render_markdown_editor(
            target,
            "body",
            state=edit_state,
            show_toggle=False,
        )
    )
    textarea = _only_element(elements, Textarea)
    buttons = [element for element in elements if isinstance(element, Button)]

    assert buttons == []
    assert textarea.visible is True

    edit_state["edit_mode"] = False
    binding._refresh_step()

    assert textarea.visible is False


def test_markdown_editor_min_height_class() -> None:
    target = {"body": "# Initial"}

    elements = _render_new_elements(
        lambda: render_markdown_editor(target, "body", min_height="min-h-[24rem]")
    )
    columns = [element for element in elements if isinstance(element, Column)]
    assert any("min-h-[24rem]" in column.classes for column in columns)


def test_scene_blueprint_expansions_collapsed_by_default(isolated_world) -> None:
    scene = create_scene()
    edit_state = {"edit_mode": True}

    elements = _render_new_elements(lambda: render_scene_blueprint_form(scene, edit_state))
    expansions = [element for element in elements if isinstance(element, Expansion)]
    titles = {expansion.text for expansion in expansions}
    assert titles == {"Blueprint", "Linked Events", "Outline", "Character Stances"}
    assert all(expansion.value is False for expansion in expansions)


def _render_new_elements(render: Callable[[], None]) -> list[Element]:
    before_ids = set(ui.context.client.elements)

    render()

    return [
        element
        for element_id, element in ui.context.client.elements.items()
        if element_id not in before_ids
    ]


def _only_element(elements: list[Element], element_type: type[ElementT]) -> ElementT:
    matches = [element for element in elements if isinstance(element, element_type)]
    assert len(matches) == 1
    return matches[0]
