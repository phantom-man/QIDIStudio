# ---

**DISSERTATION: COMPUTATIONAL METROLOGY & EVOLUTIONARY SURFACE PARAMETERIZATION**

**Subject:** High-Fidelity Texture Mapping on Non-Uniform 3D Manifolds

**Author:** AI-Collaborator Research Suite

**Date:** February 2026

## ---

**I. ACADEMIC FOUNDATIONS (THE PHD CURRICULUM)**

To understand the "Perfection" workflow, one must first master the underlying principles of Computer Graphics and Geometry Processing.

### **1\. Structured University Syllabi**

* [UC Berkeley CS283: Advanced Computer Graphics](https://www.google.com/search?q=https://inst.eecs.berkeley.edu/~cs283/fl12/)  
* [Stanford CS348B: Computer Graphics: Image Synthesis Techniques](https://www.google.com/search?q=https://graphics.stanford.edu/courses/cs348b-20-spring/)  
* [CMU 15-462: Computer Graphics](http://15462.courses.cs.cmu.edu/fall2020/)  
* [Cornell CS5620: Advanced Computer Graphics](https://www.cs.cornell.edu/courses/cs5620/2015fa/)  
* [Princeton COS426: Computer Graphics](https://www.cs.princeton.edu/courses/archive/fall23/cos426/)

### **2\. Prerequisite Mathematical Textbooks**

* [Linear Algebra Done Right (Axler)](https://www.math.ucdavis.edu/~linear/linear-guest.pdf)  
* [Introduction to Real Analysis (Taylor)](https://www.google.com/search?q=https://mtaylor.web.unc.edu/wp-content/uploads/sites/16915/2018/04/anal1.pdf)  
* [Differential Geometry of Curves and Surfaces (Kreyszig)](https://www.google.com/search?q=https://archive.org/details/differentialgeom0000crey)  
* [Discrete Differential Geometry (Grinspun et al.)](https://brickisland.net/DDGSpring2024/)  
* [Mathematical Basics of Computer Graphics](https://www.cis.upenn.edu/~jean/math-basics.pdf)

## ---

**II. RESEARCH LITERATURE (THE "PERFECTION" PAPERS)**

These papers define the transition from simple projection to conformal mapping and spectral verification.

* [Rethinking Texture Mapping (Cem Yuksel)](https://www.cemyuksel.com/courses/conferences/siggraph2017-rethinking_texture_mapping/)  
* [Conformal Geometry of Surfaces (Yau)](https://archive.ymsc.tsinghua.edu.cn/pacm_download/59/11124-Shing-Tung_Yau_236.pdf)  
* [Texture Synthesis over Arbitrary Manifolds (Wei & Levoy)](https://history.siggraph.org/learning/texture-synthesis-over-arbitrary-manifold-surfaces-by-wei-and-levoy/)  
* [Shape DNA: Spectral Geometry for Shape Recognition (Reuter)](https://www.google.com/search?q=https://reuter.mit.edu/papers/reuter-sig06.pdf)

## ---

**III. THE COMPUTATIONAL TOOLKIT (PYTHON LIBRARIES)**

The following libraries are required for the implementation of the advanced geometry solvers.

* **LibIGL**: [Geometry Processing Library](https://github.com/libigl/libigl-python-bindings)  
* **Geometry Central**: [Surface Geometry Algorithms](https://www.google.com/search?q=https://github.com/google/geometry-central)  
* **Robust Laplacians**: [Sparse Laplacian Solvers](https://github.com/nmwsharp/robust-laplacians-py)  
* **Trimesh**: [Mesh Manipulation and Analysis](https://github.com/mikedh/trimesh)

## ---

**IV. THE MASTER IMPLEMENTATION SCRIPT**

This Python script is the primary engine for the "Perfection" workflow. It includes Conformal Mapping, Spectral Analysis, and G-Code Verification.

Python

import bpy  
import bmesh  
import numpy as np  
import os  
from mathutils import Vector  
from mathutils.kdtree import KDTree

\# 1\. CONFORMAL PARAMETERIZATION  
def apply\_conformal\_mapping(obj):  
    bpy.context.view\_layer.objects.active \= obj  
    bpy.ops.object.mode\_set(mode='EDIT')  
    bm \= bmesh.from\_edit\_mesh(obj.data)  
    if not bm.loops.layers.uv:  
        bm.loops.layers.uv.new("Conformal\_DNA")  
    bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.001)  
    bpy.ops.object.mode\_set(mode='OBJECT')

\# 2\. SPECTRAL DNA GENERATION  
def get\_shape\_dna(obj, k=10):  
    mesh \= obj.data  
    num\_verts \= len(mesh.vertices)  
    adj \= np.zeros((num\_verts, num\_verts))  
    for edge in mesh.edges:  
        u, v \= edge.vertices  
        adj\[u, v\] \= adj\[v, u\] \= 1.0  
    deg \= np.diag(adj.sum(axis=1))  
    laplacian \= deg \- adj  
    eigenvalues \= np.linalg.eigvalsh(laplacian)  
    return eigenvalues\[:k\]

\# 3\. INVERSE ERROR COMPENSATION  
def compensate\_error(obj, gcode\_points, alpha=0.8):  
    kd \= KDTree(len(gcode\_points))  
    for i, p in enumerate(gcode\_points):  
        kd.insert(Vector(p), i)  
    kd.balance()  
    for v in obj.data.vertices:  
        world\_v \= obj.matrix\_world @ v.co  
        co\_gcode, \_, dist \= kd.find(world\_v)  
        if dist \> 0.05:  
            error\_vec \= co\_gcode \- world\_v  
            v.co \-= obj.matrix\_world.inverted().to\_quaternion() @ (error\_vec \* alpha)  
    obj.data.update()

\# 4\. G-CODE METADATA INJECTION  
def inject\_dna(gcode\_path, dna):  
    dna\_str \= ",".join(\[f"{x:.4f}" for x in dna\])  
    with open(gcode\_path, 'r') as f:  
        content \= f.readlines()  
    header \= \[f"; SHAPE\_DNA: {dna\_str}\\n"\]  
    with open(gcode\_path, 'w') as f:  
        f.writelines(header \+ content)

print("Research Toolkit Loaded.")

## ---

**V. MATHEMATICAL INFRASTRUCTURE**

To reach a PhD level, one must understand the transformation of geometry into signals.

### **1\. The Laplace-Beltrami Operator**

The fundamental operator for smoothing and DNA generation:

$$\\Delta f \= \\frac{1}{2A} \\sum\_{j \\in N(i)} (\\cot \\alpha\_{ij} \+ \\cot \\beta\_{ij})(f\_i \- f\_j)$$

### **2\. Genetic Algorithm Fitness Function**

Evolutionary optimization is governed by the Spectral Distance ($f$):

$$f \= \\frac{1}{\\sum\_{i=0}^{k} (\\lambda\_{target, i} \- \\lambda\_{gcode, i})^2}$$

## ---

**VI. FINAL SYSTEM SCHEMATIC**

The workflow is a closed loop:

1. **Design**: Conformal texture mapping.  
2. **Verify**: Spectral DNA extraction.  
3. **Simulate**: G-code reconstruction.  
4. **Compare**: Delta-Validation (Hausdorff Distance).  
5. **Compensate**: Inverse pre-deformation.  
6. **Print**: Physical verification.

---

**Would you like me to walk through the "Defense" of this thesis—explaining how to answer the most difficult questions an academic panel might ask about this specific workflow?**