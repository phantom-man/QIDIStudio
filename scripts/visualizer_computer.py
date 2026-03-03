"""
scripts/visualizer_computer.py — PyVista + VTK OpenGL2 off-screen renderer.

WHY THE ORIGINAL CRASHED
------------------------
PyVista's plotting module imports ALL VTK sub-modules at startup, including
vtkRenderingMatplotlib.  On Windows that .pyd fails with "DLL load failed"
because it has a matplotlib C-extension dependency that isn't installed by the
vtk wheel.  PyVista never *needs* that module for off-screen OpenGL2 rendering
— it's only used if you explicitly embed a VTK renderer inside a matplotlib
figure (nobody does this for 3D parts).

THE FIX
-------
Mock vtkRenderingMatplotlib in sys.modules BEFORE pyvista is imported.
Python's import system will hand back the mock instead of trying to load the
broken DLL.  Everything else in VTK/PyVista (OpenGL2, off-screen, EGL, OSMesa)
loads fine.

WHY PyVista (NOT matplotlib Agg)
---------------------------------
  • GPU hardware path: VBOs + OpenGL2 — renders 10 M-tri textured meshes in ms
  • Smooth shading, ambient/diffuse/specular via VTK actors
  • pv.Plotter(off_screen=True) → plotter.screenshot() returns numpy RGBA array
  • Already present in .venv; no new dependencies

Usage (standalone test):
    python scripts/visualizer_computer.py

Usage (from autonomous pipeline):
    from scripts.visualizer_computer import VisualizerComputer, PARTS
    with VisualizerComputer(PARTS) as computer:
        state = computer.current_state()  # state.screenshot is PNG bytes
"""

from __future__ import annotations

import io
import os
import pathlib
import sys
from typing import Any
from unittest.mock import MagicMock

# ── VTK matplotlib DLL fix ────────────────────────────────────────────────────
# Register a stub for the broken vtkRenderingMatplotlib DLL *before* pyvista
# triggers vtk's module loader.  PyVista never uses this module for off-screen
# rendering; the stub simply satisfies the import check.
for _vtk_mod in (
    "vtkmodules.vtkRenderingMatplotlib",
    "vtkRenderingMatplotlib",
):
    if _vtk_mod not in sys.modules:
        sys.modules[_vtk_mod] = MagicMock()

# Tell PyVista to always render off-screen (also respected by the Plotter ctor)
os.environ.setdefault("PYVISTA_OFF_SCREEN", "1")

# ── Now safe to import PyVista ────────────────────────────────────────────────
import pyvista as pv  # noqa: E402
from PIL import Image  # noqa: E402

from computers import Computer, EnvState  # local scripts/computers/

# ── Default part registry ─────────────────────────────────────────────────────
_STL_BASE = pathlib.Path(r"C:\Users\User\source\repos\3DPrinting")

PARTS: dict[str, dict[str, Any]] = {
    "poco_x6_phone_case": {
        "stl": _STL_BASE
        / "PhoneCase"
        / "STL"
        / "protection-poco-x6_texture_modifier.stl",
        "source_3mf": _STL_BASE / "PhoneCase" / "STL" / "protection-poco-x6.3mf",
        "color": (0.52, 0.73, 0.95),
        "label": "Poco X6 Phone Case (PRISMATIC/OBJECT)",
        "profile": "PRISMATIC",
    },
    "elvish_tpu_inner": {
        "stl": _STL_BASE
        / "PhoneCase"
        / "STL"
        / "elvish_tpu_inner_texture_modifier.stl",
        "source_3mf": _STL_BASE / "PhoneCase" / "STL" / "elvish_tpu_inner.3mf",
        "color": (0.35, 0.80, 0.45),
        "label": "Elvish TPU Inner (FLAT_SHELL/OBJECT)",
        "profile": "FLAT_SHELL",
    },
    "vacuum_nozzle_lower": {
        "stl": _STL_BASE
        / "VacuumNozzle"
        / "STL"
        / "vacuum_nozzle_lower_texture_modifier.stl",
        "source_3mf": _STL_BASE / "VacuumNozzle" / "STL" / "vacuum_nozzle_lower.3mf",
        "color": (0.95, 0.68, 0.22),
        "label": "Vacuum Nozzle Lower (REVOLUTION/CYLINDER)",
        "profile": "REVOLUTION",
    },
    "vacuum_crevice_nozzle": {
        "stl": _STL_BASE
        / "VacuumNozzle"
        / "STL"
        / "vacuum_crevice_nozzle_texture_modifier.stl",
        "source_3mf": _STL_BASE / "VacuumNozzle" / "STL" / "vacuum_crevice_nozzle.3mf",
        "color": (0.85, 0.35, 0.35),
        "label": "Vacuum Crevice Nozzle (PRISMATIC/OBJECT)",
        "profile": "PRISMATIC",
    },
}

