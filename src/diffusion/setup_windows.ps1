# Windows PowerShell: 웹 실행용 최소 Python 환경만 설치 (Python 3.11)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11이 필요합니다.' }
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install -r requirements_kr_report_web.txt
if ($LASTEXITCODE -ne 0) { throw '웹 의존성 설치 실패' }
Write-Host '웹 의존성 설치 완료. 실행: .\run_web.ps1' -ForegroundColor Green
