"""Background scene generation manager."""

from __future__ import annotations

import threading

from app.graphs.scene_generation import run_scene_generation

_GENERATION_MANAGER: GenerationManager | None = None


class GenerationManager:
    """Process-wide manager for async scene generation runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, threading.Thread] = {}
        self._errors: dict[str, str] = {}

    def start_generation(self, scene_id: str, *, max_revisions: int = 1) -> None:
        """Start generation for ``scene_id`` in a background thread."""

        with self._lock:
            if scene_id in self._active:
                msg = f"Generation already running for scene {scene_id}"
                raise RuntimeError(msg)
            self._errors.pop(scene_id, None)
            thread = threading.Thread(
                target=self._run,
                args=(scene_id, max_revisions),
                name=f"scene-gen-{scene_id}",
                daemon=True,
            )
            self._active[scene_id] = thread
            thread.start()

    def is_generating(self, scene_id: str) -> bool:
        """Return True when a generation run is active for ``scene_id``."""

        with self._lock:
            thread = self._active.get(scene_id)
            return thread is not None and thread.is_alive()

    def last_error(self, scene_id: str) -> str | None:
        """Return the last error message for ``scene_id``, if any."""

        with self._lock:
            return self._errors.get(scene_id)

    def _run(self, scene_id: str, max_revisions: int) -> None:
        try:
            run_scene_generation(scene_id, max_revisions=max_revisions)
        except Exception as exc:
            with self._lock:
                self._errors[scene_id] = str(exc)
        finally:
            with self._lock:
                self._active.pop(scene_id, None)


def get_generation_manager() -> GenerationManager:
    """Return the process-local generation manager singleton."""

    global _GENERATION_MANAGER
    if _GENERATION_MANAGER is None:
        _GENERATION_MANAGER = GenerationManager()
    return _GENERATION_MANAGER
