# Interactive local onboarding launched only after an explicit click in the Streamlit UI.
# Authentication happens in the user's own terminal/browser. Do not log or collect tokens.
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('codex','claude')]
    [string]$Provider,
    [Parameter(Mandatory=$true)]
    [ValidateSet('install','login')]
    [string]$Action
)
$ErrorActionPreference = 'Stop'

function Refresh-Path {
    # The running Streamlit server may have an old PATH after installers finish.
    $userPath = [Environment]::GetEnvironmentVariable('Path','User')
    $machinePath = [Environment]::GetEnvironmentVariable('Path','Machine')
    $env:Path = "$userPath;$machinePath;$env:Path"
    $dirs = @(
        (Join-Path $HOME '.local\bin'),
        (Join-Path $env:APPDATA 'npm'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links')
    )
    foreach ($d in $dirs) {
        if ((Test-Path -LiteralPath $d -PathType Container) -and ($env:Path -notlike "*$d*")) {
            $env:Path = "$d;$env:Path"
        }
    }
}

function Resolve-Cli {
    param([string]$Key)
    Refresh-Path
    $base = if ($Key -eq 'codex') { 'codex' } else { 'claude' }
    $candidates = @(
        (Join-Path $HOME ".local\bin\$base.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\$base.exe"),
        (Join-Path $env:APPDATA "npm\$base.cmd")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    $found = Get-Command $base -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found -and $found.Source) { return $found.Source }
    return $null
}

Write-Host ''
Write-Host "AI-Capstone | $Provider CLI | $Action" -ForegroundColor Cyan
Write-Host 'This is a local terminal. Enter account credentials only on the official sign-in screen.'
Write-Host ''
try {
    if ($Action -eq 'install') {
        $existing = Resolve-Cli -Key $Provider
        if ($existing) {
            Write-Host "Already installed: $existing" -ForegroundColor Green
        } elseif ($Provider -eq 'claude') {
            # Official Windows package or native installer; Node.js is not required.
            $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
            if ($winget) {
                Write-Host 'Installing official Anthropic.ClaudeCode via winget...'
                & $winget.Source install --id Anthropic.ClaudeCode --exact --source winget --accept-source-agreements --accept-package-agreements
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning 'winget failed. Trying the official native installer.'
                }
            }
            if (-not (Resolve-Cli -Key 'claude')) {
                Write-Host 'Running the official Claude Code Windows installer...'
                Invoke-RestMethod 'https://claude.ai/install.ps1' | Invoke-Expression
            }
        } else {
            # Official Codex Windows standalone install: no npm/Node.js prerequisite.
            Write-Host 'Running the official Codex CLI Windows installer...'
            Invoke-RestMethod 'https://chatgpt.com/codex/install.ps1' | Invoke-Expression
        }
        $installed = Resolve-Cli -Key $Provider
        if ($installed) {
            Write-Host "Installation found: $installed" -ForegroundColor Green
            Write-Host 'Return to web page 3, click [Recheck connection], then open the login terminal.'
        } else {
            Write-Warning 'Installer finished but the executable is not visible yet. Close/reopen the web server if PATH has not propagated.'
            Write-Host 'Codex: https://github.com/openai/codex'
            Write-Host 'Claude: https://github.com/anthropics/claude-code'
        }
    } else {
        $exe = Resolve-Cli -Key $Provider
        if (-not $exe) {
            throw "$Provider CLI is not installed. Use the Install button in web page 3 first."
        }
        Write-Host "Using: $exe"
        Write-Host 'A browser may open. Complete sign-in there, then return to this terminal.'
        if ($Provider -eq 'codex') {
            & $exe login
            if ($LASTEXITCODE -ne 0) { throw 'Codex login did not succeed.' }
            & $exe login status
            if ($LASTEXITCODE -ne 0) { throw 'Codex authentication check failed.' }
        } else {
            & $exe auth login
            if ($LASTEXITCODE -ne 0) { throw 'Claude login did not succeed.' }
            & $exe auth status
            if ($LASTEXITCODE -ne 0) { throw 'Claude authentication check failed.' }
        }
        Write-Host 'Login complete. Click [Recheck connection] on web page 3.' -ForegroundColor Green
    }
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'You can retry with the button on web page 3.'
}
Write-Host ''
Write-Host 'This window stays open so you can read the result. Close it when finished.'
