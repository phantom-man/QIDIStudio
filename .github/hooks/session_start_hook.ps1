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

Add-Content -Path $logFile -Value "$ts [SessionStart] fired"

# ── Read static knowledge base ────────────────────────────────────────────────
$additionalContext = ""

if (Test-Path $kbFile) {
    try {
        $kbContent = Get-Content $kbFile -Raw -Encoding UTF8 -ErrorAction Stop
        $additionalContext = "━━━ QIDISTUDIO KNOWLEDGE BASE ━━━`n$($kbContent.Trim())`n━━━ END KNOWLEDGE BASE ━━━"
        Add-Content -Path $logFile -Value "$ts [SessionStart] knowledge base injected ($($kbContent.Length) chars)"
    }
    catch {
        $additionalContext = "NOTE: QIDIStudio knowledge base read failed: $_"
        Add-Content -Path $logFile -Value "$ts [SessionStart] knowledge base read FAILED: $_"
    }
}
else {
    $additionalContext = "NOTE: QIDIStudio knowledge base not found at $kbFile"
    Add-Content -Path $logFile -Value "$ts [SessionStart] knowledge base not found: $kbFile"
}

# ── Emit hook response ────────────────────────────────────────────────────────
@{
    hookSpecificOutput = @{
        hookEventName     = 'SessionStart'
        additionalContext = $additionalContext
    }
} | ConvertTo-Json -Depth 4 -Compress
