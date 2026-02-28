"""
scripts/view_texture_parts.py — Display all 4 texture-modified STL parts.

Primary backend:   trimesh + matplotlib (no OCP dependency — always works)
Secondary backend: build123d + ocp_vscode (if installed and OCP version matches)

Usage:
    From the VS Code terminal:
        .venv\\Scripts\\python.exe scripts/view_texture_parts.py

    Force matplotlib mode even if build123d is available:
        .venv\\Scripts\\python.exe scripts/view_texture_parts.py --matplotlib

    VS Code OCP viewer mode (requires working build123d):
        .venv\\Scripts\\python.exe scripts/view_texture_parts.py --ocp

Parts displayed (4 texture_modifier STLs):
    - protection-poco-x6         (phone case,    PRISMATIC/OBJECT)
    - elvish_tpu_inner           (TPU insert,    FREEFORM/LSCM)
    - vacuum_nozzle_lower        (vacuum nozzle, REVOLUTION/LSCM)
    - vacuum_crevice_nozzle      (crevice tool,  PRISMATIC/OBJECT)

Install (trimesh backend — minimal):
    pip install trimesh matplotlib

Install (OCP backend — full):
    pip install --force-reinstall --no-cache-dir build123d ocp_vscode
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
        "label": "Elvish TPU Inner (FREEFORM/LSCM)",
    },
    "vacuum_nozzle_lower": {
        "path": STL_BASE
        / "VacuumNozzle"
        / "STL"
        / "vacuum_nozzle_lower_texture_modifier.stl",
        "color": (0.95, 0.68, 0.22),  # amber
        "alpha": 0.85,
        "label": "Vacuum Nozzle Lower (REVOLUTION/LSCM)",
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


def _has_build123d() -> bool:
    try:
        import build123d  # noqa: F401

        # Quick smoke-test to catch the TopoDS.Vertex AttributeError
        from build123d import import_stl  # noqa: F401

        return True
    except Exception:
        return False


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


# ── Trimesh + Matplotlib backend ──────────────────────────────────────────────


def show_matplotlib() -> None:
    """Load STLs with trimesh, display 4-up 3D subplots in matplotlib."""
    if not _has_trimesh():
        print("ERROR: trimesh not installed. Run:  pip install trimesh matplotlib")
        sys.exit(1)
    if not _has_matplotlib():
        print("ERROR: matplotlib not installed. Run:  pip install trimesh matplotlib")
        sys.exit(1)

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

            # Auto-scale to mesh bounds
            mins = verts.min(axis=0)
            maxs = verts.max(axis=0)
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
    print("\nDisplaying in matplotlib window...")
    plt.show()


# ── OCP / build123d backend ───────────────────────────────────────────────────


def show_ocp() -> None:
    """Load STLs with build123d, send to OCP CAD Viewer in VS Code."""
    from build123d import import_stl  # type: ignore
    from ocp_vscode import show, set_port  # type: ignore

    print(f"\nOCP CAD Viewer — port {OCP_PORT}")
    print("Open: View -> OCP CAD Viewer in VS Code\n")
    set_port(OCP_PORT)

    parts, names, colors, alphas = [], [], [], []
    for info in PARTS.values():
        path: Path = info["path"]
        if not path.exists():
            print(f"  SKIP (not found): {path}")
            continue
        print(f"  Loading {path.name}... ", end="", flush=True)
        try:
            part = import_stl(str(path))
            parts.append(part)
            names.append(info["label"])
            r, g, b = info["color"]
            colors.append((int(r * 255), int(g * 255), int(b * 255)))
            alphas.append(info["alpha"])
            print("OK")
        except Exception as exc:
            print(f"FAIL: {exc}")

    if not parts:
        print("No parts loaded.")
        sys.exit(1)

    show(*parts, names=names, colors=colors, alphas=alphas, reset_camera=True)
    print("Display sent to OCP CAD Viewer.")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="View QIDIStudio texture parts")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ocp", action="store_true", help="Force OCP/build123d backend")
    group.add_argument(
        "--matplotlib", action="store_true", help="Force matplotlib backend"
    )
    args = parser.parse_args()

    if args.ocp:
        if not _has_build123d():
            print("ERROR: build123d/OCP not working. Fix with:")
            print("  pip install --force-reinstall --no-cache-dir build123d ocp_vscode")
            sys.exit(1)
        show_ocp()
    elif args.matplotlib or not _has_build123d():
        if args.ocp is False and not _has_build123d():
            print(
                "(build123d/OCP not available or broken — falling back to matplotlib)\n"
            )
        show_matplotlib()
    else:
        # build123d works — prefer OCP viewer
        try:
            show_ocp()
        except Exception as exc:
            print(f"OCP backend failed ({exc}) — falling back to matplotlib\n")
            show_matplotlib()


if __name__ == "__main__":
    main()
