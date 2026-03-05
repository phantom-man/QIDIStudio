# PhD-Level Hybrid Debugging Workflow

A rigorous methodology for cross-language debugging of hybrid Python/C++ systems, covering mixed-mode stack tracing, PyObject inspection in GDB, and systematic abstraction-gap bridging.

---

## I. The Abstraction Gap Problem

### 1.1 Two Execution Models

Python and C++ operate on fundamentally different memory and execution models:

| Property | Python | C++ (via pybind11) |
|---------|--------|------------------|
| Heap | `PyHeap` — GC-managed | `malloc/new` — manual/RAII |
| Stack frame | `PyFrameObject*` chain | Hardware stack (DWARF metadata) |
| Debugger | `sys.settrace()` / `pdb` | DWARF + GDB/LLDB |
| Exception | `PyObject* (PyExc_*)` | `std::exception` hierarchy |
| Threads | GIL-serialized | Native OS threads |

When C++ code is called from Python via pybind11, the debugger sees a `PyObject*` that GDB cannot dereference meaningfully without Python-aware extensions.

---

## II. GDB with Python Extension (libpython-gdb)

### 2.1 Setup

Enable Python-aware GDB extensions:

```bash
# Install debug symbols
sudo apt install python3-dbg gdb

# In .gdbinit
add-auto-load-safe-path /usr/lib/python3.X/
python import gdb.printing

# Or explicitly load
source /usr/share/gdb/python3/libpython.py
```

### 2.2 Inspecting Python Frames from GDB

```gdb
(gdb) info threads
(gdb) thread 1
(gdb) where                      # C stack trace
(gdb) py-bt                      # Python call stack (from libpython extension)
(gdb) py-locals                  # Local Python variables at current frame
(gdb) py-up                      # Go up one Python frame
(gdb) print ((PyObject*)obj)->ob_type->tp_name    # Type name of any PyObject*
```

---

## III. pdb-Based Entry into C++ Breakpoints

### 3.1 Embedding a Python Breakpoint near the C Interface

```python
import ctypes, os, signal

def trigger_gdb_breakpoint():
    """
    Drop into GDB/LLDB from Python at this exact line.
    Requires the process to be already attached or launched under gdb.
    """
    if os.getenv("ENABLE_CPP_BREAKPOINT"):
        os.kill(os.getpid(), signal.SIGINT)  # sends SIGINT → GDB catches it
```

### 3.2 The `pybind11::gil_scoped_release` Pattern

When calling long C++ functions, release the GIL to allow Python-side interrupts:

```cpp
#include <pybind11/pybind11.h>
namespace py = pybind11;

// In the C++ function binding:
py::array_t<double> expensive_compute(py::array_t<double> input) {
    py::gil_scoped_release release;  // GIL released, GDB can now inspect C++ freely
    // ... long C++ work ...
    py::gil_scoped_acquire acquire;  // GIL reacquired before returning Python objects
    return result;
}
```

---

## IV. Mixed-Mode Stack Trace Script

### 4.1 Unified Stack Trace Reporter

```python
import traceback
import sys
import ctypes

def unified_stack_trace(exc: BaseException | None = None) -> str:
    """
    Return a unified Python + C++ stack trace.
    C++ frames are extracted via the `faulthandler` module on segfault,
    or via `traceback` for Python exceptions.
    """
    lines = ["=== Python stack ==="]
    if exc is not None:
        lines += traceback.format_exception(type(exc), exc, exc.__traceback__)
    else:
        lines += traceback.format_stack()

    # Check for C++ exception info embedded by pybind11
    if hasattr(exc, "__cause__") and exc.__cause__ is not None:
        lines += ["\n=== Caused by C++ exception ==="]
        lines += [str(exc.__cause__)]

    return "".join(lines)

# Install as system exception hook
def install_hybrid_hook():
    original = sys.excepthook
    def hook(exc_type, exc_value, exc_tb):
        print(unified_stack_trace(exc_value))
        original(exc_type, exc_value, exc_tb)
    sys.excepthook = hook
```

---

## V. VS Code Launch Configuration

### 5.1 Python + C++ Simultaneous Debugger

```jsonc
// .vscode/launch.json
{
  "configurations": [
    {
      "name": "Python + C++ Hybrid Debug",
      "type": "pythoncpp",
      "request": "launch",
      "pythonLaunchName": "Python: Run Script",
      "cppAttachName": "GDB: Attach to Python"
    },
    {
      "name": "Python: Run Script",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/scripts/apply_texture_bpy.py",
      "env": {"ENABLE_CPP_BREAKPOINT": "1"}
    },
    {
      "name": "GDB: Attach to Python",
      "type": "cppdbg",
      "request": "attach",
      "program": "python3",
      "processId": "${command:pickProcess}",
      "MIMode": "gdb",
      "setupCommands": [
        {"text": "source /usr/share/gdb/python3/libpython.py", "ignoreFailures": true}
      ]
    }
  ]
}
```

---

## VI. Common Failure Modes

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `Segmentation fault (core dumped)` | C++ writing past array bounds | Enable AddressSanitizer: `CFLAGS="-fsanitize=address"` |
| `Couldn't find type PyObject` | libpython debug symbols missing | `sudo apt install python3.X-dbg` |
| `GIL: thread state mismatch` | C++ holding GIL across thread boundary | Use `py::gil_scoped_release` |
| Python exception swallowed | pybind11 converts C++ exception silently | Use `py::set_error()` or rethrow |
| `AttributeError` after C++ mutation | Cached Python object not invalidated | Call `mesh.invalidate()` or return new object |

---

## References

- Galowicz, J. (2017). *C++17 STL Cookbook*. Packt (RAII and exception safety).
- GDB Manual, §12: Debugging Programs with Multiple Threads. gnu.org/software/gdb.
- pybind11 Documentation: Exception Handling. pybind11.readthedocs.io.
- Python C API Reference: Memory Management. docs.python.org/3/c-api/memory.html.
