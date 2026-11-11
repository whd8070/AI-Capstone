<#
AI-Capstone Windows 11 first-run bootstrap.
Runs in Windows PowerShell 5.1 without Git or Python.
Installs missing tools, registers user PATH, clones safely, sets up and starts the web.
#>
param(
    [string]$Destination = '',
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This bootstrap is for Windows only.'
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'A 64-bit Windows 11 environment is required.'
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step {
    param([string]$Message)
    Write-Host "[AI-Capstone] $Message" -ForegroundColor Cyan
}

function Test-Python311 {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $result = & $Path -c 'import sys; print(sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32)' 2>$null
        return ($LASTEXITCODE -eq 0 -and "$result".Trim() -eq 'True')
    } catch { return $false }
}

function Find-Python311 {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        try {
            $exe = & $launcher.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Python311 -Path "$exe".Trim())) {
                return "$exe".Trim()
            }
        } catch {}
    }
    $candidates = New-Object System.Collections.Generic.List[string]
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311'),
        (Join-Path $env:ProgramFiles 'Python311')
    )
    $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    if ($programFilesX86) { $roots += (Join-Path $programFilesX86 'Python311') }
    foreach ($root in $roots) { $candidates.Add((Join-Path $root 'python.exe')) }
    foreach ($commandName in @('python.exe','python3.exe')) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source) { $candidates.Add($command.Source) }
    }
    foreach ($candidate in $candidates) {
        if (Test-Python311 -Path $candidate) { return $candidate }
    }
    return $null
}

function Find-Git {
    $known = New-Object System.Collections.Generic.List[string]
    $command = Get-Command git.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command -and $command.Source) { $known.Add($command.Source) }
    $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    foreach ($base in @($env:ProgramFiles, $programFilesX86, $env:LOCALAPPDATA)) {
        if (-not $base) { continue }
        $known.Add((Join-Path $base 'Git\cmd\git.exe'))
        $known.Add((Join-Path $base 'Programs\Git\cmd\git.exe'))
    }
    foreach ($path in $known) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        try {
            $null = & $path --version 2>$null
            if ($LASTEXITCODE -eq 0) { return $path }
        } catch {}
    }
    return $null
}

