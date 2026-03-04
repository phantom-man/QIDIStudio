# PreCompact hook — fires when context is about to be compacted.
# Lightweight: ONLY writes the compaction flag + brief agent reminder.
# The Stop hook captures the response and stores it in the prompts/responses DB.
# The 30-min sync job pushes it to LanceDB. No manual steps needed.

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$log = Join-Path $repo '.github\hooks\precompact.log'
$flag = Join-Path $repo 'memory\_compaction_pending.txt'

Add-Content -Path $log -Value "$ts [PreCompact] fired — writing flag"
Set-Content -Path $flag -Value $ts -Encoding UTF8

# Instruct the agent to write a compaction summary IN ITS RESPONSE.
# The Stop hook will capture this response and store it in the DB with is_compaction=TRUE.
# The 30-min sync job will push it to LanceDB and write compaction_summaries.md.
# DO NOT write to copilot-instructions.md — learnings live in Postgres/LanceDB now.
@{
  hookSpecificOutput = @{
    hookEventName     = 'PreCompact'
    additionalContext = @"
Context compaction imminent. Include a COMPACTION_SUMMARY block in your NEXT response:

COMPACTION_SUMMARY: yes
Key decisions this session:
  - [decision 1: specific function/file/value]
  - [decision 2]
Key gotchas / bugs found:
  - [gotcha 1]
Files modified:
  - [file: what was changed]

Be specific: real function names, file paths, confirmed values.
This block will be automatically captured to the knowledge database — you do NOT need to
write to copilot-instructions.md or run extract.py. The sync job handles both.
"@
  }
} | ConvertTo-Json -Compress