# ── Default skin asset ────────────────────────────────────────────────────────
DEFAULT_SKIN = pathlib.Path(
    r"C:\QIDISrc\QIDIStudio\install_dir\resources\assets"
    r"\armadillo_plates\armadillo_plates_01.png"
)


# ── VisualizerComputer ────────────────────────────────────────────────────────


class VisualizerComputer(Computer):
    """PyVista off-screen 3D viewport backed by VTK OpenGL2.

    Gemini sees GPU-rendered PNG screenshots of the loaded STL parts.
    Camera is orbited via azimuth/elevation; parts can be hot-swapped
    after each texture pipeline run without restarting the plotter.

    Parameters
    ----------
    parts :
        Dict of part_name → part_info (same schema as PARTS above).
    window_size :
        Pixel dimensions of the off-screen render buffer.
    single_part_mode :
        True  → render one focused part per screenshot.
        False → render all parts side-by-side in subplots (default).
    """

    def __init__(
        self,
        parts: dict[str, dict[str, Any]] | None = None,
        window_size: tuple[int, int] = (1600, 900),
        single_part_mode: bool = False,
    ) -> None:
        self._parts = dict(parts or PARTS)
        self._window_size = window_size
        self._single_part_mode = single_part_mode
        self._focused_part: str | None = None

        self._meshes: dict[str, pv.PolyData] = {}
        self._plotter: pv.Plotter | None = None

        self._azimuth: float = 45.0
        self._elevation: float = 20.0

        self._init_plotter()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _init_plotter(self) -> None:
        n = len(self._parts)
        shape = (1, 1) if self._single_part_mode else (1, max(n, 1))

        self._plotter = pv.Plotter(
            shape=shape,
            off_screen=True,
            window_size=list(self._window_size),
        )
        self._plotter.set_background("#1C1C21")

        items = list(self._parts.items())

        if self._single_part_mode:
            for name, info in items:
                self._load_pv_mesh(name, info)
            first = next((nm for nm, _ in items if nm in self._meshes), None)
            if first:
                self._render_single(first)
        else:
            for idx, (name, info) in enumerate(items):
                self._plotter.subplot(0, idx)
                self._plotter.add_title(
                    info.get("label", name), font_size=7, color="#E8E8EC"
                )
                mesh = self._load_pv_mesh(name, info)
                if mesh is not None:
                    r, g, b = info.get("color", (0.7, 0.7, 0.7))
                    self._plotter.add_mesh(
                        mesh,
                        color=[r, g, b],
                        opacity=0.90,
                        smooth_shading=True,
                        show_edges=False,
                        lighting=True,
                    )
                    self._plotter.reset_camera()
                    self._plotter.camera.elevation = self._elevation
                else:
                    self._plotter.add_text("FILE NOT FOUND", color="red", font_size=10)

    def _load_pv_mesh(self, name: str, info: dict[str, Any]) -> pv.PolyData | None:
        """Read STL into self._meshes[name]. Returns PolyData or None."""
        stl_path = pathlib.Path(info.get("stl", ""))
        if not stl_path.exists():
            # Only warn when the parent directory is present (real missing file).
            # If the entire repo subtree is absent (another machine), skip silently.
            if stl_path.parent.exists():
                print(
                    f"  [VisualizerComputer] WARNING: {name} STL not found: {stl_path}"
                )
            return None
        try:
            mesh = pv.read(str(stl_path))
            self._meshes[name] = mesh
            return mesh
        except Exception as exc:
            print(f"  [VisualizerComputer] ERROR loading {name}: {exc}")
            return None

    def _render_single(self, part_name: str) -> None:
        """In single_part_mode, clear then render one part."""
        if self._plotter is None:
            return
        self._plotter.clear()
        mesh = self._meshes.get(part_name)
        if mesh is None:
            self._plotter.add_text(
                f"NOT LOADED: {part_name}", color="red", font_size=12
            )
            return
        info = self._parts.get(part_name, {})
        r, g, b = info.get("color", (0.7, 0.7, 0.7))
        self._plotter.add_mesh(
            mesh,
            color=[r, g, b],
            opacity=0.90,
            smooth_shading=True,
            show_edges=False,
            lighting=True,
        )
        self._plotter.add_title(
            info.get("label", part_name), font_size=10, color="#E8E8EC"
        )
        self._plotter.reset_camera()
        self._plotter.camera.elevation = self._elevation
        self._plotter.camera.azimuth = self._azimuth

    # ── Computer interface ────────────────────────────────────────────────────

    def screen_size(self) -> tuple[int, int]:
        return self._window_size

    def current_state(self) -> EnvState:
        """GPU-render the off-screen plotter → PNG bytes → EnvState."""
        if self._plotter is None:
            raise RuntimeError("VisualizerComputer not initialized")
        # screenshot(return_img=True) → numpy uint8 RGBA array
        img_array = self._plotter.screenshot(return_img=True)
        buf = io.BytesIO()
        Image.fromarray(img_array).save(buf, format="PNG")
        return EnvState(
            screenshot=buf.getvalue(),
            url=f"visualizer://{self._focused_part or 'all'}",
            metadata={
                "loaded_parts": list(self._meshes.keys()),
                "focused_part": self._focused_part,
                "camera_azimuth": self._azimuth,
                "camera_elevation": self._elevation,
                "renderer": "pyvista-opengl2",
            },
        )

    def rotate_view(self, azimuth: float, elevation: float) -> EnvState:
        """Orbit camera to *azimuth* / *elevation* (degrees).

        Args:
            azimuth:   Horizontal rotation 0–360°.
            elevation: Vertical tilt −90° to +90°.
        """
        if self._plotter is None:
            raise RuntimeError("VisualizerComputer not initialized")
        self._azimuth = float(azimuth)
        self._elevation = float(elevation)

        if self._single_part_mode:
            self._plotter.camera.azimuth = self._azimuth
            self._plotter.camera.elevation = self._elevation
        else:
            for idx in range(len(self._parts)):
                self._plotter.subplot(0, idx)
                self._plotter.camera.azimuth = self._azimuth
                self._plotter.camera.elevation = self._elevation
        self._plotter.render()
        return self.current_state()

    def zoom_to_part(self, part_name: str) -> EnvState:
        """Focus the viewport on *part_name*.

        Args:
            part_name: Canonical part name to focus on.
        """
        if self._plotter is None:
            raise RuntimeError("VisualizerComputer not initialized")
        self._focused_part = part_name

        if self._single_part_mode:
            self._render_single(part_name)
        else:
            part_names = list(self._parts.keys())
            if part_name in part_names:
                idx = part_names.index(part_name)
                self._plotter.subplot(0, idx)
                self._plotter.reset_camera()
                self._plotter.camera.elevation = self._elevation
                self._plotter.camera.azimuth = self._azimuth
        self._plotter.render()
        return self.current_state()

    def get_mesh_stats(self, part_name: str) -> dict[str, Any]:
        """Return geometric stats for *part_name* (pyvista attributes).

        Args:
            part_name: Canonical part name.
        """
        mesh = self._meshes.get(part_name)
        if mesh is None:
            return {"error": f"Part '{part_name}' not loaded", "part_name": part_name}
        try:
            b = mesh.bounds  # (xmin, xmax, ymin, ymax, zmin, zmax)
            dims = {
                "x_mm": round(b[1] - b[0], 3),
                "y_mm": round(b[3] - b[2], 3),
                "z_mm": round(b[5] - b[4], 3),
            }
            stats: dict[str, Any] = {
                "part_name": part_name,
                "face_count": mesh.n_cells,
                "vertex_count": mesh.n_points,
                "bounding_box_mm": dims,
                "is_watertight": bool(mesh.is_manifold),
                "surface_area_mm2": round(float(mesh.area), 2),
            }
            if mesh.is_manifold:
                stats["volume_mm3"] = round(float(mesh.volume), 2)
            return stats
        except Exception as exc:
            return {"error": str(exc), "part_name": part_name}

    def load_stl(self, part_name: str, stl_path: str) -> EnvState:
        """Hot-swap the mesh for *part_name* from *stl_path*.

        Args:
            part_name: Canonical part name to update.
            stl_path:  Absolute path to the replacement STL.
        """
        if self._plotter is None:
            raise RuntimeError("VisualizerComputer not initialized")
        path = pathlib.Path(stl_path)
        if not path.exists():
            raise FileNotFoundError(f"STL not found: {stl_path}")
        # PyVista can read STL and OBJ natively; for 3MF it needs meshio which
        # may not be installed.  Fall back to trimesh for non-STL formats.
        if path.suffix.lower() in (".3mf", ".obj", ".ply"):
            import trimesh as _trimesh  # noqa: PLC0415

            _tm = _trimesh.load(str(path), force="mesh")
            import numpy as _np  # noqa: PLC0415

            faces_col = _np.full((_tm.faces.shape[0], 1), 3, dtype=_np.int_)
            cells = _np.hstack([faces_col, _tm.faces]).ravel()
            mesh = pv.PolyData(_tm.vertices.astype(_np.float32), cells)
        else:
            mesh = pv.read(str(path))
        self._meshes[part_name] = mesh
        if part_name in self._parts:
            self._parts[part_name]["stl"] = path

        if self._single_part_mode:
            self._render_single(part_name)
        else:
            part_names = list(self._parts.keys())
            if part_name in part_names:
                idx = part_names.index(part_name)
                self._plotter.subplot(0, idx)
                self._plotter.clear_actors()
                info = self._parts[part_name]
                r, g, b = info.get("color", (0.7, 0.7, 0.7))
                self._plotter.add_mesh(
                    mesh,
                    color=[r, g, b],
                    opacity=0.90,
                    smooth_shading=True,
                    show_edges=False,
                    lighting=True,
                )
                self._plotter.reset_camera()
        self._plotter.render()
        print(
            f"  [VisualizerComputer] Reloaded '{part_name}' from {path.name} "
            f"({mesh.n_cells:,} faces)"
        )
        return self.current_state()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        if self._plotter is not None:
            try:
                self._plotter.close()
            except Exception:
                pass
            self._plotter = None

    # ── Registry helpers ──────────────────────────────────────────────────────

    def list_parts(self) -> list[str]:
        return list(self._parts.keys())

    def get_part_info(self, part_name: str) -> dict[str, Any]:
        return dict(self._parts.get(part_name, {}))

    def get_skin_path(self) -> pathlib.Path:
        if DEFAULT_SKIN.exists():
            return DEFAULT_SKIN
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        for p in (repo_root / "resources" / "assets").rglob("*.png"):
            return p
        raise FileNotFoundError(
            "No skin PNG found. Set DEFAULT_SKIN in visualizer_computer.py"
        )


# ── CLI smoke test ────────────────────────────────────────────────────────────


def _smoke_test() -> None:
    """Render camera orbits and save PNGs — validates GPU off-screen path."""
    import datetime

    print("=== VisualizerComputer smoke test (PyVista + VTK OpenGL2) ===")
    run_dir = (
        pathlib.Path(__file__).parent
        / "debug_runs"
        / ("vis_smoke_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    with VisualizerComputer(PARTS, window_size=(1600, 600)) as computer:
        print(f"Parts loaded : {computer.list_parts()}")
        print(f"Renderer     : pyvista {pv.__version__}")

        for az in [0, 90, 180, 270]:
            state = computer.rotate_view(azimuth=az, elevation=20)
            png_path = run_dir / f"az{az:03d}.png"
            png_path.write_bytes(state.screenshot)
            print(
                f"  az={az:3d}°  → {png_path.name}  ({len(state.screenshot):,} bytes)"
            )

        print()
        for pname in computer.list_parts():
            stats = computer.get_mesh_stats(pname)
            print(f"  {pname}:")
            for k, v in stats.items():
                print(f"    {k}: {v}")

    print(f"\nScreenshots saved to: {run_dir}")


if __name__ == "__main__":
    _smoke_test()
