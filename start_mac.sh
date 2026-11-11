#!/usr/bin/env bash
# First setup, or recheck dependencies. For normal restarts use run_mac.sh.
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd -P)"
exec bash "$root/bootstrap_mac.sh" --destination "$root" "$@"
