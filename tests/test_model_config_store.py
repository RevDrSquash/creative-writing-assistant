"""Unit tests for model configuration persistence."""

import json

import pytest

from app.models.config import CHAT_NODE_ID, ORCHESTRATION_CONFIG_ID, ModelConfig
from app.persistence import (
    JsonFileModelConfigStore,
    ModelConfigRepository,
    StoredModelConfigs,
    export_model_configs_json,
    import_model_configs_json,
)
from app.persistence.model_configs import _default_selections


def test_load_missing_model_config_file_returns_defaults(tmp_path) -> None:
    store = JsonFileModelConfigStore(tmp_path / "model_configs.json")

    state = store.load()

    assert {config.id for config in state.configs} == {
        "orchestration",
        "writing",
        "judgment",
        "structure",
    }
    assert state.selections == _default_selections()


def test_model_config_store_round_trips_configs_and_selections(tmp_path) -> None:
    path = tmp_path / "model_configs.json"
    store = JsonFileModelConfigStore(path)
    repo = ModelConfigRepository(store)
    custom = ModelConfig(
        id="custom",
        name="Custom",
        model="example/custom",
        temperature=0.2,
        reasoning_effort="high",
        system_prompt_prefix="Prefer vivid sensory detail.",
    )

    repo.save_config(custom)
    repo.set_selection(CHAT_NODE_ID, custom.id)

    fresh_repo = ModelConfigRepository(JsonFileModelConfigStore(path))
    assert fresh_repo.get_config(custom.id) == custom
    assert fresh_repo.get_selection(CHAT_NODE_ID) == custom.id


def test_model_config_repository_resolves_override_then_node_default(tmp_path) -> None:
    repo = ModelConfigRepository(JsonFileModelConfigStore(tmp_path / "model_configs.json"))
    custom = ModelConfig(id="custom", name="Custom", model="example/custom")

    assert repo.resolve_model_config(CHAT_NODE_ID).id == ORCHESTRATION_CONFIG_ID

    repo.save_config(custom)
    repo.set_selection(CHAT_NODE_ID, custom.id)
    assert repo.resolve_model_config(CHAT_NODE_ID).id == custom.id

    repo.delete_config(custom.id)
    assert repo.resolve_model_config(CHAT_NODE_ID).id == ORCHESTRATION_CONFIG_ID


def test_delete_default_config_resets_it_to_builtin(tmp_path) -> None:
    repo = ModelConfigRepository(JsonFileModelConfigStore(tmp_path / "model_configs.json"))
    edited_orchestration = ModelConfig(
        id=ORCHESTRATION_CONFIG_ID,
        name="Edited Orchestration",
        model="example/edited",
    )

    repo.save_config(edited_orchestration)
    assert repo.get_config(ORCHESTRATION_CONFIG_ID) == edited_orchestration

    repo.delete_config(ORCHESTRATION_CONFIG_ID)

    assert repo.get_config(ORCHESTRATION_CONFIG_ID) != edited_orchestration
    assert repo.resolve_model_config(CHAT_NODE_ID).id == ORCHESTRATION_CONFIG_ID


def test_export_import_round_trips_configs_and_selections(tmp_path) -> None:
    source_repo = ModelConfigRepository(JsonFileModelConfigStore(tmp_path / "source.json"))
    custom = ModelConfig(
        id="custom",
        name="Custom",
        model="example/custom",
        temperature=0.4,
        reasoning_effort="low",
        system_prompt_prefix="Write tersely.",
    )
    source_repo.save_config(custom)
    source_repo.set_selection(CHAT_NODE_ID, custom.id)

    exported = export_model_configs_json(source_repo.export_state())

    target_repo = ModelConfigRepository(JsonFileModelConfigStore(tmp_path / "target.json"))
    target_repo.replace_state(import_model_configs_json(exported))

    assert target_repo.get_config(custom.id) == custom
    assert target_repo.get_selection(CHAT_NODE_ID) == custom.id


def test_import_replaces_existing_configs(tmp_path) -> None:
    repo = ModelConfigRepository(JsonFileModelConfigStore(tmp_path / "model_configs.json"))
    repo.save_config(ModelConfig(id="stale", name="Stale", model="example/stale"))

    repo.replace_state(StoredModelConfigs())

    assert repo.get_config("stale") is None
    assert {config.id for config in repo.list_configs()} == {
        "orchestration",
        "writing",
        "judgment",
        "structure",
    }


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"\xff\xfe not utf-8 json", "Not valid JSON"),
        (b"{not json", "Not valid JSON"),
        (b'["not", "an", "object"]', "must contain a JSON object"),
        (json.dumps({"configs": [{"id": "broken"}]}).encode("utf-8"), "failed validation"),
    ],
)
def test_import_rejects_malformed_payloads(data: bytes, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        import_model_configs_json(data)


def test_import_drops_dangling_selections_and_keeps_defaults(tmp_path) -> None:
    repo = ModelConfigRepository(JsonFileModelConfigStore(tmp_path / "model_configs.json"))
    payload = json.dumps(
        {
            "configs": [],
            "selections": {
                CHAT_NODE_ID: "no-such-config",
                "no-such-node": ORCHESTRATION_CONFIG_ID,
            },
        }
    ).encode("utf-8")

    repo.replace_state(import_model_configs_json(payload))

    assert {config.id for config in repo.list_configs()} == {
        "orchestration",
        "writing",
        "judgment",
        "structure",
    }
    assert repo.get_selection("no-such-node") is None
    assert repo.get_selection(CHAT_NODE_ID) == ORCHESTRATION_CONFIG_ID
    assert repo.resolve_model_config(CHAT_NODE_ID).id == ORCHESTRATION_CONFIG_ID
