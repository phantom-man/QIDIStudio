# Desktop Commander MCP — Integration Guide

## What is it?

[Desktop Commander MCP](https://github.com/wonderwhy-er/DesktopCommanderMCP) (v0.2.37, MIT, by Eduards Ruzga)
is a Model Context Protocol server that gives AI assistants direct terminal and filesystem access on the
host machine — without an API token budget.

In this repo it is:

- **Cloned** at `DesktopCommanderMCP/` (excluded from git — see `.gitignore`)
- **Already registered** in the VS Code / Copilot Chat MCP toolset under the `mcp_desktop-comma_*` tool prefix
- The backing process is managed by VS Code; no manual `npm install` or `node dist/index.js` needed for day-to-day use

---

## Available Tools (prefix: `mcp_desktop-comma_`)

| Tool                              | Purpose                                                   |
| --------------------------------- | --------------------------------------------------------- |
| `start_process`                   | Launch a shell command / REPL (returns PID)               |
| `interact_with_process`           | Send stdin to a running REPL, read response               |
| `list_sessions`                   | List all active shell sessions with PID + status          |
| `read_process_output`             | Non-blocking read of accumulated stdout                   |
| `start_search`                    | Async file-name or content search (returns session ID)    |
| `get_more_search_results`         | Paginate search results                                   |
| `stop_search`                     | Cancel an active search                                   |
| `edit_block`                      | Surgical find-replace in any text/Excel/DOCX/PDF file     |
| `read_file`                       | Read text, PDF, Excel (supports negative offset for tail) |
| `write_pdf`                       | Create or modify PDF from markdown                        |
| `get_config` / `set_config_value` | Inspect / change DC server config                         |
| `get_recent_tool_calls`           | Replay recent tool history for context recovery           |
| `get_prompts`                     | Load onboarding prompt by ID                              |

---

## PowerShell Quirks (Windows)

Desktop Commander uses **powershell.exe** as the default shell on Windows.

```powershell
# ✅ Correct — use semicolons
cd C:\path; python script.py; Write-Host Done

# ❌ Wrong — && is not valid in PowerShell
cd C:\path && python script.py
```

Other common gotchas:

- Environment variables: `$env:VAR` not `$VAR`
- `python3` may not exist — use `python` or full path
- Paths with spaces: wrap in `'single quotes'` inside strings
- Stderr is printed as `NativeCommandError` by PS — this is cosmetic, not fatal

---

## Common Workflows for This Repo

### Run a build

```powershell
# start_process with timeout_ms = 300000 (5 min)
cd C:\QIDISrc\QIDIStudio\build
C:\CMake329\bin\cmake.exe --build . --config RelWithDebInfo -- /m:16 2>&1 | Select-Object -Last 40
```

### Run tests

```powershell
cd C:\QIDISrc\QIDIStudio\build
C:\CMake329\bin\ctest.exe -C RelWithDebInfo --output-on-failure -j4 2>&1
```

### Memory sync (embed + upsert to LanceDB)

```powershell
cd C:\Users\User\source\repos\QIDIStudio
memory_env\Scripts\python.exe memory\extract.py 2>&1
```

### Search codebase

```json
{
  "path": "C:\\Users\\User\\source\\repos\\QIDIStudio\\src",
  "pattern": "apply_texture",
  "searchType": "content",
  "filePattern": "*.cpp"
}
```

### Surgical header edit

```json
{
  "file_path": "C:\\...\\src\\libslic3r\\SomeHeader.hpp",
  "old_string": "#ifndef slic3r_SomeHeader_hpp_\n#define slic3r_SomeHeader_hpp_",
  "new_string": "#pragma once"
}
```

---

## Session Management

```
PID: 51132  Blocked: true   Runtime: 36000s  ← long-lived background session (keep alive)
PID: 34332  Blocked: true   Runtime: 540s    ← memory sync (embedding model loading)
```

- `list_sessions` before launching expensive processes to avoid duplicates
- `force_terminate` (activate_process_control_tools) to kill stuck sessions
- Long-running REPLs (Python `-i`) survive across multiple `interact_with_process` calls

---

## Installation Reference

This directory contains the upstream source for reference/debugging.
The live MCP server is registered separately via the VS Code extension
settings (`mcp.servers` or `MCP: Add Server`).

To update to a newer DC version:

```powershell
cd C:\Users\User\source\repos\QIDIStudio\DesktopCommanderMCP
git pull
npm install
npm run build
# then update the registered server path if using local node dist/index.js
```

The npm-published version (`npx @wonderwhy-er/desktop-commander`) is the
recommended install path for most users; the cloned source is here for
auditability and local patching.

---

## Related Docs

- [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md) — LangGraph agent fleet (orchestrator, researcher, builder, verifier, scribe)
- [CPP_MODERNIZATION_SCORE.md](CPP_MODERNIZATION_SCORE.md) — current score and roadmap
- [QIDISTUDIO_KNOWLEDGE.md](QIDISTUDIO_KNOWLEDGE.md) — full architecture knowledge base
