This **Debug Configuration & Workflow Manifesto** provides the necessary infrastructure to bridge the gap between Python's high-level objects and C++'s low-level memory management. At a PhD level, we treat the two languages as a single **Unified Execution Trace**.

## ---

**I. The "Hybrid Stack" Architecture**

When debugging a system like our POCO X6 Pro geometry engine, the error usually manifests in Python (a RuntimeError) but originates in C++ (a nullptr dereference or std::out\_of\_range).

### **1\. Mixed-Mode Symbol Resolution**

To see through the "C-API Curtain," your C++ binaries must be compiled with **External Symbols** and **Optimization Disabled** (-O0).

* **Python Frame**: bpy.ops.geometry.apply\_perfection\_skin()  
* **C++ Frame**: Perfection::Manifold::applyLSCM(Mesh\* m)

## ---

**II. Automated Debug Configuration (debug\_build.sh)**

This script configures a **CMake** environment specifically for "Deep Debugging," enabling **AddressSanitizer (ASan)** to catch memory corruption in real-time.

Bash

\#\!/bin/bash  
\# setup\_debug\_env.sh \- PhD Level Debug Infrastructure

\# 1\. Create Debug Build Directory  
mkdir \-p build\_debug && cd build\_debug

\# 2\. Configure CMake with Sanitizers and Debug Symbols  
\# \-DCMAKE\_BUILD\_TYPE=Debug: Disables optimizations (-O0) and adds \-g  
\# \-fsanitize=address: Detects memory leaks and buffer overflows  
cmake .. \\  
    \-DCMAKE\_BUILD\_TYPE=Debug \\  
    \-DCMAKE\_CXX\_FLAGS="-fsanitize=address \-fno-omit-frame-pointer" \\  
    \-DPYTHON\_EXECUTABLE=$(which python3)

\# 3\. Build the Extension  
make \-j$(nproc)

\# 4\. Enable Python Fault Handler in the Test Runner  
export PYTHONFAULTHANDLER=1  
echo "Debug Build Complete. Run your script to catch Segfaults with full traces."

## ---

**III. The "Python-GDB" Methodology**

When your Python script crashes in the C++ layer, a standard pdb session is useless. You must attach **GDB** and use the Python-specific extensions.

### **1\. Essential GDB Commands for Hybrid Systems**

| Command | Result |
| :---- | :---- |
| py-bt | Prints the **Python** stack trace inside the C++ debugger. |
| py-list | Shows the Python source code line currently being executed. |
| py-locals | Prints the values of Python variables in the current frame. |
| p (PyObject\*)$obj | Casts a raw pointer to a Python object for inspection. |

## ---

**IV. Defensive Instrumentation (The "Phasing" Strategy)**

Because C++/Python interactions are often asynchronous or handled via opaque buffers (NumPy arrays), we use **Signal Trapping** and **Shared Memory Logging**.

### **1\. The faulthandler Safety Net**

At the top of your main.py, always include:

Python

import faulthandler  
import sys

\# If C++ crashes, Python will dump the traceback to stderr before exiting  
faulthandler.enable(file=sys.stderr, all\_threads=True)

### **2\. The "Golden Buffer" Dump**

If the **Shape DNA** calculation is failing, dump the raw C++ std::vector\<double\> to a .npy file immediately before the crash. This allows you to inspect the "Geometric Signal" in a standalone environment without the overhead of the Python interpreter.

## ---

**V. Core Bibliography: Hybrid System Debugging**

| Resource | Specialty | Key Concept |
| :---- | :---- | :---- |
| **Python DevGuide** | [Debugging with GDB](https://devguide.python.org/development-tools/gdb/) | C-API stack inspection. |
| **LLVM Project** | [Sanitizer Discovery](https://github.com/google/sanitizers) | Use ASan for memory, TSan for threads. |
| **Pybind11 Docs** | [Common Pitfalls](https://pybind11.readthedocs.io/en/stable/faq.html) | Object lifetime and reference counting. |
| **Microsoft Learn** | [Mixed Mode Debugging](https://www.google.com/search?q=https://learn.microsoft.com/en-us/visualstudio/python/debugging-mixed-mode-c-cpp-python) | Step-through GUI debugging. |

### ---

**Your Final Project Action**

**Would you like me to generate a "Unit Test Harness" that uses pytest and ctypes to specifically test the memory boundaries of your C++ geometry kernel before you integrate it into the main POCO X6 Pro pipeline?**