#!/usr/bin/env bash
# Fast restart after setup. This does not install packages or pull Git changes.
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd -P)"
project="$root/src/diffusion"
python="$project/.venv/bin/python"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "[ERROR] This launcher is for macOS only." >&2
  exit 1
fi
if [[ ! -x "$python" ]]; then
  echo "[ERROR] .venv is missing. First run: bash ./start_mac.sh" >&2
  exit 1
fi
if [[ ! -s "$project/checkpoints/kr/stable_best.pt" ]]; then
  echo "[ERROR] Frozen model checkpoint is missing: $project/checkpoints/kr/stable_best.pt" >&2
  exit 1
fi
cd "$project"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
echo "[AI-Capstone] Starting web at http://127.0.0.1:8501 (Ctrl+C to stop)."
exec "$python" -m streamlit run "$project/kr_report_web.py" --server.address 127.0.0.1 --server.port 8501