function Add-UserPath {
    param([string[]]$Folders)
    $existing = [Environment]::GetEnvironmentVariable('Path','User')
    $parts = @($existing -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $known = @($parts | ForEach-Object { $_.Trim().Trim('"').TrimEnd('\').ToLowerInvariant() })
    foreach ($folder in $Folders) {
        if (-not $folder -or -not (Test-Path -LiteralPath $folder -PathType Container)) { continue }
        $normalized = $folder.TrimEnd('\').ToLowerInvariant()
        if ($normalized -notin $known) {
            $parts += $folder
            $known += $normalized
        }
        $sessionEntries = @($env:Path -split ';' | ForEach-Object { $_.Trim().Trim('"').TrimEnd('\').ToLowerInvariant() })
        if ($normalized -notin $sessionEntries) { $env:Path = "$folder;$env:Path" }
    }
    $newPath = $parts -join ';'
    if ($newPath.Length -gt 30000) { throw 'The user PATH is too long; please remove obsolete entries.' }
    if ($newPath -ne $existing) {
        [Environment]::SetEnvironmentVariable('Path',$newPath,'User')
        Write-Step 'Git/Python directories added to the user PATH and current process.'
    }
}

function Try-WingetInstall {
    param([string]$PackageId)
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $winget) {
        Write-Warning 'winget not found; trying official signed installers.'
        return $false
    }
    Write-Step "Installing $PackageId with winget..."
    try {
        & $winget.Source install --id $PackageId --exact --source winget --scope user --architecture x64 --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { return $true }
        Write-Warning "winget returned exit code $LASTEXITCODE. Trying official installer."
    } catch {
        Write-Warning ("winget failed for {0}: {1}" -f $PackageId,$_.Exception.Message)
    }
    return $false
}

function Download-SignedInstaller {
    param([string]$Url,[string]$Path,[string]$PublisherPattern='')
    Write-Step "Downloading official installer: $Url"
    Invoke-WebRequest -Uri $Url -UseBasicParsing -OutFile $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Download failed: $Url"
    }
    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne 'Valid') {
        throw "Installer signature not valid ($($signature.Status)): $Url"
    }
    if ($PublisherPattern -and $signature.SignerCertificate.Subject -notmatch $PublisherPattern) {
        throw "Unexpected installer publisher: $Url"
    }
}

function Install-GitDirect {
    param([string]$TempFolder)
    Write-Step 'Finding the latest Git for Windows installer...'
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/git-for-windows/git/releases/latest' -Headers @{
        'User-Agent' = 'AI-Capstone-Windows-Bootstrap'
        'Accept' = 'application/vnd.github+json'
    }
    $asset = $release.assets | Where-Object { $_.name -match '^Git-[0-9].*-64-bit\.exe$' } | Select-Object -First 1
    if (-not $asset -or $asset.browser_download_url -notlike 'https://github.com/git-for-windows/git/releases/download/*') {
        throw 'Official Git x64 installer not found: https://git-scm.com/install/windows'
    }
    $installer = Join-Path $TempFolder 'git-setup.exe'
    Download-SignedInstaller -Url $asset.browser_download_url -Path $installer
    Write-Step 'Installing Git for this Windows user...'
    $proc = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/NORESTART','/CURRENTUSER','/SP-') -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw "Git installer failed (exit $($proc.ExitCode))." }
}

function Install-PythonDirect {
    param([string]$TempFolder)
    # 3.11.9 is the last official Python 3.11 Windows executable installer.
    $url = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe'
    $installer = Join-Path $TempFolder 'python-3.11.9-amd64.exe'
    Download-SignedInstaller -Url $url -Path $installer -PublisherPattern 'Python Software Foundation'
    Write-Step 'Installing Python 3.11 x64 for this Windows user...'
    $proc = Start-Process -FilePath $installer -ArgumentList @(
        '/quiet','InstallAllUsers=0','PrependPath=1','Include_pip=1',
        'Include_launcher=0','Include_test=0','Shortcuts=0'
    ) -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw "Python installer failed (exit $($proc.ExitCode))." }
}

Write-Step 'Checking Git and Python 3.11...'
$git = Find-Git
$python = Find-Python311
$tempFolder = Join-Path $env:TEMP ('AI-Capstone-setup-' + [guid]::NewGuid().ToString('N'))
try {
    if (-not $git -or -not $python) {
        New-Item -ItemType Directory -Path $tempFolder -Force | Out-Null
    }
    if (-not $git) {
        $null = Try-WingetInstall -PackageId 'Git.Git'
        $git = Find-Git
        if (-not $git) {
            Install-GitDirect -TempFolder $tempFolder
            $git = Find-Git
        }
        if (-not $git) { throw 'Git not found after installation. See https://git-scm.com/install/windows.' }
    } else { Write-Step 'Git already installed: skipping.' }
    if (-not $python) {
        $null = Try-WingetInstall -PackageId 'Python.Python.3.11'
        $python = Find-Python311
        if (-not $python) {
            Install-PythonDirect -TempFolder $tempFolder
            $python = Find-Python311
        }
        if (-not $python) { throw 'Python 3.11 x64 not found after installation.' }
    } else { Write-Step 'Python 3.11 x64 already installed: skipping.' }
} finally {
    if (Test-Path -LiteralPath $tempFolder) {
        Remove-Item -LiteralPath $tempFolder -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Add-UserPath -Folders @(
    (Split-Path -Path $git -Parent),
    (Split-Path -Path $python -Parent),
    (Join-Path (Split-Path -Path $python -Parent) 'Scripts')
)
Write-Host ('[AI-Capstone] ' + (& $git --version))
Write-Host ('[AI-Capstone] ' + (& $python --version))

if (-not $Destination) {
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'src\diffusion\setup_windows.ps1')) {
        $Destination = $PSScriptRoot
    } else {
        $Destination = Join-Path $env:USERPROFILE 'AI-Capstone'
    }
}
$Destination = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $Destination) {
    if (-not (Test-Path -LiteralPath (Join-Path $Destination '.git'))) {
        throw "Destination exists but is not a Git clone: $Destination. Use another -Destination; existing files will not be overwritten."
    }
    Write-Step "Using existing clone: $Destination. To update it, run git pull manually."
} else {
    $parent = Split-Path -Path $Destination -Parent
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Write-Step "Cloning project into $Destination..."
    & $git clone --branch main --single-branch 'https://github.com/whd8070/AI-Capstone.git' $Destination
    if ($LASTEXITCODE -ne 0) { throw "Git clone failed: $Destination" }
}

$diffusion = Join-Path $Destination 'src\diffusion'
$setup = Join-Path $diffusion 'setup_windows.ps1'
$run = Join-Path $diffusion 'run_web.ps1'
if (-not (Test-Path -LiteralPath $setup -PathType Leaf) -or
    -not (Test-Path -LiteralPath $run -PathType Leaf)) {
    throw "Required web setup scripts are missing from $Destination."
}
Write-Step 'Installing the project Python environment...'
& $setup
if ($NoLaunch) {
    Write-Step "Setup complete. To start later: $Destination\start_windows.cmd"
    exit 0
}
Write-Step 'Starting the local web...'
& $run
