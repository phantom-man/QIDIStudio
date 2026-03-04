#!/usr/bin/env python3
"""
gen_icon.py — Generate NexusSlicer extension icon
Forge-black background + cyan isometric 3D mesh wireframe with layer lines.
Outputs: media/icon.png (256×256) and media/icon@2x.png (128×128)
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (12, 14, 20, 255))
draw = ImageDraw.Draw(img)


def iso(x, y, z):
    """Isometric projection: cube unit coords → pixel coords."""
    s = SIZE * 0.22
    ox, oy = SIZE // 2, SIZE * 0.55
    px = ox + (x - z) * s
    py = oy + (x + z) * s * 0.5 - y * s
    return (px, py)


# 8 unit-cube vertices
verts = [(i, j, k) for i in range(2) for j in range(2) for k in range(2)]
projected = {v: iso(*v) for v in verts}

# 12 edges (one-step Manhattan distance)
edges = [
    (v1, v2)
    for idx1, v1 in enumerate(verts)
    for idx2, v2 in enumerate(verts)
    if sum(abs(a - b) for a, b in zip(v1, v2)) == 1 and idx1 < idx2
]

CYAN = (0, 220, 255, 255)
GLOW = (0, 140, 200, 100)

# Glow pass (fat, semi-transparent)
for v1, v2 in edges:
    draw.line([projected[v1], projected[v2]], fill=GLOW, width=7)

# Crisp edges
for v1, v2 in edges:
    draw.line([projected[v1], projected[v2]], fill=CYAN, width=2)

# Horizontal layer lines on the front face (x=0, z=0..1 plane)
for i in range(1, 7):
    t = i / 7.0
    ya = projected[(0, 0, 0)][1] * (1 - t) + projected[(0, 1, 0)][1] * t
    xa0 = projected[(0, 0, 0)][0]
    xa1 = projected[(1, 0, 0)][0]
    # Interpolate Y on left edge then right edge of front face
    yb = projected[(0, 0, 0)][1] * (1 - t) + projected[(0, 1, 0)][1] * t
    draw.line(
        [(xa0, ya), (xa1, ya)],
        fill=(0, 180, 220, 140),
        width=1,
    )

# Layer lines on the right face (z=1)
for i in range(1, 7):
    t = i / 7.0
    p_bl = projected[(0, 0, 1)]
    p_tl = projected[(0, 1, 1)]
    p_br = projected[(1, 0, 1)]
    p_tr = projected[(1, 1, 1)]
    pa = (p_bl[0] + (p_tl[0] - p_bl[0]) * t, p_bl[1] + (p_tl[1] - p_bl[1]) * t)
    pb = (p_br[0] + (p_tr[0] - p_br[0]) * t, p_br[1] + (p_tr[1] - p_br[1]) * t)
    draw.line([pa, pb], fill=(0, 160, 200, 120), width=1)

# Soft glow pass
blurred = img.filter(ImageFilter.GaussianBlur(3))
img_final = Image.composite(img, blurred, img.split()[3])

# Actually just blend for a nice glow effect
combined = Image.blend(blurred, img, 0.65)

# Output paths — write to nexusslicer-viewer
out_dir = Path(__file__).parent.parent.parent / "nexusslicer-viewer" / "media"
combined.save(str(out_dir / "icon.png"))
combined.resize((128, 128), Image.LANCZOS).save(str(out_dir / "icon@2x.png"))
print(f"Icons written to {out_dir}")
