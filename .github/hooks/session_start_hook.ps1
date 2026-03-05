# SessionStart hook — static knowledge base injection.
#
# Fires once at the beginning of every agent session.
# Injects the static knowledge base markdown file (memory/langsmith_prompt.md)
# as additionalContext — no Python, no LanceDB, no network required.
#
# Semantic / per-prompt LanceDB injection happens separately via the
# UserPromptSubmit hook which writes _last_prompt.txt for downstream use.
#
# NOTE: UserPromptSubmit does NOT support hookSpecificOutput.additionalContext
# (it uses the common output format only, per VS Code docs).
# SessionStart IS one of the supported events for additionalContext injection.

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$logFile = Join-Path $PSScriptRoot "precompact.log"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent  # hooks → .github → repo root
$kbFile = Join-Path $repo 'docs\QIDISTUDIO_KNOWLEDGE.md'
$today = Get-Date -Format 'yyyy-MM-dd'
$time = Get-Date -Format 'HH:mm:ss'

Add-Content -Path $logFile -Value "$ts [SessionStart] fired"

# ── Mandatory log protocol banner (always injected, cannot be missed) ─────────
$protocolBanner = @"
╔══════════════════════════════════════════════════════════════════════════════╗
║  MANDATORY FIRST ACTION — PROMPT EXECUTION PROTOCOL (copilot-instructions)  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Phase 0 MUST run before ANY other work. Steps in order:                    ║
║                                                                              ║
║  0.1  Scan logs/ for OPEN logs:                                              ║
║       grep -l '- [ ]' logs/*.md | xargs grep -l '## Status: OPEN'           ║
║       If found → ask user YES/NO to inherit before continuing.              ║
║                                                                              ║
║  0.2  Create session log IMMEDIATELY:                                        ║
║       File: logs/$today`_HHMMSS_<slug>.md                                    ║
║       (Get timestamp: Get-Date -Format 'yyyy-MM-dd_HHmmss')                 ║
║       Use the canonical template with Task Checklist + ## Status: OPEN      ║
║                                                                              ║
║  0.3  Check off each task as you complete it (replace_string_in_file).      ║
║  0.4  Set ## Status: COMPLETE when all tasks are [x].                       ║
║                                                                              ║
║  ⚠️  DO NOT run any tool, read any file, or make any edit until Step 0.2   ║
║     is done. The log file MUST be the first create_file call of the turn.   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"@
# ── Read static knowledge base ────────────────────────────────────────────────
$additionalContext = ""

if (Test-Path $kbFile) {
    try {
        $kbContent = Get-Content $kbFile -Raw -Encoding UTF8 -ErrorAction Stop
        $additionalContext = "$protocolBanner`n`n━━━ QIDISTUDIO KNOWLEDGE BASE ━━━`n$($kbContent.Trim())`n━━━ END KNOWLEDGE BASE ━━━"
        Add-Content -Path $logFile -Value "$ts [SessionStart] knowledge base injected ($($kbContent.Length) chars)"
    }
    catch {
        $additionalContext = "$protocolBanner`n`nNOTE: QIDIStudio knowledge base read failed: $_"
        Add-Content -Path $logFile -Value "$ts [SessionStart] knowledge base read FAILED: $_"
    }
}
else {
    $additionalContext = "$protocolBanner`n`nNOTE: QIDIStudio knowledge base not found at $kbFile"
    Add-Content -Path $logFile -Value "$ts [SessionStart] knowledge base not found: $kbFile"
}

# ── Emit hook response ────────────────────────────────────────────────────────
@{
    hookSpecificOutput = @{
        hookEventName     = 'SessionStart'
        additionalContext = $additionalContext
    }
} | ConvertTo-Json -Depth 4 -Compress
