"""Persistence facade for model configurations and node selections."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from app.models.config import (
    CHAT_NODE_ID,
    DEFAULT_MODEL_CONFIG_IDS,
    DEFAULT_MODEL_CONFIG_MAP,
    DEFAULT_MODEL_CONFIGS,
    JUDGMENT_CONFIG_ID,
    ORCHESTRATION_CONFIG_ID,
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
    ModelConfig,
    get_graph_node,
)
from app.persistence.paths import get_data_dir

MODEL_CONFIG_FILENAME = "model_configs.json"

_MODEL_CONFIG_REPOSITORY: ModelConfigRepository | None = None


def _default_configs() -> list[ModelConfig]:
    return [config.model_copy(deep=True) for config in DEFAULT_MODEL_CONFIGS]


def _default_selections() -> dict[str, str]:
    return {
        CHAT_NODE_ID: ORCHESTRATION_CONFIG_ID,
        SCENE_STANCES_NODE_ID: STRUCTURE_CONFIG_ID,
        SCENE_OUTLINE_NODE_ID: STRUCTURE_CONFIG_ID,
        SCENE_OUTLINE_REVIEW_NODE_ID: JUDGMENT_CONFIG_ID,
        SCENE_OUTLINE_REVISE_NODE_ID: JUDGMENT_CONFIG_ID,
        SCENE_GATHER_NODE_ID: ORCHESTRATION_CONFIG_ID,
        SCENE_DRAFT_NODE_ID: WRITING_CONFIG_ID,
        SCENE_PROSE_REVIEW_NODE_ID: JUDGMENT_CONFIG_ID,
        SCENE_PROSE_REVISE_NODE_ID: JUDGMENT_CONFIG_ID,
        SCENE_SUMMARY_NODE_ID: STRUCTURE_CONFIG_ID,
    }


class StoredModelConfigs(BaseModel):
    """Serializable model config document."""

    configs: list[ModelConfig] = Field(default_factory=_default_configs)
    selections: dict[str, str] = Field(default_factory=_default_selections)


class ModelConfigStore(Protocol):
    """Minimal persistence API for model configuration state."""

    def load(self) -> StoredModelConfigs:
        """Return persisted configs and selections."""

    def save(self, data: StoredModelConfigs) -> None:
        """Persist configs and selections."""


class JsonFileModelConfigStore:
    """JSON-file-backed model config store."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_data_dir() / MODEL_CONFIG_FILENAME

    def load(self) -> StoredModelConfigs:
        """Load model config state from disk, with defaults always present."""

        if not self.path.exists():
            return _with_defaults(StoredModelConfigs())

        raw = self.path.read_text(encoding="utf-8")
        if not raw.strip():
            return _with_defaults(StoredModelConfigs())

        data = json.loads(raw)
        if not isinstance(data, dict):
            msg = f"Expected model config JSON object at {self.path}"
            raise ValueError(msg)
        return _with_defaults(StoredModelConfigs.model_validate(data))

    def save(self, data: StoredModelConfigs) -> None:
        """Write the full config document atomically."""

        state = _with_defaults(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(state.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, self.path)


class ModelConfigRepository:
    """Facade for model configs, node selections, and resolution."""

    def __init__(self, store: ModelConfigStore | None = None) -> None:
        self.store = store or JsonFileModelConfigStore()

    def list_configs(self) -> list[ModelConfig]:
        """Return all configs, including built-in defaults."""

        return self.store.load().configs

    def get_config(self, config_id: str) -> ModelConfig | None:
        """Return a config by id, if one exists."""

        return _config_map(self.store.load().configs).get(config_id)

    def save_config(self, config: ModelConfig) -> None:
        """Create or update a model config."""

        state = self.store.load()
        configs = _upsert_config(state.configs, config)
        self.store.save(StoredModelConfigs(configs=configs, selections=state.selections))

    def delete_config(self, config_id: str) -> None:
        """Delete a custom config, or reset a default config to its built-in value."""

        state = self.store.load()
        configs_by_id = _config_map(state.configs)
        if config_id in DEFAULT_MODEL_CONFIG_IDS:
            configs_by_id[config_id] = DEFAULT_MODEL_CONFIG_MAP[config_id]
        else:
            configs_by_id.pop(config_id, None)

        selections = {
            node_id: selected_id
            for node_id, selected_id in state.selections.items()
            if selected_id in configs_by_id
        }
        self.store.save(
            StoredModelConfigs(
                configs=_ordered_configs(configs_by_id.values()),
                selections=selections,
            )
        )

    def get_selection(self, node_id: str) -> str | None:
        """Return the persisted config id selected for a node, if any."""

        return self.store.load().selections.get(node_id)

    def set_selection(self, node_id: str, config_id: str) -> None:
        """Persist a node-to-config selection."""

        if get_graph_node(node_id) is None:
            msg = f"Unknown graph node: {node_id}"
            raise ValueError(msg)
        state = self.store.load()
        if config_id not in _config_map(state.configs):
            msg = f"Unknown model config: {config_id}"
            raise ValueError(msg)

        selections = dict(state.selections)
        selections[node_id] = config_id
        self.store.save(StoredModelConfigs(configs=state.configs, selections=selections))

    def resolve_model_config(self, node_id: str) -> ModelConfig:
        """Resolve selected config, then node default, then standard."""

        state = self.store.load()
        configs_by_id = _config_map(state.configs)
        selected_id = state.selections.get(node_id)
        if selected_id in configs_by_id:
            return configs_by_id[selected_id]

        node = get_graph_node(node_id)
        if node is not None and node.default_config_id in configs_by_id:
            return configs_by_id[node.default_config_id]

        return configs_by_id[ORCHESTRATION_CONFIG_ID]

    def export_state(self) -> StoredModelConfigs:
        """Return the full persisted document (defaults-normalized) for export."""

        return self.store.load()

    def replace_state(self, state: StoredModelConfigs) -> None:
        """Replace the persisted document, dropping dangling selections."""

        normalized = _with_defaults(state)
        configs_by_id = _config_map(normalized.configs)
        selections = {
            node_id: selected_id
            for node_id, selected_id in normalized.selections.items()
            if get_graph_node(node_id) is not None and selected_id in configs_by_id
        }
        self.store.save(StoredModelConfigs(configs=normalized.configs, selections=selections))


def export_model_configs_json(state: StoredModelConfigs) -> bytes:
    """Serialize a model config document to JSON bytes for download."""

    return (json.dumps(state.model_dump(mode="json"), indent=2) + "\n").encode("utf-8")


def import_model_configs_json(data: bytes) -> StoredModelConfigs:
    """Parse JSON bytes into a config document; raises ``ValueError`` on invalid input."""

    try:
        payload = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"Not valid JSON: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(payload, dict):
        msg = "Model config JSON must contain a JSON object."
        raise ValueError(msg)

    try:
        return StoredModelConfigs.model_validate(payload)
    except ValidationError as exc:
        msg = f"Model config JSON failed validation: {exc}"
        raise ValueError(msg) from exc


def get_model_config_repository() -> ModelConfigRepository:
    """Return the process-local model config repository singleton."""

    global _MODEL_CONFIG_REPOSITORY

    if _MODEL_CONFIG_REPOSITORY is None:
        _MODEL_CONFIG_REPOSITORY = ModelConfigRepository()
    return _MODEL_CONFIG_REPOSITORY


def reset_model_config_repository() -> None:
    """Drop the cached repository so the next access rebinds to the data dir (tests)."""

    global _MODEL_CONFIG_REPOSITORY

    _MODEL_CONFIG_REPOSITORY = None


def _with_defaults(data: StoredModelConfigs) -> StoredModelConfigs:
    configs_by_id = dict(DEFAULT_MODEL_CONFIG_MAP)
    configs_by_id.update(_config_map(data.configs))

    selections = _default_selections()
    selections.update(data.selections)
    return StoredModelConfigs(
        configs=_ordered_configs(configs_by_id.values()),
        selections=selections,
    )


def _config_map(configs: Sequence[ModelConfig]) -> dict[str, ModelConfig]:
    return {config.id: config for config in configs}


def _upsert_config(configs: Sequence[ModelConfig], config: ModelConfig) -> list[ModelConfig]:
    configs_by_id = _config_map(configs)
    configs_by_id[config.id] = config
    return _ordered_configs(configs_by_id.values())


def _ordered_configs(configs: Sequence[ModelConfig]) -> list[ModelConfig]:
    configs_by_id = _config_map(configs)
    ordered = [
        configs_by_id[default_config.id]
        for default_config in DEFAULT_MODEL_CONFIGS
        if default_config.id in configs_by_id
    ]
    ordered.extend(
        sorted(
            (
                config
                for config_id, config in configs_by_id.items()
                if config_id not in DEFAULT_MODEL_CONFIG_IDS
            ),
            key=lambda config: config.name.lower(),
        )
    )
    return ordered
