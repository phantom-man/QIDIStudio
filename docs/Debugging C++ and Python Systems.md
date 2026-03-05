# Systematic Debugging of C++ and Python Systems

A methodical reference for diagnosing memory errors, undefined behavior, and cross-language failures in mixed C++/Python systems — covering sanitizers, dynamic analysis tools, GDB watchpoints, Python `faulthandler`, and hybrid stack trace reconstruction.

---

## I. Memory Error Taxonomy

| Error Class | Tool | Detection Rate |
|-------------|------|---------------|
| Heap buffer overflow | AddressSanitizer | ~99% |
| Stack buffer overflow | AddressSanitizer | ~95% |
| Use-after-free | AddressSanitizer | ~99% |
| Uninitialized reads | MemorySanitizer | ~90% |
| Integer overflow | UndefinedBehaviorSanitizer | ~85% |
| Null dereference | UBSan + ASAN | ~95% |
| Data races (threads) | ThreadSanitizer | ~80% |
| Memory leaks | LeakSanitizer | ~95% |

---

## II. Sanitizer Compiler Flags

```cmake
# CMakeLists.txt — debug/sanitizer build
option(ENABLE_ASAN "Address + Leak sanitizer" OFF)
option(ENABLE_UBSAN "Undefined behavior sanitizer" OFF)
option(ENABLE_TSAN "Thread sanitizer" OFF)

if (ENABLE_ASAN)
    add_compile_options(-fsanitize=address,leak -fno-omit-frame-pointer -g)
    add_link_options(-fsanitize=address,leak)
endif()

if (ENABLE_UBSAN)
    add_compile_options(-fsanitize=undefined -fno-omit-frame-pointer -g)
    add_link_options(-fsanitize=undefined)
endif()

if (ENABLE_TSAN)
    add_compile_options(-fsanitize=thread -fno-omit-frame-pointer -g)
    add_link_options(-fsanitize=thread)
endif()
```

Usage:

```bash
cmake -B build -DENABLE_ASAN=ON -DCMAKE_BUILD_TYPE=Debug
cmake --build build --target my_app
./build/my_app  # ASAN will print violations to stderr
```

---

## III. GDB: Advanced Breakpoints and Watchpoints

### 3.1 Conditional Breakpoint

```gdb
(gdb) break mesh.cpp:142 if vertex_count > 100000
(gdb) commands 1
> bt
> print *this
> continue
> end
```

### 3.2 Watchpoints (Detect Write to Variable)

```gdb
(gdb) watch -l m_faces[42]   # hardware watchpoint on m_faces[42]
(gdb) rwatch m_dirty_flag    # break when m_dirty_flag is READ
(gdb) awatch m_vertex_count  # break on read OR write
```

### 3.3 Python Stack in GDB

With `python3-dbg` and libpython debug symbols:

```gdb
(gdb) py-bt     # Python backtrace from C extension
(gdb) py-list   # Python source context
(gdb) py-print x  # Inspect Python variable
```

---

## IV. Python faulthandler — Crash Diagnostics

`faulthandler` prints a Python traceback on SIGSEGV/SIGFPE — even in C extensions:

```python
import faulthandler
import sys

# Enable before any C extension loads
faulthandler.enable()

# Periodically dump to file every 5s (for hanging processes)
faulthandler.dump_traceback_later(timeout=5.0, file=open("crash.log", "w"), repeat=True)
```

For subprocess invocation:

```bash
python -X faulthandler my_script.py
```

---

## V. Hybrid Stack Trace Reconstruction

For C++ extensions called from Python, a full trace requires both layers:

```python
import traceback
import ctypes
import subprocess

def get_hybrid_trace() -> str:
    """Combine Python traceback with GDB C++ frames for current process."""
    py_trace = "".join(traceback.format_stack())
    pid = os.getpid()
    gdb_cmd = f"gdb -p {pid} -batch -ex 'bt' -ex 'quit'"
    result = subprocess.run(gdb_cmd, shell=True, capture_output=True, text=True)
    return f"=== Python ===\n{py_trace}\n=== C++ (GDB) ===\n{result.stdout}"
```

---

## VI. Valgrind Memcheck

```bash
valgrind --tool=memcheck \
         --leak-check=full \
         --show-leak-kinds=all \
         --track-origins=yes \
         --suppressions=/usr/share/valgrind/python3.supp \
         python my_script.py 2>&1 | tee valgrind.log
```

Valgrind typical output:

```
==12345== Invalid read of size 4
==12345==    at 0x4C2F678: mesh_get_vertex (mesh.cpp:87)
==12345==  Address 0x5204e40 is 0 bytes after a block of 2048 alloc'd
==12345==    at 0x4C2AB80: operator new[] (in vg_replace_malloc.so)
```

---

## VII. Failure Mode Matrix

| Symptom | Likely cause | First diagnostic step |
|---------|-------------|----------------------|
| SIGSEGV in `.pyd` | Buffer overflow or null deref | ASAN + GDB `py-bt` |
| Memory growing unbounded | Leak: Python ref-cycle or C malloc | LeakSanitizer + `tracemalloc` |
| Deadlock in `std::mutex` | Thread ordering issue | TSAN + GDB `info threads` |
| NaN propagation | Uninitialized float | MSan + print first NaN frame |
| Race on global | Missing lock | TSAN report |

---

## References

- Seyer, G. et al. (2022). AddressSanitizer: A fast address sanity checker. *USENIX ATC*.
- GDB Project (2023). GDB: The GNU Project Debugger. gnu.org/software/gdb.
- CPython (2023). faulthandler — Dump the Python traceback. docs.python.org/3/library/faulthandler.
- Nethercote, N. & Seward, J. (2007). Valgrind. *ACM SIGPLAN Notices*, 42(6).
