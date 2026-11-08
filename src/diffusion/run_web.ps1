# Windows PowerShell: localhost 전용 Streamlit 웹 실행
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw '가상환경이 없습니다. 먼저 .\setup_windows.ps1 을 실행하세요.'
}
if (-not (Test-Path 'checkpoints\kr\stable_best.pt')) {
    throw '필수 학습 체크포인트 checkpoints\kr\stable_best.pt 가 없습니다.'
}
& $python -m streamlit run kr_report_web.py --server.address 127.0.0.1 --server.port 8501
