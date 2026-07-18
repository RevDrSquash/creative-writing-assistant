"""Tests for readable HTML story ZIP export."""

from __future__ import annotations

import io
import zipfile

from app.persistence.story_export import export_story_zip, scene_page_name
from app.persistence.world import default_world
from app.world.models import Scene


def _sample_world():
    world = default_world()
    world.metadata.title = "Zip Story"
    world.metadata.description = "A short adventure."
    world.scenes.clear()
    world.scenes.append(
        Scene(
            title="Chapter One",
            summary="The beginning.",
            markdown="# One\n\nProse **here**.",
        )
    )
    world.scenes.append(
        Scene(
            title="Chapter Two",
            summary="The middle.",
            markdown="## Two\n\nMore prose.",
        )
    )
    world.scenes.append(
        Scene(
            title="Chapter Three",
            summary="",
            markdown="The end.",
        )
    )
    return world


def test_export_story_zip_layout() -> None:
    world = _sample_world()

    data = export_story_zip(world)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert "index.html" in names
        assert "style.css" in names
        assert scene_page_name(1) in names
        assert scene_page_name(2) in names
        assert scene_page_name(3) in names
        assert len([n for n in names if n.startswith("scene_")]) == 3

    # Exporting must not mutate the live world.
    assert world.scenes[0].markdown == "# One\n\nProse **here**."


def test_index_contains_titles_summaries_and_links() -> None:
    world = _sample_world()

    with zipfile.ZipFile(io.BytesIO(export_story_zip(world))) as archive:
        index = archive.read("index.html").decode("utf-8")

    assert "Zip Story" in index
    assert "A short adventure." in index
    assert "Chapter One" in index
    assert "The beginning." in index
    assert "Chapter Two" in index
    assert 'href="scene_001.html"' in index
    assert 'href="scene_002.html"' in index
    assert 'href="scene_003.html"' in index


def test_scene_pages_render_markdown_and_nav_links() -> None:
    world = _sample_world()

    with zipfile.ZipFile(io.BytesIO(export_story_zip(world))) as archive:
        first = archive.read(scene_page_name(1)).decode("utf-8")
        middle = archive.read(scene_page_name(2)).decode("utf-8")
        last = archive.read(scene_page_name(3)).decode("utf-8")

    assert "<h1>One</h1>" in first
    assert "<strong>here</strong>" in first
    assert 'href="index.html"' in first
    assert "Previous" not in first
    assert 'href="scene_002.html"' in first
    assert "Next" in first

    assert 'href="scene_001.html"' in middle
    assert 'href="scene_003.html"' in middle
    assert 'href="index.html"' in middle
    assert "Previous" in middle
    assert "Next" in middle

    assert 'href="scene_002.html"' in last
    assert "Previous" in last
    assert "Next" not in last
    assert 'href="index.html"' in last


def test_html_special_characters_are_escaped() -> None:
    world = default_world()
    world.metadata.title = "Tom & Jerry <edit>"
    world.metadata.description = "A & B <C>"
    world.scenes.clear()
    world.scenes.append(
        Scene(
            title="Scene <One> & Two",
            summary="Less < more & equal",
            markdown="Plain text.",
        )
    )

    with zipfile.ZipFile(io.BytesIO(export_story_zip(world))) as archive:
        index = archive.read("index.html").decode("utf-8")
        scene = archive.read(scene_page_name(1)).decode("utf-8")

    assert "Tom &amp; Jerry &lt;edit&gt;" in index
    assert "A &amp; B &lt;C&gt;" in index
    assert "Scene &lt;One&gt; &amp; Two" in index
    assert "Less &lt; more &amp; equal" in index
    assert "Scene &lt;One&gt; &amp; Two" in scene
    assert "<edit>" not in index
    assert "Tom & Jerry" not in index


def test_empty_world_exports_valid_index() -> None:
    world = default_world()
    world.metadata.title = "Empty"
    world.scenes.clear()

    data = export_story_zip(world)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert names == {"index.html", "style.css"}
        index = archive.read("index.html").decode("utf-8")
        assert "Empty" in index
        assert "no scenes" in index.lower()
