# Run the local Streamlit app from its own virtual environment.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$checkpoint = Join-Path $PSScriptRoot 'checkpoints\kr\stable_best.pt'
$web = Join-Path $PSScriptRoot 'kr_report_web.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Python environment not found. Run start_windows.cmd from the repository root first.'
}
if (-not (Test-Path -LiteralPath $checkpoint -PathType Leaf)) {
    throw "Model checkpoint not found: $checkpoint"
}
if (-not (Test-Path -LiteralPath $web -PathType Leaf)) {
    throw "Web entry point not found: $web"
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Write-Host '[web] Starting at http://127.0.0.1:8501 (Ctrl+C to stop)' -ForegroundColor Cyan
& $python -m streamlit run $web --server.address 127.0.0.1 --server.port 8501
if ($LASTEXITCODE -ne 0) {
    throw 'Streamlit stopped with an error. See the output above. If port 8501 is in use, close the other Streamlit process.'
}
