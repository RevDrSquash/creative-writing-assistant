"""Model configuration values and graph-node registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.models.settings import DEFAULT_MODEL

# OpenRouter's unified reasoning effort levels. Older Anthropic models map these to a
# thinking token budget; Claude 4.6+ maps them to output_config.effort under adaptive
# thinking, where "xhigh" and "max" become meaningful (older models fall back to "high").
ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh", "max"]

# Role-oriented default configs. Each role captures a requirement profile (see
# docs/model_selection_analysis.md), not a model size: nodes default to the role whose
# requirements they share, and swapping a role's model retunes every node of that role.
ORCHESTRATION_CONFIG_ID = "orchestration"
WRITING_CONFIG_ID = "writing"
JUDGMENT_CONFIG_ID = "judgment"
STRUCTURE_CONFIG_ID = "structure"
CHAT_NODE_ID = "chat"
SCENE_STANCES_NODE_ID = "scene_stances"
SCENE_OUTLINE_NODE_ID = "scene_outline"
SCENE_OUTLINE_REVIEW_NODE_ID = "scene_outline_review"
SCENE_OUTLINE_REVISE_NODE_ID = "scene_outline_revise"
SCENE_GATHER_NODE_ID = "scene_gather"
SCENE_DRAFT_NODE_ID = "scene_draft"
SCENE_PROSE_REVIEW_NODE_ID = "scene_prose_review"
SCENE_PROSE_REVISE_NODE_ID = "scene_prose_revise"
SCENE_SUMMARY_NODE_ID = "scene_summary"


class ModelConfig(BaseModel):
    """User-editable model profile for one or more graph nodes."""

    id: str
    name: str
    model: str
    temperature: float | None = None
    reasoning_effort: ReasoningEffort | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    system_prompt_prefix: str = ""


@dataclass(frozen=True)
class GraphNode:
    """Registry entry for a LangGraph node that can select a model config."""

    node_id: str
    label: str
    default_config_id: str


DEFAULT_MODEL_CONFIGS: tuple[ModelConfig, ...] = (
    ModelConfig(
        id=ORCHESTRATION_CONFIG_ID,
        name="Orchestration",
        model=DEFAULT_MODEL,
        reasoning_effort="medium",
    ),
    ModelConfig(
        id=WRITING_CONFIG_ID,
        name="Writing",
        model="openai/gpt-5.6-luna",
        reasoning_effort="low",
    ),
    ModelConfig(
        id=JUDGMENT_CONFIG_ID,
        name="Judgment",
        model=DEFAULT_MODEL,
        reasoning_effort="medium",
    ),
    ModelConfig(
        id=STRUCTURE_CONFIG_ID,
        name="Structure",
        model="google/gemini-3.5-flash-lite",
        reasoning_effort="low",
    ),
)

DEFAULT_MODEL_CONFIG_IDS = frozenset(config.id for config in DEFAULT_MODEL_CONFIGS)
DEFAULT_MODEL_CONFIG_MAP = {config.id: config for config in DEFAULT_MODEL_CONFIGS}

GRAPH_NODES: tuple[GraphNode, ...] = (
    GraphNode(CHAT_NODE_ID, "Chat Agent", default_config_id=ORCHESTRATION_CONFIG_ID),
    GraphNode(
        SCENE_STANCES_NODE_ID,
        "Scene: Author Stances",
        default_config_id=STRUCTURE_CONFIG_ID,
    ),
    GraphNode(SCENE_OUTLINE_NODE_ID, "Scene: Outline", default_config_id=STRUCTURE_CONFIG_ID),
    GraphNode(
        SCENE_OUTLINE_REVIEW_NODE_ID,
        "Scene: Review Plan",
        default_config_id=JUDGMENT_CONFIG_ID,
    ),
    GraphNode(
        SCENE_OUTLINE_REVISE_NODE_ID,
        "Scene: Revise Plan",
        default_config_id=JUDGMENT_CONFIG_ID,
    ),
    GraphNode(
        SCENE_GATHER_NODE_ID,
        "Scene: Gather Context",
        default_config_id=ORCHESTRATION_CONFIG_ID,
    ),
    GraphNode(SCENE_DRAFT_NODE_ID, "Scene: Draft Prose", default_config_id=WRITING_CONFIG_ID),
    GraphNode(
        SCENE_PROSE_REVIEW_NODE_ID,
        "Scene: Review Prose",
        default_config_id=JUDGMENT_CONFIG_ID,
    ),
    GraphNode(
        SCENE_PROSE_REVISE_NODE_ID,
        "Scene: Revise Prose",
        default_config_id=JUDGMENT_CONFIG_ID,
    ),
    GraphNode(
        SCENE_SUMMARY_NODE_ID,
        "Scene: Summary",
        default_config_id=STRUCTURE_CONFIG_ID,
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
    """Resolve registry default, then the orchestration config as the final fallback."""

    node = get_graph_node(node_id)
    if node is not None:
        config = get_default_model_config(node.default_config_id)
        if config is not None:
            return config
    return DEFAULT_MODEL_CONFIG_MAP[ORCHESTRATION_CONFIG_ID]
