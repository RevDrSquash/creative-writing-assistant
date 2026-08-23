"""Unit tests for model configuration defaults and registry."""

from app.models.config import (
    CHAT_NODE_ID,
    DEFAULT_MODEL_CONFIGS,
    GRAPH_NODES,
    INTIMACY_ANALYZE_NODE_ID,
    INTIMACY_REVIEW_NODE_ID,
    JUDGMENT_CONFIG_ID,
    ORCHESTRATION_CONFIG_ID,
    SCENE_CHARACTER_REVIEW_NODE_ID,
    SCENE_DRAFT_NODE_ID,
    SCENE_GATHER_NODE_ID,
    SCENE_OUTLINE_NODE_ID,
    SCENE_OUTLINE_REVIEW_NODE_ID,
    SCENE_OUTLINE_REVISE_NODE_ID,
    SCENE_PROSE_REVIEW_NODE_ID,
    SCENE_PROSE_REVISE_NODE_ID,
    SCENE_STANCES_NODE_ID,
    SCENE_SUMMARY_NODE_ID,
    STRUCTURE_CONFIG_ID,
    WRITING_CONFIG_ID,
    resolve_default_model_config,
)
from app.models.settings import DEFAULT_MODEL


def test_default_model_configs_include_required_roles() -> None:
    configs_by_id = {config.id: config for config in DEFAULT_MODEL_CONFIGS}

    assert set(configs_by_id) == {"orchestration", "writing", "judgment", "structure"}
    assert configs_by_id[ORCHESTRATION_CONFIG_ID].model == DEFAULT_MODEL


def test_default_model_configs_set_role_appropriate_reasoning_effort() -> None:
    configs_by_id = {config.id: config for config in DEFAULT_MODEL_CONFIGS}

    assert configs_by_id[ORCHESTRATION_CONFIG_ID].reasoning_effort == "medium"
    assert configs_by_id[JUDGMENT_CONFIG_ID].reasoning_effort == "medium"
    assert configs_by_id[WRITING_CONFIG_ID].reasoning_effort == "low"
    assert configs_by_id[STRUCTURE_CONFIG_ID].reasoning_effort == "low"
    for config in DEFAULT_MODEL_CONFIGS:
        assert config.max_tokens is None


def test_graph_nodes_register_chat_node_default() -> None:
    chat_node = next(node for node in GRAPH_NODES if node.node_id == CHAT_NODE_ID)

    assert chat_node.label == "Chat Agent"
    assert chat_node.default_config_id == ORCHESTRATION_CONFIG_ID


def test_graph_nodes_register_scene_workflow_nodes() -> None:
    scene_nodes = {
        SCENE_STANCES_NODE_ID,
        SCENE_OUTLINE_NODE_ID,
        SCENE_OUTLINE_REVIEW_NODE_ID,
        SCENE_OUTLINE_REVISE_NODE_ID,
        SCENE_GATHER_NODE_ID,
        SCENE_DRAFT_NODE_ID,
        SCENE_PROSE_REVIEW_NODE_ID,
        SCENE_CHARACTER_REVIEW_NODE_ID,
        SCENE_PROSE_REVISE_NODE_ID,
        SCENE_SUMMARY_NODE_ID,
    }
    node_map = {node.node_id: node for node in GRAPH_NODES}
    assert scene_nodes <= set(node_map)
    assert node_map[SCENE_STANCES_NODE_ID].default_config_id == STRUCTURE_CONFIG_ID
    assert node_map[SCENE_OUTLINE_NODE_ID].default_config_id == STRUCTURE_CONFIG_ID
    assert node_map[SCENE_OUTLINE_REVIEW_NODE_ID].default_config_id == JUDGMENT_CONFIG_ID
    assert node_map[SCENE_OUTLINE_REVIEW_NODE_ID].label == "Scene: Review Plan"
    assert node_map[SCENE_OUTLINE_REVISE_NODE_ID].label == "Scene: Revise Plan"
    assert node_map[SCENE_OUTLINE_REVISE_NODE_ID].default_config_id == JUDGMENT_CONFIG_ID
    assert node_map[SCENE_GATHER_NODE_ID].label == "Scene: Gather Context"
    assert node_map[SCENE_GATHER_NODE_ID].default_config_id == ORCHESTRATION_CONFIG_ID
    assert node_map[SCENE_DRAFT_NODE_ID].default_config_id == WRITING_CONFIG_ID
    assert node_map[SCENE_PROSE_REVIEW_NODE_ID].default_config_id == JUDGMENT_CONFIG_ID
    assert node_map[SCENE_CHARACTER_REVIEW_NODE_ID].default_config_id == JUDGMENT_CONFIG_ID
    assert node_map[SCENE_CHARACTER_REVIEW_NODE_ID].label == "Scene: Character Review"
    assert node_map[SCENE_PROSE_REVISE_NODE_ID].default_config_id == JUDGMENT_CONFIG_ID
    assert node_map[SCENE_SUMMARY_NODE_ID].default_config_id == STRUCTURE_CONFIG_ID

    # Gather sits between revise plan and draft in the UI registry order.
    node_ids = [node.node_id for node in GRAPH_NODES]
    assert node_ids.index(SCENE_GATHER_NODE_ID) == node_ids.index(SCENE_OUTLINE_REVISE_NODE_ID) + 1
    assert node_ids.index(SCENE_DRAFT_NODE_ID) == node_ids.index(SCENE_GATHER_NODE_ID) + 1


def test_graph_nodes_register_intimacy_workflow_nodes() -> None:
    node_map = {node.node_id: node for node in GRAPH_NODES}
    assert node_map[INTIMACY_ANALYZE_NODE_ID].default_config_id == JUDGMENT_CONFIG_ID
    assert node_map[INTIMACY_ANALYZE_NODE_ID].label == "Intimacy: Analyze"
    assert node_map[INTIMACY_REVIEW_NODE_ID].default_config_id == JUDGMENT_CONFIG_ID
    assert node_map[INTIMACY_REVIEW_NODE_ID].label == "Intimacy: Review"


def test_resolve_default_model_config_uses_orchestration_for_unknown_nodes() -> None:
    assert resolve_default_model_config("unknown").id == ORCHESTRATION_CONFIG_ID
