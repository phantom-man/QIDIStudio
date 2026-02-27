$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$log  = Join-Path $repo '.github\hooks\precompact.log'

Set-Location $repo

git add .github/copilot-instructions.md docs/QIDISTUDIO_KNOWLEDGE.md

$staged = git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m 'docs: update knowledge + instructions [pre-compact]'
    Add-Content -Path $log -Value "$ts [PreCompact] committed"
} else {
    Add-Content -Path $log -Value "$ts [PreCompact] fired, nothing to commit"
}
