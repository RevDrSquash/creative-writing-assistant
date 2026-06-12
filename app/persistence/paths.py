"""Shared filesystem locations for local persistence."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR_ENV_VAR = "WRITING_AGENT_DATA_DIR"


def get_data_dir() -> Path:
    """Return the directory for local JSON stores.

    Defaults to ``<repo>/data``. The ``WRITING_AGENT_DATA_DIR`` environment
    variable overrides it, which tests use to isolate persistence from the
    developer's real data.
    """

    override = os.environ.get(DATA_DIR_ENV_VAR)
    if override:
        return Path(override)
    return REPO_ROOT / "data"
