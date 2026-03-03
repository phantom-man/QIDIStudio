"""
scripts/computers/computer.py — Computer ABC and EnvState for viewport-in-the-loop agents.

Interface adapted from google-gemini/computer-use-preview (Apache-2.0).
https://github.com/google-gemini/computer-use-preview/blob/main/computers/computer.py

The original is browser-focused.  This adaptation is domain-neutral: any
"screen" that can return a PNG screenshot and dispatch typed actions qualifies.
"""

from __future__ import annotations

import abc
from typing import Any

import pydantic


class EnvState(pydantic.BaseModel):
    """Snapshot of the computer's current visual state.

    screenshot : PNG-encoded bytes of the current viewport.
    url        : Logical address of the current "page" (URL for browsers;
                 "visualizer://<part_name>" for the 3D visualizer).
    metadata   : Any extra structured data the Computer wants to pass back
                 (camera state, quality metrics, etc.).
    """

    screenshot: bytes
    url: str = "visualizer://active"
    metadata: dict[str, Any] = pydantic.Field(default_factory=dict)


class Computer(abc.ABC):
    """Abstract interface for an environment that Gemini Computer Use can control.

    Each subclass represents one kind of "screen":
      - PlaywrightComputer  → browser (original upstream implementation)
      - VisualizerComputer  → PyVista 3D viewport (this project)

    Gemini sees screenshots returned by current_state() and issues function
    calls that are dispatched to the methods below.  Every method must return
    an EnvState so the agent can observe the outcome.
    """

    # ── Core ──────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def screen_size(self) -> tuple[int, int]:
        """Return (width, height) of the viewport in pixels."""

    @abc.abstractmethod
    def current_state(self) -> EnvState:
        """Render the current viewport and return it as an EnvState."""

    # ── 3D Viewport actions (domain-specific) ────────────────────────────────

    def rotate_view(self, azimuth: float, elevation: float) -> EnvState:
        """Orbit the camera to the given azimuth / elevation in degrees."""
        raise NotImplementedError(f"{type(self).__name__} does not support rotate_view")

    def zoom_to_part(self, part_name: str) -> EnvState:
        """Fit the camera to the bounding box of a named part."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support zoom_to_part"
        )

    def get_mesh_stats(self, part_name: str) -> dict[str, Any]:
        """Return a dict with face_count, bounding_box, is_watertight, volume_mm3."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support get_mesh_stats"
        )

    def load_stl(self, part_name: str, stl_path: str) -> EnvState:
        """Hot-swap the mesh for *part_name* from *stl_path* and re-render."""
        raise NotImplementedError(f"{type(self).__name__} does not support load_stl")

    # ── Context manager support ───────────────────────────────────────────────

    def __enter__(self) -> "Computer":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:  # noqa: D401
        """Release any resources held by the computer (e.g. PyVista plotter)."""
