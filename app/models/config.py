"""Model configuration values and graph-node registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.models.settings import DEFAULT_MODEL

ReasoningEffort = Literal["low", "medium", "high"]

SMALL_CONFIG_ID = "small"
STANDARD_CONFIG_ID = "standard"
LARGE_CONFIG_ID = "large"
CHAT_NODE_ID = "chat"
SCENE_STANCES_NODE_ID = "scene_stances"
SCENE_OUTLINE_NODE_ID = "scene_outline"
SCENE_OUTLINE_REVIEW_NODE_ID = "scene_outline_review"
SCENE_OUTLINE_REVISE_NODE_ID = "scene_outline_revise"
SCENE_DRAFT_NODE_ID = "scene_draft"
SCENE_SUMMARY_NODE_ID = "scene_summary"


class ModelConfig(BaseModel):
    """User-editable model profile for one or more graph nodes."""

    id: str
    name: str
    model: str
    temperature: float | None = None
    reasoning_effort: ReasoningEffort | None = None
    system_prompt_prefix: str = ""


@dataclass(frozen=True)
class GraphNode:
    """Registry entry for a LangGraph node that can select a model config."""

    node_id: str
    label: str
    default_config_id: str


DEFAULT_MODEL_CONFIGS: tuple[ModelConfig, ...] = (
    ModelConfig(
        id=SMALL_CONFIG_ID,
        name="Small",
        model="openai/gpt-4o-mini",
    ),
    ModelConfig(
        id=STANDARD_CONFIG_ID,
        name="Standard",
        model=DEFAULT_MODEL,
    ),
    ModelConfig(
        id=LARGE_CONFIG_ID,
        name="Large",
        model="anthropic/claude-3.5-sonnet",
    ),
)

DEFAULT_MODEL_CONFIG_IDS = frozenset(config.id for config in DEFAULT_MODEL_CONFIGS)
DEFAULT_MODEL_CONFIG_MAP = {config.id: config for config in DEFAULT_MODEL_CONFIGS}

GRAPH_NODES: tuple[GraphNode, ...] = (
    GraphNode(CHAT_NODE_ID, "Chat Agent", default_config_id=STANDARD_CONFIG_ID),
    GraphNode(SCENE_STANCES_NODE_ID, "Scene: Author Stances", default_config_id=STANDARD_CONFIG_ID),
    GraphNode(SCENE_OUTLINE_NODE_ID, "Scene: Outline", default_config_id=STANDARD_CONFIG_ID),
    GraphNode(
        SCENE_OUTLINE_REVIEW_NODE_ID,
        "Scene: Review Outline",
        default_config_id=SMALL_CONFIG_ID,
    ),
    GraphNode(
        SCENE_OUTLINE_REVISE_NODE_ID,
        "Scene: Revise Outline",
        default_config_id=STANDARD_CONFIG_ID,
    ),
    GraphNode(SCENE_DRAFT_NODE_ID, "Scene: Draft Prose", default_config_id=LARGE_CONFIG_ID),
    GraphNode(
        SCENE_SUMMARY_NODE_ID,
        "Scene: Summary",
        default_config_id=SMALL_CONFIG_ID,
    ),
)
GRAPH_NODE_MAP = {node.node_id: node for node in GRAPH_NODES}


def get_graph_node(node_id: str) -> GraphNode | None:
    """Return the registered graph node, if known."""

    return GRAPH_NODE_MAP.get(node_id)


def get_default_model_config(config_id: str) -> ModelConfig | None:
    """Return a built-in model config by id, if one exists."""

    return DEFAULT_MODEL_CONFIG_MAP.get(config_id)


def resolve_default_model_config(node_id: str) -> ModelConfig:
    """Resolve registry default, then the standard config as the final fallback."""

    node = get_graph_node(node_id)
    if node is not None:
        config = get_default_model_config(node.default_config_id)
        if config is not None:
            return config
    return DEFAULT_MODEL_CONFIG_MAP[STANDARD_CONFIG_ID]
