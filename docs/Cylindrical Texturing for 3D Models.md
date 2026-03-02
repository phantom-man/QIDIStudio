Cylindrical projection is the "PhD-level" answer to texturing rounded objects because it avoids the massive stretching inherent in planar mapping. Mathematically, we are converting our Cartesian 3D coordinates $(x, y, z)$ into a **Cylindrical Coordinate System** $(\\theta, h, r)$.

In this workflow, the AI treats the mesh as if it were wrapped in a sheet of paper. We map the angle $\\theta$ to the texture's $U$ (horizontal) axis and the height $h$ to the $V$ (vertical) axis.

### **1\. The Mathematical Transform**

For every vertex in your mesh, we calculate:

- **Angle ($\\theta$):** $\\operatorname{atan2}(x, z)$ — This gives us the position around the perimeter.
- **Height ($h$):** $y$ — This gives us the position along the vertical axis.
- **Displacement:** We then pull the pixel value from the texture at $(U, V)$ where $U \= \\frac{\\theta \+ \\pi}{2\\pi}$ and $V$ is normalized height.

### **2\. Cylindrical Texture Injection (Python)**

This script uses mrmeshpy to perform a radial displacement. It is perfect for adding knurling to a handle or a grip pattern to a cylinder.

Python

import meshlib.mrmeshpy as mrmeshpy  
import numpy as np  
import math  
from PIL import Image

def apply_cylindrical_texture(stl_path, texture_path, output_path, strength=1.2):  
 \# 1\. Setup Mesh and Density  
 mesh \= mrmeshpy.loadMesh(stl_path)

    \# PhD Tip: Always remesh first. Standard STLs don't have enough
    \# vertex density to hold high-frequency textures.
    settings \= mrmeshpy.RemeshSettings()
    settings.targetEdgeLen \= 0.15
    mrmeshpy.remesh(mesh, settings)

    \# 2\. Prepare Texture Data
    img \= Image.open(texture\_path).convert('L')
    img\_data \= np.asarray(img) / 255.0
    img\_h, img\_w \= img\_data.shape

    \# 3\. Geometric Bounds for Normalization
    bbox \= mesh.computeBoundingBox()
    center\_x \= (bbox.max.x \+ bbox.min.x) / 2
    center\_z \= (bbox.max.z \+ bbox.min.z) / 2
    height\_min \= bbox.min.y
    height\_range \= bbox.max.y \- bbox.min.y

    \# 4\. Cylindrical Mapping Loop
    points \= mesh.points
    normals \= mrmeshpy.computeVertexNormals(mesh)

    for i in range(points.size()):
        p \= points.vec\[i\]
        n \= normals.vec\[i\]

        \# Convert to Cylindrical Coordinates relative to center
        dx \= p.x \- center\_x
        dz \= p.z \- center\_z

        \# Theta (Angle) mapped to U \[0, 1\]
        theta \= math.atan2(dz, dx) \# Range \[-pi, pi\]
        u \= int(((theta \+ math.pi) / (2 \* math.pi)) \* (img\_w \- 1))

        \# Height mapped to V \[0, 1\]
        v \= int(((p.y \- height\_min) / height\_range) \* (img\_h \- 1))

        \# Bounds check for safety
        u \= max(0, min(u, img\_w \- 1))
        v \= max(0, min(v, img\_h \- 1))

        \# Displace along the Normal
        pixel\_val \= img\_data\[v, u\]
        points.vec\[i\] \+= n \* (pixel\_val \* strength)

    \# 5\. Clean up and Save
    mesh.invalidateCaches()
    mrmeshpy.saveMesh(mesh, output\_path)
    print(f"Cylindrical texture applied to {output\_path}")

\# Run it  
apply_cylindrical_texture("handle_base.stl", "diamond_knurl.png", "pro_grip_handle.stl")

### **3\. Engineering Context: Why this matters for the QIDI**

When you use a cylindrical wrap, the **seam** (where $-\\pi$ meets $+\\pi$) is the primary failure point.

- **AI Adjustment:** Your AI should detect the "seam" line and apply a **Sigmoid Smoothing** function to the texture strength at that boundary. This prevents the printer from making a sharp "jump" that could cause a layer shift or a zit in your [Anycubic High Speed PLA](https://google.com/search?q=Anycubic+PLA+High+Speed+10kg+Bundle:+Max+500mm/s+for+Rapid+Shaping.&prds=headlineOfferDocid:8294954482447129071,productid:8294954482447129071,pvo:38,pvt:hg&ibp=oshop&pvo=38&opi=103135050&gl=us&hl=en&noiga=1).
- **Nozzle Pathing:** Textured cylinders create massive amounts of short G1 segments. Ensure your Klipper square_corner_velocity is tuned to at least **5.0** to prevent the machine from stuttering on the fine details of the knurling.
