"""Run offline, deterministic Evals on the deployed verification gate.

Usage: python evals/run_evals.py --change 'initial baseline' --golden '12/12 passed'
This intentionally does NOT call a live LLM; recorded scores do not measure
semantic detection accuracy of Claude or Codex.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections import defaultdict
from pathlib import Path

from verification_adapter import execute

ROOT = Path(__file__).resolve().parents[1]
SET = ROOT / "evals" / "evalset.jsonl"
RESULTS = ROOT / "evals" / "results"
HISTORY = RESULTS / "history.csv"
EXPECTED_KEYS = {"id", "category", "query", "expect", "graders", "note", "ac"}


def read_cases(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) < 20 or len({c.get("id") for c in rows}) != len(rows):
        raise ValueError("evalset needs >=20 unique cases")
    if len({c.get("category") for c in rows} - {"normal"}) < 2:
        raise ValueError("at least two non-normal categories required")
    for c in rows:
        if EXPECTED_KEYS - set(c) or not str(c.get("ac", "")).startswith("AC-") or c["graders"] != ["code"]:
            raise ValueError("missing required eval keys or unsupported graders")
        if not isinstance(c["query"], dict) or c["expect"].get("status") not in ("PASS", "FAIL", "LOCAL_RULE_ONLY"):
            raise ValueError("invalid query or expected status")
    return rows


def grade(actual: dict, expect: dict) -> tuple[bool, list[str]]:
    reasons = []
    if actual.get("status") != expect["status"]:
        reasons.append("STATUS_MISMATCH")
    for prefix in expect.get("errors_contain", []):
        if not any(str(error).startswith(prefix) for error in actual.get("errors", [])):
            reasons.append("MISSING_ERROR:" + prefix)
    for prefix in expect.get("errors_exclude", []):
        if any(str(error).startswith(prefix) for error in actual.get("errors", [])):
            reasons.append("FORBIDDEN_ERROR:" + prefix)
    if actual.get("content_sha256") is None or len(str(actual["content_sha256"])) != 64:
        reasons.append("INVALID_CONTENT_HASH")
    if not isinstance(actual.get("claim_count"), int):
        reasons.append("INVALID_CLAIM_COUNT")
    if "claim_count" in expect and actual.get("claim_count") != expect["claim_count"]:
        reasons.append("CLAIM_COUNT_MISMATCH")
    if "errors_empty" in expect and (len(actual.get("errors", [])) == 0) != expect["errors_empty"]:
        reasons.append("ERRORS_EMPTY_MISMATCH")
    return not reasons, reasons


def run(dataset: Path, *, change: str, golden: str, commit: str, result_dir: Path) -> dict:
    cases = read_cases(dataset)
    details = []
    for case in cases:
        try:
            actual = execute(case["query"])
            ok, reasons = grade(actual, case["expect"])
        except Exception as exc:
            actual, ok, reasons = {"exception": repr(exc)}, False, ["EVALUATION_EXCEPTION"]
        details.append({"id": case["id"], "category": case["category"], "ac": case.get("ac"),
                        "expected_status": case["expect"]["status"],
                        "actual": actual, "pass": ok, "grade_errors": reasons})
    categories = defaultdict(lambda: [0, 0])
    for item in details:
        categories[item["category"]][1] += 1
        categories[item["category"]][0] += int(item["pass"])
    metrics = {k: {"passed": v[0], "total": v[1], "rate": v[0] / v[1]}
               for k, v in sorted(categories.items())}
    passed = sum(item["pass"] for item in details)
    now = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9)))
    run_id = now.strftime("%Y-%m-%dT%H%M%S%z") + "_" + uuid.uuid4().hex[:8]
    eval_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    record = {"run_id": run_id, "executed_at": now.isoformat(), "commit": commit,
              "change": change, "evalset_version": f"{len(cases)} cases sha256:{eval_hash}",
              "model_id": "offline-reviewer-double", "judge_version": "not-used",
              "golden_tests": golden, "scope": "rule and publication gate; not LLM factual accuracy",
              "passed": passed, "total": len(details), "overall_rate": passed / len(details),
              "metrics": metrics, "cases": details}
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / f"{run_id}.json").write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    history = result_dir / "history.csv"
    fields = ["run_id", "commit", "change", "evalset_version", "model_id", "judge_version",
              "golden_tests", "passed", "total", "overall_rate", "normal_rate", "boundary_rate", "failure_rate", "prohibited_rate"]
    with history.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if stream.tell() == 0:
            writer.writeheader()
        writer.writerow({"run_id": run_id, "commit": commit, "change": change,
                         "evalset_version": record["evalset_version"], "model_id": record["model_id"],
                         "judge_version": record["judge_version"], "golden_tests": golden,
                         "passed": passed, "total": len(details), "overall_rate": record["overall_rate"],
                         **{k + "_rate": metrics.get(k, {}).get("rate", "")
                            for k in ("normal", "boundary", "failure", "prohibited")}})
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--change", required=True)
    parser.add_argument("--golden", default="not-provided")
    parser.add_argument("--commit", default=None)
    parser.add_argument("--evalset", type=Path, default=SET)
    parser.add_argument("--result-dir", type=Path, default=RESULTS)
    args = parser.parse_args()
    commit = args.commit or subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                            capture_output=True, text=True).stdout.strip() or "unavailable"
    result = run(args.evalset, change=args.change, golden=args.golden, commit=commit, result_dir=args.result_dir)
    print(f"EVALS {result['passed']}/{result['total']} passed (offline gate, not LLM): {result['run_id']}")
    for name, m in result["metrics"].items():
        print(f"  {name}: {m['passed']}/{m['total']}")
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
