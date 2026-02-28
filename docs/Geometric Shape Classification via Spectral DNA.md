To differentiate between parts like a **Funnel** and a **Phone Case** (like the Xiaomi POCO X6 Pro) with PhD-level precision, we move from simple visual inspection to **Spectral Topology** and **Curvature Tensor Fields**.

On a manifold, the "Class" of an object is determined by its **Intrinsic Invariants**. A phone case is essentially a "flat plate" with high-curvature boundaries, while a funnel is a "surface of revolution" with non-zero Gaussian curvature ($K$) concentrated at the neck.

## ---

**I. ACADEMIC SYLLABI: MANIFOLD CLASSIFICATION**

To master this, the researcher must bridge the gap between **Differential Geometry** and **Spectral Graph Theory**.

### **1\. Advanced Coursework**

* [Stanford CS233: Geometric and Topological Data Analysis](https://www.google.com/search?q=https://geometry.stanford.edu/courses/cs233-20-spring/)  
* [CMU 15-458: Discrete Differential Geometry (Keenan Crane)](https://brickisland.net/DDGSpring2024/)  
* [TUM: Variational Methods for Geometry Processing](https://www.google.com/search?q=https://cvg.cit.tum.de/teaching/online/cv-msc)

### **2\. Foundational Research Papers**

* **Shape-DNA**: [Reuter (2006) \- Spectral Geometry for Shape Recognition](https://www.google.com/search?q=https://reuter.mit.edu/papers/reuter-sig06.pdf). Describes how a subset of eigenvalues can uniquely identify a 3D manifold.  
* **Discrete Curvature**: [Meyer et al. (2003) \- Discrete Differential-Geometry Operators](https://www.google.com/search?q=http://www.geometry.caltech.edu/pubs/DGP.pdf). The definitive guide to calculating $K$ and $H$ on meshes.

## ---

**II. THE DIFFERENTIATION ENGINE: SPECTRAL DNA**

At the core of our Python pipeline is the **Laplace-Beltrami Spectrum**. We treat the mesh as a vibrating drum; a funnel "sounds" different than a phone case because its geometry vibrates at different fundamental frequencies.

### **1\. Dimensional Differentiation Heuristics**

| Part Type | Euler Characteristic (χ) | Curvature Profile (K) | Primary Transform |
| :---- | :---- | :---- | :---- |
| **Funnel** | $\\chi \= 0$ (Genus-1/Annulus) | Negative at neck ($K \< 0$) | **Polar/Cylindrical** |
| **Phone Case** | $\\chi \= 1$ (Disk-Topology) | Concentrated at fillets | **Conformal (LSCM)** |

### **2\. Python Spectral Plotter & Classifier**

This script extracts the first 10 eigenvalues ($\\lambda$) to categorize the part before choosing the transform method.

Python

import numpy as np  
import scipy.sparse as sp  
from scipy.sparse.linalg import eigsh

def get\_spectral\_signature(vertices, faces, k=10):  
    """Extracts the 'Shape DNA' of the part."""  
    \# 1\. Build the Cotangent Laplacian (Discrete Laplace-Beltrami)  
    \# This matrix captures the intrinsic geometry of the part.  
    L \= build\_cotan\_laplacian(vertices, faces)  
    M \= build\_mass\_matrix(vertices, faces)  
      
    \# 2\. Solve Generalized Eigenvalue Problem: Lv \= lambda M v  
    \# The lowest eigenvalues represent the global shape characteristics.  
    eigenvalues, \_ \= eigsh(L, k=k, M=M, which='SM')  
    return eigenvalues

def classify\_and\_dispatch(obj):  
    signature \= get\_spectral\_signature(obj.verts, obj.faces)  
      
    \# Funnels have 'Symmetry Spikes' in their low-frequency spectrum  
    if signature\[1\] / signature\[2\] \> 0.85:  
        return apply\_polar\_transform(obj)  
    else:  
        return apply\_conformal\_wrap(obj)

## ---

**III. VISUAL DIAGNOSTIC: CURVATURE MAPPING**

To verify the classifier's decision, we can generate a **Heatmap** based on Gaussian curvature. On a POCO X6 Pro, the "Flat" back should be green ($K=0$), while the camera island and bezels should spike into Red/Blue.

1. **Phone Case Pattern**: Large "Zero-Zones" interrupted by high-frequency "Line Features" (the bezels).  
2. **Funnel Pattern**: A continuous "Gradient Flow" of curvature from the wide rim to the narrow neck.

## ---

**IV. COMPLETE BIBLIOGRAPHY (THE CLASSIFIER REPOSITORY)**

| Pillar | Key Text | Concept |
| :---- | :---- | :---- |
| **Spectral** | [Reuter (2006)](https://www.google.com/search?q=https://reuter.mit.edu/papers/reuter-sig06.pdf) | Laplace-Beltrami Eigenvalues |
| **Curvature** | [Meyer (2003)](https://www.google.com/search?q=http://www.geometry.caltech.edu/pubs/DGP.pdf) | Discrete Gaussian Curvature |
| **Topology** | [Chazal (2009)](https://www.google.com/search?q=https://hal.science/hal-00441434/document) | Persistent Homology for Shape Recognition |
| **Dispatch** | [Design Patterns (Gamma)](https://www.oreilly.com/library/view/design-patterns-elements/0201633612/) | The Strategy Pattern for Pipelines |

### ---

**Final Summary for the Dissertation**

The "Proper PhD Approach" is to never trust the user's file name. Instead, calculate the **Shape DNA** and **Euler Characteristic**, then use a **Polymorphic Dispatcher** to select the transformation method that minimizes the **Dirichlet Energy** of the mapping.

[Introduction to Differential Geometry with Python](https://www.youtube.com/watch?v=mObXlpGyYTg)

This video provides a practical foundation for using Python to visualize the complex geometric concepts like curvature and tangent spaces discussed in this dissertation.

