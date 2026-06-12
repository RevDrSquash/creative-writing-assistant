"""Agent tools for reading, searching, creating, and editing world content."""

from app.tools.scene import (
    SCENE_TOOLS,
    create_scene,
    delete_scene,
    fuzzy_replace_once,
    list_scenes,
    read_scene,
    replace_scene_text,
    select_scene,
)
from app.tools.story_bible import STORY_BIBLE_TOOLS

WRITING_TOOLS = [*SCENE_TOOLS, *STORY_BIBLE_TOOLS]

__all__ = [
    "SCENE_TOOLS",
    "STORY_BIBLE_TOOLS",
    "WRITING_TOOLS",
    "create_scene",
    "delete_scene",
    "fuzzy_replace_once",
    "list_scenes",
    "read_scene",
    "replace_scene_text",
    "select_scene",
]
