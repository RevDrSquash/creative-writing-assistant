"""Unit tests for model configuration defaults and registry."""

from app.models.config import (
    CHAT_NODE_ID,
    DEFAULT_MODEL_CONFIGS,
    GRAPH_NODES,
    SCENE_DRAFT_NODE_ID,
    SCENE_OUTLINE_NODE_ID,
    SCENE_OUTLINE_REVIEW_NODE_ID,
    SCENE_OUTLINE_REVISE_NODE_ID,
    SCENE_PROSE_REVIEW_NODE_ID,
    SCENE_PROSE_REVISE_NODE_ID,
    SCENE_STANCES_NODE_ID,
    SCENE_SUMMARY_NODE_ID,
    SMALL_CONFIG_ID,
    STANDARD_CONFIG_ID,
    resolve_default_model_config,
)
from app.models.settings import DEFAULT_MODEL


def test_default_model_configs_include_required_roles() -> None:
    configs_by_id = {config.id: config for config in DEFAULT_MODEL_CONFIGS}

    assert set(configs_by_id) == {"small", "standard", "large"}
    assert configs_by_id[STANDARD_CONFIG_ID].model == DEFAULT_MODEL


def test_graph_nodes_register_chat_node_default() -> None:
    chat_node = next(node for node in GRAPH_NODES if node.node_id == CHAT_NODE_ID)

    assert chat_node.label == "Chat Agent"
    assert chat_node.default_config_id == STANDARD_CONFIG_ID


def test_graph_nodes_register_scene_workflow_nodes() -> None:
    scene_nodes = {
        SCENE_STANCES_NODE_ID,
        SCENE_OUTLINE_NODE_ID,
        SCENE_OUTLINE_REVIEW_NODE_ID,
        SCENE_OUTLINE_REVISE_NODE_ID,
        SCENE_DRAFT_NODE_ID,
        SCENE_PROSE_REVIEW_NODE_ID,
        SCENE_PROSE_REVISE_NODE_ID,
        SCENE_SUMMARY_NODE_ID,
    }
    node_map = {node.node_id: node for node in GRAPH_NODES}
    assert scene_nodes <= set(node_map)
    assert node_map[SCENE_STANCES_NODE_ID].default_config_id == STANDARD_CONFIG_ID
    assert node_map[SCENE_OUTLINE_REVIEW_NODE_ID].default_config_id == SMALL_CONFIG_ID
    assert node_map[SCENE_OUTLINE_REVIEW_NODE_ID].label == "Scene: Review Plan"
    assert node_map[SCENE_OUTLINE_REVISE_NODE_ID].label == "Scene: Revise Plan"
    assert node_map[SCENE_DRAFT_NODE_ID].default_config_id == "large"
    assert node_map[SCENE_PROSE_REVIEW_NODE_ID].default_config_id == SMALL_CONFIG_ID
    assert node_map[SCENE_PROSE_REVISE_NODE_ID].default_config_id == "large"


def test_resolve_default_model_config_uses_standard_for_unknown_nodes() -> None:
    assert resolve_default_model_config("unknown").id == STANDARD_CONFIG_ID
