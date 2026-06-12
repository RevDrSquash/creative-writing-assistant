"""Smoke tests for Phase 0 package layout."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_PACKAGES = [
    "app",
    "app.ui",
    "app.graphs",
    "app.tools",
    "app.world",
    "app.persistence",
    "app.models",
]


@pytest.mark.parametrize("package_name", EXPECTED_PACKAGES)
def test_package_importable(package_name: str) -> None:
    __import__(package_name)


def test_repo_has_poetry_files() -> None:
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert (REPO_ROOT / "poetry.lock").is_file()
