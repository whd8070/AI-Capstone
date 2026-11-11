"""Check first-run web imports without shell quoting or Windows argv issues.

Run via the interpreter inside src/diffusion/.venv:
    python check_windows_imports.py
"""
from __future__ import annotations

import importlib
import sys
import traceback

REQUIRED_MODULES = (
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "torch",
    "yfinance",
    "pandas_datareader",
    "streamlit",
    "psutil",
    "requests",
    "fitz",
    "jsonschema",
)


def main() -> int:
    failed = []
    for name in REQUIRED_MODULES:
        try:
            importlib.import_module(name)
            print(f"[import-check] OK: {name}", flush=True)
        except Exception:
            print(f"[import-check] FAILED: {name}", file=sys.stderr, flush=True)
            traceback.print_exc()
            failed.append(name)
    if failed:
        print(f"[import-check] FAILED modules: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("[import-check] IMPORTS_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
