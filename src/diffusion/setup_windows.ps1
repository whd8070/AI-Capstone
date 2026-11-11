# First-run Windows setup. ASCII source is compatible with Windows PowerShell 5.1.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$venvDir = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$requirements = Join-Path $PSScriptRoot 'requirements_kr_report_web.txt'
$checkpoint = Join-Path $PSScriptRoot 'checkpoints\kr\stable_best.pt'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$consensus = Join-Path $repoRoot 'agents\collection\data\handoff\daily_consensus.csv'
$compact = Join-Path $repoRoot 'agents\collection\data\handoff\reports_compact.jsonl'

foreach ($file in @($requirements, $checkpoint, $consensus, $compact)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Required repository file is missing: $file. Check that the clone is complete."
    }
}
if ((Get-Item -LiteralPath $checkpoint).Length -lt 1024) {
    throw "The model checkpoint is suspiciously small: $checkpoint. Restore the real stable_best.pt (not a Git LFS pointer)."
}

function Test-Python311X64 {
    param([string]$Exe, [string[]]$Prefix = @())
    try {
        $probe = & $Exe @Prefix -c 'import sys; print(sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32)' 2>$null
        return ($LASTEXITCODE -eq 0 -and "$probe".Trim() -eq 'True')
    } catch {
        return $false
    }
}

if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    if (-not (Test-Python311X64 -Exe $venvPython)) {
        throw "Existing .venv is not a working Python 3.11 (64-bit) environment: $venvDir. Rename that directory and run setup again."
    }
    Write-Host '[setup] Reusing Python 3.11 environment.' -ForegroundColor Cyan
} else {
    if (Test-Path -LiteralPath $venvDir) {
        throw "An incomplete .venv exists at $venvDir. Rename it and run setup again."
    }
    $candidates = @(
        @{ Exe = 'py'; Prefix = @('-3.11') },
        @{ Exe = 'python'; Prefix = @() },
        @{ Exe = 'python3'; Prefix = @() }
    )
    $selected = $null
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        if (Test-Python311X64 -Exe $candidate.Exe -Prefix $candidate.Prefix) {
            $selected = $candidate
            break
        }
    }
    if ($null -eq $selected) {
        throw 'Python 3.11 (64-bit) was not found. Install it from https://www.python.org/downloads/ (enable the Python launcher if offered), reopen the terminal, and run start_windows.cmd again. Python 3.12/3.13 is not the supported version for this project.'
    }
    Write-Host "[setup] Creating environment with $($selected.Exe) $($selected.Prefix -join ' ')" -ForegroundColor Cyan
    $launcher = $selected.Exe
    $launcherArgs = $selected.Prefix
    & $launcher @launcherArgs -m venv $venvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw 'Unable to create .venv. Check Python installation, disk space, and folder permissions.'
    }
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Write-Host '[setup] Installing web dependencies (first run may download PyTorch).' -ForegroundColor Cyan
& $venvPython -m pip install --disable-pip-version-check --prefer-binary -r $requirements
if ($LASTEXITCODE -ne 0) {
    throw 'Dependency installation failed. Check network/proxy access and the pip error above. Existing files were not deleted.'
}
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Installed Python dependencies are inconsistent (pip check failed).' }

Write-Host '[setup] Checking required Python imports...' -ForegroundColor Cyan
# Run a real .py file: Windows PowerShell 5.1 strips nested double quotes from -c arguments.
# The previous -c one-liner produced NameError: name 'numpy' is not defined.
$importCheck = Join-Path $PSScriptRoot 'check_windows_imports.py'
if (-not (Test-Path -LiteralPath $importCheck -PathType Leaf)) {
    throw "Missing import validation script: $importCheck. Run git pull origin main."
}
& $venvPython $importCheck
if ($LASTEXITCODE -ne 0) {
    throw 'Python import check failed. If torch reports a DLL error, install the Microsoft Visual C++ 2015-2022 x64 Redistributable and rerun setup.'
}
Write-Host '[setup] Ready. Start the web app with start_windows.cmd or run_web.ps1.' -ForegroundColor Green
