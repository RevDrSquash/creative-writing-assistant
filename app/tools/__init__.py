"""Agent tools for reading, searching, creating, and editing world content."""

from app.tools.scene import (
    SCENE_TOOLS,
    delete_scene,
    list_scenes,
    propose_scene,
    read_scene,
    read_scene_blueprint,
    select_scene,
    update_scene_blueprint,
)
from app.tools.story_bible import (
    STORY_BIBLE_TOOLS,
    read_character,
    read_event,
    read_story_bible,
    read_timeline,
    read_world_fact,
    read_world_state,
)

READ_ONLY_WRITING_TOOLS = [
    read_scene,
    read_scene_blueprint,
    list_scenes,
    read_story_bible,
    read_world_fact,
    read_character,
    read_timeline,
    read_event,
    read_world_state,
]

WRITING_TOOLS = [*SCENE_TOOLS, *STORY_BIBLE_TOOLS]

__all__ = [
    "READ_ONLY_WRITING_TOOLS",
    "SCENE_TOOLS",
    "STORY_BIBLE_TOOLS",
    "WRITING_TOOLS",
    "delete_scene",
    "list_scenes",
    "propose_scene",
    "read_scene",
    "read_scene_blueprint",
    "select_scene",
    "update_scene_blueprint",
]
