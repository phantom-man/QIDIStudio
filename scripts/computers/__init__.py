"""
scripts/computers/ — Minimal Computer abstraction for the QIDIStudio autonomous pipeline.

Adapted from the interface defined in google-gemini/computer-use-preview (Apache-2.0).
We strip the browser-specific methods and keep only what VisualizerComputer needs.
"""

from .computer import Computer, EnvState

__all__ = ["Computer", "EnvState"]
