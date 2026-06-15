"""Unit tests for model configuration persistence."""

from app.models.config import CHAT_NODE_ID, STANDARD_CONFIG_ID, ModelConfig
from app.persistence import JsonFileModelConfigStore, ModelConfigRepository
from app.persistence.model_configs import _default_selections


def test_load_missing_model_config_file_returns_defaults(tmp_path) -> None:
    store = JsonFileModelConfigStore(tmp_path / "model_configs.json")

    state = store.load()

    assert {config.id for config in state.configs} == {"small", "standard", "large"}
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

    assert repo.resolve_model_config(CHAT_NODE_ID).id == STANDARD_CONFIG_ID

    repo.save_config(custom)
    repo.set_selection(CHAT_NODE_ID, custom.id)
    assert repo.resolve_model_config(CHAT_NODE_ID).id == custom.id

    repo.delete_config(custom.id)
    assert repo.resolve_model_config(CHAT_NODE_ID).id == STANDARD_CONFIG_ID


def test_delete_default_config_resets_it_to_builtin(tmp_path) -> None:
    repo = ModelConfigRepository(JsonFileModelConfigStore(tmp_path / "model_configs.json"))
    edited_standard = ModelConfig(
        id=STANDARD_CONFIG_ID,
        name="Edited Standard",
        model="example/edited",
    )

    repo.save_config(edited_standard)
    assert repo.get_config(STANDARD_CONFIG_ID) == edited_standard

    repo.delete_config(STANDARD_CONFIG_ID)

    assert repo.get_config(STANDARD_CONFIG_ID) != edited_standard
    assert repo.resolve_model_config(CHAT_NODE_ID).id == STANDARD_CONFIG_ID
