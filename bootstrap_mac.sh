#!/usr/bin/env bash
# macOS bootstrap: first install or repair only; use run_mac.sh for daily launches.
set -euo pipefail
if [[ "$(uname -s)" != "Darwin" ]]; then echo "[ERROR] macOS only" >&2; exit 1; fi
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
DEST=""
NO_LAUNCH=0
while (( $# )); do
  case "$1" in
    --destination) [[ $# -ge 2 ]] || { echo "Missing destination" >&2; exit 2; }; DEST="$2"; shift 2 ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
if [[ -z "$DEST" ]]; then
  if [[ -f "$ROOT/src/diffusion/kr_report_web.py" ]]; then DEST="$ROOT"; else DEST="$HOME/AI-Capstone"; fi
fi
if [[ "$DEST" != /* ]]; then echo "[ERROR] Use an absolute destination path" >&2; exit 1; fi
echo "[setup] macOS target: $DEST"
if ! command -v git >/dev/null 2>&1 || ! git --version >/dev/null 2>&1; then
  echo "[setup] Git requires Apple Command Line Tools. Starting official macOS installer."
  xcode-select --install || true
  echo "[ACTION] Complete the Apple installation dialog, then run the setup command again."
  exit 2
fi
BREW=""
if command -v brew >/dev/null 2>&1; then BREW="$(command -v brew)"; fi
for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  if [[ -z "$BREW" && -x "$p" ]]; then BREW="$p"; fi
done
PYTHON=""
for p in "$(command -v python3.11 2>/dev/null || true)" /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
  if [[ -n "$p" && -x "$p" ]] && "$p" -c "import sys; assert sys.version_info[:2] == (3,11) and sys.maxsize > 2**32" >/dev/null 2>&1; then
    PYTHON="$p"; break
  fi
done
if [[ -z "$PYTHON" ]]; then
  if [[ -z "$BREW" ]]; then
    echo "[setup] Python 3.11 is not installed. Homebrew will be installed from its official script."
    if [[ ! -t 0 ]]; then echo "[ERROR] Interactive terminal required for Homebrew installation" >&2; exit 1; fi
    read -r -p "Install Homebrew (official installer)? [y/N] " ANSWER
    if [[ "$ANSWER" != "y" && "$ANSWER" != "Y" ]]; then echo "[ACTION] Install Homebrew from https://brew.sh and rerun."; exit 2; fi
    TMPFILE="$(mktemp /tmp/ai-capstone-brew.XXXXXX)"
    trap 'rm -f "$TMPFILE"' EXIT
    curl -fL --retry 2 --connect-timeout 15 "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh" -o "$TMPFILE"
    /bin/bash "$TMPFILE"
    rm -f "$TMPFILE"
    trap - EXIT
    for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do if [[ -x "$p" ]]; then BREW="$p"; break; fi; done
    if [[ -z "$BREW" ]]; then echo "[ERROR] brew not found after install" >&2; exit 1; fi
  fi
  eval "$("$BREW" shellenv)"
  "$BREW" install python@3.11
  PYTHON="$("$BREW" --prefix python@3.11)/bin/python3.11"
fi
if [[ -n "$BREW" ]]; then
  eval "$("$BREW" shellenv)"
  PROFILE="$HOME/.zprofile"
  BREW_LINE="eval \"\$($BREW shellenv)\""
  if [[ ! -f "$PROFILE" ]] || ! grep -Fqx "$BREW_LINE" "$PROFILE"; then
    printf "\n%s\n" "$BREW_LINE" >> "$PROFILE"
    echo "[setup] Homebrew PATH registered for future Terminal windows: $PROFILE"
  fi
fi
if [[ ! -x "$PYTHON" ]] || ! "$PYTHON" -c "import sys; assert sys.version_info[:2] == (3,11) and sys.maxsize > 2**32" >/dev/null 2>&1; then
  echo "[ERROR] Python 3.11 not available" >&2; exit 1
fi
echo "[setup] $(git --version) / $("$PYTHON" --version)"
if [[ -e "$DEST" ]]; then
  if [[ ! -d "$DEST/.git" ]]; then echo "[ERROR] Existing target is not a git clone: $DEST" >&2; exit 1; fi
  echo "[setup] Existing checkout retained; no automatic git pull."
else
  mkdir -p "$(dirname "$DEST")"
  git clone --branch main --single-branch https://github.com/whd8070/AI-Capstone.git "$DEST"
fi
APP="$DEST/src/diffusion"
for f in "$APP/kr_report_web.py" "$APP/requirements_kr_report_web.txt" "$APP/checkpoints/kr/stable_best.pt" "$DEST/agents/collection/data/handoff/daily_consensus.csv" "$DEST/agents/collection/data/handoff/reports_compact.jsonl" "$APP/check_windows_imports.py"; do
  if [[ ! -f "$f" ]]; then echo "[ERROR] Required file missing: $f" >&2; exit 1; fi
done
if [[ ! -s "$APP/checkpoints/kr/stable_best.pt" ]]; then echo "[ERROR] Empty checkpoint" >&2; exit 1; fi
VENV="$APP/.venv"
if [[ -e "$VENV" ]]; then
  if [[ ! -x "$VENV/bin/python" ]] || ! "$VENV/bin/python" -c "import sys; assert sys.version_info[:2] == (3,11) and sys.maxsize > 2**32" >/dev/null 2>&1; then
    echo "[ERROR] Existing .venv is incomplete or incompatible; back it up and retry" >&2; exit 1
  fi
  echo "[setup] Reusing Python 3.11 .venv"
else
  "$PYTHON" -m venv "$VENV"
fi
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
"$VENV/bin/python" -m pip install --disable-pip-version-check --prefer-binary -r "$APP/requirements_kr_report_web.txt"
"$VENV/bin/python" -m pip check
"$VENV/bin/python" "$APP/check_windows_imports.py"
echo "[setup] Complete. Future launches: cd \"$DEST\" && bash ./run_mac.sh"
if (( NO_LAUNCH == 0 )); then exec bash "$DEST/run_mac.sh"; fi
