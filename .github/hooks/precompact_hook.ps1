# PreCompact hook — fires when context is about to be compacted.
# Lightweight: ONLY writes the compaction flag + brief agent reminder.
# Heavy work (extract.py + commit) is handled by the Stop hook automatically.

$ts   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$log  = Join-Path $repo '.github\hooks\precompact.log'
$flag = Join-Path $repo 'memory\_compaction_pending.txt'

Add-Content -Path $log -Value "$ts [PreCompact] fired — writing flag"
Set-Content -Path $flag -Value $ts -Encoding UTF8

# Minimal agent instruction: write learnings NOW before context is gone.
# extract.py + commit run automatically in the Stop hook — no manual steps needed.
@{
  hookSpecificOutput = @{
    hookEventName     = 'PreCompact'
    additionalContext = @"
Context compaction imminent. ONE task before context is lost:

Append new learnings to .github/copilot-instructions.md Session Learnings Log:
  | $(Get-Date -Format 'yyyy-MM-dd') | <category> | <topic> | <decision> | <rationale> |

Be specific: real function names, file paths, confirmed values. No vague summaries.
Extract.py + commit will run automatically in the Stop hook — you do NOT need to do that.
"@
  }
} | ConvertTo-Json -Compress
