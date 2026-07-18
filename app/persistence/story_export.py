"""Readable HTML story ZIP export (scenes as linked chapter pages)."""

from __future__ import annotations

import io
import zipfile
from html import escape

import markdown2

from app.world.models import Scene, World

MARKDOWN_EXTRAS = ["fenced-code-blocks", "tables", "smarty-pants"]

STYLE_CSS = """\
:root {
  color-scheme: light dark;
}
body {
  margin: 0;
  font-family: Georgia, "Times New Roman", serif;
  line-height: 1.6;
  background: #faf9f7;
  color: #1a1a1a;
}
main {
  max-width: 42rem;
  margin: 0 auto;
  padding: 2rem 1.25rem 4rem;
}
header.site {
  margin-bottom: 1.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #ddd;
}
header.site .story-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: normal;
  color: #666;
  letter-spacing: 0.02em;
}
h1 {
  font-size: 1.75rem;
  line-height: 1.25;
  margin: 0 0 1rem;
}
.summary {
  color: #444;
  font-style: italic;
  margin: 0 0 1.5rem;
}
.chapter-list {
  list-style: none;
  padding: 0;
  margin: 1.5rem 0 0;
}
.chapter-list li {
  margin: 0 0 1.25rem;
  padding-bottom: 1.25rem;
  border-bottom: 1px solid #eee;
}
.chapter-list a {
  color: #1a3a5c;
  text-decoration: none;
  font-size: 1.15rem;
  font-weight: bold;
}
.chapter-list a:hover {
  text-decoration: underline;
}
.chapter-list .chapter-summary {
  margin: 0.35rem 0 0;
  color: #555;
  font-size: 0.95rem;
}
.nav {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin: 2rem 0 1.5rem;
  padding: 0.75rem 0;
  border-top: 1px solid #ddd;
  border-bottom: 1px solid #ddd;
  font-family: system-ui, sans-serif;
  font-size: 0.9rem;
}
.nav a {
  color: #1a3a5c;
  text-decoration: none;
}
.nav a:hover {
  text-decoration: underline;
}
.nav .spacer {
  flex: 1;
}
.prose p {
  margin: 0 0 1em;
}
.prose h1, .prose h2, .prose h3 {
  margin: 1.5em 0 0.5em;
}
.description {
  color: #444;
  margin: 0 0 1rem;
}
.empty {
  color: #666;
  font-style: italic;
}
@media (prefers-color-scheme: dark) {
  body {
    background: #1a1a1a;
    color: #e8e6e3;
  }
  header.site {
    border-bottom-color: #333;
  }
  header.site .story-title {
    color: #999;
  }
  .summary, .description, .empty {
    color: #aaa;
  }
  .chapter-list li {
    border-bottom-color: #333;
  }
  .chapter-list a, .nav a {
    color: #8cb4e8;
  }
  .chapter-list .chapter-summary {
    color: #aaa;
  }
  .nav {
    border-top-color: #333;
    border-bottom-color: #333;
  }
}
"""


def scene_page_name(index: int) -> str:
    """Return the zero-padded HTML filename for a 1-based scene position."""
    return f"scene_{index:03d}.html"


def _markdown_to_html(markdown: str) -> str:
    return markdown2.markdown(markdown or "", extras=MARKDOWN_EXTRAS)


def _page_shell(*, title: str, story_title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{escape(title)}</title>\n"
        '  <link rel="stylesheet" href="style.css">\n'
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        '    <header class="site">\n'
        f'      <p class="story-title">{escape(story_title)}</p>\n'
        "    </header>\n"
        f"{body}"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def _nav_html(*, prev_href: str | None, next_href: str | None) -> str:
    parts = ['    <nav class="nav">\n']
    if prev_href:
        parts.append(f'      <a href="{escape(prev_href, quote=True)}">← Previous</a>\n')
    else:
        parts.append("      <span></span>\n")
    parts.append('      <a href="index.html">Index</a>\n')
    if next_href:
        parts.append(f'      <a href="{escape(next_href, quote=True)}">Next →</a>\n')
    else:
        parts.append("      <span></span>\n")
    parts.append("    </nav>\n")
    return "".join(parts)


def _render_index(world: World) -> str:
    story_title = world.metadata.title or "Untitled Story"
    description = world.metadata.description.strip()
    chapters: list[str] = []
    for i, scene in enumerate(world.scenes, start=1):
        href = scene_page_name(i)
        title = scene.title or f"Scene {i}"
        summary = scene.summary.strip()
        summary_html = (
            f'        <p class="chapter-summary">{escape(summary)}</p>\n' if summary else ""
        )
        chapters.append(
            "      <li>\n"
            f'        <a href="{escape(href, quote=True)}">{escape(title)}</a>\n'
            f"{summary_html}"
            "      </li>\n"
        )

    if chapters:
        chapter_block = '    <ol class="chapter-list">\n' + "".join(chapters) + "    </ol>\n"
    else:
        chapter_block = '    <p class="empty">This story has no scenes yet.</p>\n'

    description_block = (
        f'    <p class="description">{escape(description)}</p>\n' if description else ""
    )
    body = f"    <h1>{escape(story_title)}</h1>\n{description_block}{chapter_block}"
    return _page_shell(title=story_title, story_title=story_title, body=body)


def _render_scene_page(
    *,
    world: World,
    scene: Scene,
    index: int,
    total: int,
) -> str:
    story_title = world.metadata.title or "Untitled Story"
    scene_title = scene.title or f"Scene {index}"
    page_title = f"{scene_title} — {story_title}"
    prev_href = scene_page_name(index - 1) if index > 1 else None
    next_href = scene_page_name(index + 1) if index < total else None
    summary = scene.summary.strip()
    summary_block = f'    <p class="summary">{escape(summary)}</p>\n' if summary else ""
    prose = _markdown_to_html(scene.markdown)
    body = (
        f"{_nav_html(prev_href=prev_href, next_href=next_href)}"
        f"    <h1>{escape(scene_title)}</h1>\n"
        f"{summary_block}"
        f'    <div class="prose">\n{prose}\n    </div>\n'
        f"{_nav_html(prev_href=prev_href, next_href=next_href)}"
    )
    return _page_shell(title=page_title, story_title=story_title, body=body)


def export_story_zip(world: World) -> bytes:
    """Render scenes as linked HTML pages and return a ZIP archive.

    Layout::

        story.zip
        |-- index.html
        |-- style.css
        |-- scene_001.html
        `-- ...

    Each scene is treated as a chapter. Export is read-only; the live world is
    not mutated. There is no corresponding import path.
    """

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("style.css", STYLE_CSS)
        archive.writestr("index.html", _render_index(world))
        total = len(world.scenes)
        for i, scene in enumerate(world.scenes, start=1):
            archive.writestr(
                scene_page_name(i),
                _render_scene_page(world=world, scene=scene, index=i, total=total),
            )
    return buffer.getvalue()
