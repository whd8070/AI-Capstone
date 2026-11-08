# Windows PowerShell: AI-Capstone/src/diffusion 초기 설정 (Python 3.11)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 실행기를 찾지 못했습니다. Python 3.11을 설치해 주세요.' }
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip 업데이트 실패' }
& $python -m pip install -r requirements_kr_report_web.txt
if ($LASTEXITCODE -ne 0) { throw '의존성 설치 실패' }
& $python -m ipykernel install --user --name ai-capstone-kr --display-name 'AI-Capstone KR (.venv)'
if ($LASTEXITCODE -ne 0) { throw 'Jupyter 커널 등록 실패' }
& $python -m unittest test_kr_pair_cpu test_kr_report_engine test_kr_report_status -v
if ($LASTEXITCODE -ne 0) { throw '오프라인 테스트가 실패했습니다. 위 로그를 확인하세요.' }
Write-Host "설치 및 테스트 완료. 실행: .\run_web.ps1" -ForegroundColor Green
