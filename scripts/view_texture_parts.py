"""
scripts/view_texture_parts.py — Display all 4 texture-modified STL parts.

Backends (auto-selection order):
  1. pyvista        — interactive 3D, already installed, opens its own window
  2. matplotlib     — static 4-up subplots, always works

  (OCP/build123d removed — cadquery-ocp uninstalled to fix pyvista VTK conflict)

Usage:
    Auto (pyvista if installed, else matplotlib):
        .venv\\Scripts\\python.exe scripts/view_texture_parts.py

    Force specific backend:
        .venv\\Scripts\\python.exe scripts/view_texture_parts.py --pyvista
        .venv\\Scripts\\python.exe scripts/view_texture_parts.py --matplotlib
        .venv\\Scripts\\python.exe scripts/view_texture_parts.py --ocp

Parts displayed (4 texture_modifier STLs):
    - protection-poco-x6         (phone case,    PRISMATIC/OBJECT)
    - elvish_tpu_inner           (TPU insert,    FLAT_SHELL/OBJECT)
    - vacuum_nozzle_lower        (vacuum nozzle, REVOLUTION/CYLINDER)
    - vacuum_crevice_nozzle      (crevice tool,  PRISMATIC/OBJECT)

Requires: cadquery-ocp-novtk==7.9.3.1  (OCP 7.9 API — TopoDS.Vertex)
  If build123d import fails run:
    .venv\\Scripts\\pip uninstall cadquery-ocp -y
    .venv\\Scripts\\pip install cadquery-ocp-novtk==7.9.3.1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

STL_BASE = Path(r"C:\Users\User\source\repos\3DPrinting")

PARTS = {
    "poco_x6_phone_case": {
        "path": STL_BASE
        / "PhoneCase"
        / "STL"
        / "protection-poco-x6_texture_modifier.stl",
        "color": (0.52, 0.73, 0.95),  # soft blue
        "alpha": 0.85,
        "label": "Poco X6 Phone Case (PRISMATIC/OBJECT)",
    },
    "elvish_tpu_inner": {
        "path": STL_BASE
        / "PhoneCase"
        / "STL"
        / "elvish_tpu_inner_texture_modifier.stl",
        "color": (0.35, 0.80, 0.45),  # soft green
        "alpha": 0.85,
        "label": "Elvish TPU Inner (FLAT_SHELL/OBJECT)",
    },
    "vacuum_nozzle_lower": {
        "path": STL_BASE
        / "VacuumNozzle"
        / "STL"
        / "vacuum_nozzle_lower_texture_modifier.stl",
        "color": (0.95, 0.68, 0.22),  # amber
        "alpha": 0.85,
        "label": "Vacuum Nozzle Lower (REVOLUTION/CYLINDER)",
    },
    "vacuum_crevice_nozzle": {
        "path": STL_BASE
        / "VacuumNozzle"
        / "STL"
        / "vacuum_crevice_nozzle_texture_modifier.stl",
        "color": (0.85, 0.35, 0.35),  # terracotta
        "alpha": 0.85,
        "label": "Vacuum Crevice Nozzle (PRISMATIC/OBJECT)",
    },
}

OCP_PORT = 3939  # default OCP CAD Viewer websocket port


# ── Backend detection ─────────────────────────────────────────────────────────


def _has_pyvista() -> bool:
    try:
        import pyvista.plotting  # noqa: F401

        return True
    except Exception:
        return False


_BUILD123D_IMPORT_ERROR: str | None = None  # kept for --ocp error path


def _has_build123d() -> bool:
    return False  # cadquery-ocp uninstalled; OCP path disabled


def _has_trimesh() -> bool:
    try:
        import trimesh  # noqa: F401

        return True
    except ImportError:
        return False


def _has_matplotlib() -> bool:
    try:
        import matplotlib  # noqa: F401

        return True
    except ImportError:
        return False


# ── pyvista backend (primary — interactive 3D, already installed) ─────────────


def show_pyvista() -> None:
    """Load STLs with pyvista, display interactive 4-up 3D window."""
    import pyvista as pv  # type: ignore

    items = list(PARTS.values())
    n = len(items)

    # Check files exist before allocating the plotter
    missing = [info for info in items if not info["path"].exists()]
    if missing:
        for m in missing:
            print(f"  WARNING: not found — {m['path']}")

    plotter = pv.Plotter(
        shape=(1, n),
        title="QIDIStudio — Texture-Modified Parts",
        window_size=[1600, 600],
    )

    for idx, info in enumerate(items):
        path: Path = info["path"]
        label: str = info["label"]
        r, g, b = info["color"]
        alpha: float = info["alpha"]

        plotter.subplot(0, idx)
        plotter.add_title(label, font_size=7)

        if not path.exists():
            plotter.add_text("FILE NOT FOUND", color="red", font_size=10)
            continue

        print(f"  Loading {path.name}... ", end="", flush=True)
        try:
            mesh = pv.read(str(path))
            plotter.add_mesh(
                mesh,
                color=[r, g, b],
                opacity=alpha,
                smooth_shading=True,
                show_edges=False,
                lighting=True,
            )
            plotter.reset_camera()
            plotter.camera.elevation = 20
            print(f"OK ({mesh.n_cells:,} faces)")
        except Exception as exc:
            print(f"FAIL: {exc}")
            plotter.add_text(f"ERROR:\n{exc}", color="red", font_size=7)

    plotter.link_views()
    print("\nOpening pyvista window — drag to rotate, scroll to zoom, Q to quit...")
    plotter.show()


# ── Trimesh + Matplotlib backend (static fallback) ────────────────────────────


def show_matplotlib() -> None:
    """Load STLs with trimesh, display static 4-up 3D subplots in matplotlib."""
    import trimesh  # type: ignore
    import matplotlib.pyplot as plt  # type: ignore
    from mpl_toolkits.mplot3d import Axes3D  # type: ignore  # noqa: F401
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # type: ignore

    items = list(PARTS.values())
    fig = plt.figure(figsize=(18, 10))
    fig.suptitle("QIDIStudio — Texture-Modified Parts", fontsize=14, fontweight="bold")

    for idx, info in enumerate(items):
        path: Path = info["path"]
        label: str = info["label"]
        color = info["color"]
        alpha: float = info["alpha"]

        ax = fig.add_subplot(1, 4, idx + 1, projection="3d")
        ax.set_title(label, fontsize=7, wrap=True)

        if not path.exists():
            ax.text(
                0.5,
                0.5,
                0.5,
                "FILE NOT FOUND",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color="red",
            )
            continue

        print(f"  Loading {path.name}... ", end="", flush=True)
        try:
            mesh = trimesh.load(str(path), force="mesh")
            verts = mesh.vertices
            faces = mesh.faces
            poly = Poly3DCollection(
                verts[faces],
                alpha=alpha,
                facecolor=color,
                edgecolor=(0.2, 0.2, 0.2),
                linewidth=0.05,
            )
            ax.add_collection3d(poly)
            mins, maxs = verts.min(axis=0), verts.max(axis=0)
            ax.set_xlim(mins[0], maxs[0])
            ax.set_ylim(mins[1], maxs[1])
            ax.set_zlim(mins[2], maxs[2])
            ax.set_xlabel("X")
            ax.set_ylabel("Y")
            ax.set_zlabel("Z")
            print(f"OK ({len(faces):,} faces)")
        except Exception as exc:
            print(f"FAIL: {exc}")
            ax.text(
                0.5,
                0.5,
                0.5,
                f"LOAD ERROR\n{exc}",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color="red",
                fontsize=7,
            )

    plt.tight_layout()
    print("\nDisplaying static matplotlib window...")
    plt.show()


# ── OCP / build123d backend (VS Code OCP CAD Viewer) ─────────────────────────


def show_ocp() -> None:
    """Load STLs with build123d, send to OCP CAD Viewer in VS Code."""
    from build123d import import_stl, Location, Vector  # type: ignore
    from ocp_vscode import show, set_port, Camera  # type: ignore
    from ocp_vscode.comms import port_check  # type: ignore

    set_port(OCP_PORT)

    # Fail fast if viewer panel isn't open — don't silently discard the geometry
    if not port_check(OCP_PORT):
        raise RuntimeError(
            f"OCP CAD Viewer not listening on port {OCP_PORT}. "
            "Open it in VS Code: Ctrl+Shift+P → 'OCP: Open Viewer'"
        )

    print(f"\nOCP CAD Viewer — port {OCP_PORT}\n")

    parts, names, colors, alphas = [], [], [], []
    x_offset = 0.0
    GAP_MM = 20.0  # spacing between parts

    for info in PARTS.values():
        path: Path = info["path"]
        if not path.exists():
            print(f"  SKIP (not found): {path}")
            continue
        print(f"  Loading {path.name}... ", end="", flush=True)
        try:
            part = import_stl(str(path))

            # Compute bounding box and centre-then-place along X axis
            bb = part.bounding_box()
            # Move part so its bounding box min-X aligns to current x_offset,
            # and centred on Y/Z
            dx = x_offset - bb.min.X
            dy = -(bb.min.Y + bb.max.Y) / 2
            dz = -(bb.min.Z + bb.max.Z) / 2
            part = part.moved(Location(Vector(dx, dy, dz)))

            x_offset += (bb.max.X - bb.min.X) + GAP_MM

            parts.append(part)
            names.append(info["label"])
            # ocp_vscode expects CSS hex colour strings e.g. "#84BAEF"
            r, g, b = info["color"]
            colors.append(f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}")
            alphas.append(info["alpha"])
            print(
                f"OK  ({bb.max.X - bb.min.X:.0f} × "
                f"{bb.max.Y - bb.min.Y:.0f} × "
                f"{bb.max.Z - bb.min.Z:.0f} mm)"
            )
        except Exception as exc:
            print(f"FAIL: {exc}")

    if not parts:
        print("No parts loaded.")
        sys.exit(1)

    show(
        *parts,
        names=names,
        colors=colors,
        alphas=alphas,
        reset_camera=Camera.RESET,
    )
    print("Display sent to OCP CAD Viewer.")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View QIDIStudio texture-modified STL parts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Auto mode selects: OCP CAD Viewer (in VS Code) → pyvista → matplotlib.\n"
            "OCP requires cadquery-ocp-novtk==7.9.3.1 (OCP 7.9 - TopoDS.Vertex API)."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--pyvista", action="store_true", help="Force pyvista backend (interactive 3D)"
    )
    group.add_argument(
        "--matplotlib", action="store_true", help="Force matplotlib backend (static)"
    )
    group.add_argument(
        "--ocp",
        action="store_true",
        help="Force OCP/build123d backend (VS Code OCP Viewer)",
    )
    args = parser.parse_args()

    if args.ocp:
        if not _has_build123d():
            print("ERROR: build123d/OCP not working.")
            if _BUILD123D_IMPORT_ERROR:
                print("\n--- build123d import traceback ---")
                print(_BUILD123D_IMPORT_ERROR)
                print("--- end traceback ---\n")
            print("Ensure OCP 7.9 is installed:")
            print("  .venv\\Scripts\\pip uninstall cadquery-ocp -y")
            print("  .venv\\Scripts\\pip install cadquery-ocp-novtk==7.9.3.1")
            sys.exit(1)
        show_ocp()
        return

    if args.matplotlib:
        show_matplotlib()
        return

    if args.pyvista:
        if not _has_pyvista():
            print("ERROR: pyvista not installed. Run: pip install pyvista")
            sys.exit(1)
        show_pyvista()
        return

    # Auto mode: pyvista → matplotlib  (OCP is opt-in via --ocp only)
    if _has_pyvista():
        try:
            show_pyvista()
            return
        except Exception as exc:
            print(f"pyvista backend failed ({exc}) — falling back to matplotlib\n")

    # Ultimate fallback
    if _has_trimesh() and _has_matplotlib():
        print("(pyvista unavailable — cadquery_vtk DLL conflict — using matplotlib)\n")
        show_matplotlib()
    else:
        print("ERROR: No display backend available.")
        print("Install pyvista:    pip install pyvista")
        print("Install matplotlib: pip install trimesh matplotlib")
        sys.exit(1)


if __name__ == "__main__":
    main()
