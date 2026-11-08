# Optional: Claude Code CLI and persistent user PATH (login remains manual).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$binDir = Join-Path $HOME '.local\bin'
$exe = Join-Path $binDir 'claude.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Host 'Installing Claude Code CLI via official installer...'
    irm https://claude.ai/install.ps1 | iex
}
if (-not (Test-Path -LiteralPath $exe)) { throw "Claude executable not found: $exe" }
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$entries = @($userPath -split ';' | Where-Object { $_ -and $_.Trim() })
$norm = { param($p) $p.Trim().TrimEnd('\').ToLowerInvariant() }
$exists = @($entries | Where-Object { (& $norm $_) -eq (& $norm $binDir) }).Count -gt 0
if (-not $exists) {
    [Environment]::SetEnvironmentVariable('Path', (($entries + @($binDir)) -join ';'), 'User')
    Write-Host "PATH registered: $binDir"
}
if (-not (@($env:Path -split ';' | Where-Object { (& $norm $_) -eq (& $norm $binDir) }).Count -gt 0)) {
    $env:Path = "$binDir;$env:Path"
}
& $exe --version
if ($LASTEXITCODE -ne 0) { throw 'Claude CLI check failed' }
Write-Host 'Claude CLI PATH ready. Next (manually): claude auth login'
Write-Host 'To verify login: claude auth status'
