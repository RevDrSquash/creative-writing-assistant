"""Navigation metadata shared by the NiceGUI pages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavigationItem:
    """Static navigation metadata for placeholder screens."""

    label: str
    path: str
    placeholder: str


@dataclass(frozen=True)
class SidebarGroup:
    """Static sidebar section with a non-clickable heading."""

    label: str
    items: tuple[NavigationItem, ...]


HEADER_NAV_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem("Workspace", "/workspace", "Main writing workspace"),
    NavigationItem("Models", "/models", "Model configuration and selection"),
    NavigationItem("Settings", "/settings", "Workspace settings"),
)
