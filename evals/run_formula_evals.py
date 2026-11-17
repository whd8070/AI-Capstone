"""24 deterministic acceptance cases for the shipped novice formula-suggestion agent.

Calls the real kr_formula_agent.propose/rule_based code with scripted LLM answers.
Not a measurement of live Claude accuracy or investment profitability.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "diffusion"
sys.path.insert(0, str(SRC))

from kr_formula_agent import propose, rule_based  # noqa: E402

DATASET = ROOT / "evals" / "formula_evalset.jsonl"
RESULTS = ROOT / "evals" / "results"


def read_cases(path: Path):
    cases = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(cases) < 20 or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("At least 20 unique formula cases are required")
    if Counter(c["category"] for c in cases) != {"normal": 6, "boundary": 6, "failure": 6, "prohibited": 6}:
        raise ValueError("Expected six cases each in four categories")
    for c in cases:
        if not all(k in c for k in ("id", "category", "ac", "mode", "profile", "outputs", "expect", "note")):
            raise ValueError("Missing case keys")
    return cases


def execute(case):
    mode = case["mode"]
    prompts = []
    queue = list(case["outputs"])
    def scripted(prompt):
        prompts.append(prompt)
        if mode == "error":
            raise RuntimeError("injected CLI unavailability")
        if not queue:
            raise RuntimeError("scripted model exhausted")
        return {"formula": queue.pop(0), "explanation": "테스트용 쉬운 설명"}, {"tokens": 10, "cost_usd": 0.0}
    try:
        if mode == "rule":
            actual = rule_based(case["profile"])
        else:
            actual = propose(case["profile"], case.get("note", ""),
                             call=scripted, max_attempts=case.get("max_attempts", 3))
        attempts = actual["attempts"]
        return {"status": "OK", "source": actual["source"], "formula": actual["formula"],
                "attempts": len(attempts),
                "errors": sum("error" in x for x in attempts),
                "issues": len(actual["issues"]),
                "stop_reason": bool(actual["stop_reason"]),
                "prompts": prompts,
                "usage_calls": actual["usage"]["calls"],
                "has_diag": isinstance(actual.get("diag"), dict)}
    except ValueError as exc:
        return {"status": "ERROR", "error": type(exc).__name__, "message": str(exc)}


def grade(actual, expect):
    failures = []
    for k in ("status", "source", "attempts", "errors", "issues"):
        if k in expect and actual.get(k) != expect[k]:
            failures.append(f"{k}: expected {expect[k]!r}, actual {actual.get(k)!r}")
    if "errors_min" in expect and actual.get("errors", -1) < expect["errors_min"]:
        failures.append("missing rejected formula")
    if "feedback" in expect and not any(expect["feedback"] in p for p in actual.get("prompts", [])[1:]):
        failures.append("LLM revision prompt missing prior feedback")
    if actual["status"] == "OK" and (not actual["has_diag"] or not actual["formula"]):
        failures.append("no usable formula/diagnostics")
    return not failures, failures


def run(dataset=DATASET, results_dir=RESULTS):
    cases = read_cases(dataset)
    output = []
    for case in cases:
        try:
            actual = execute(case)
            ok, failure = grade(actual, case["expect"])
        except Exception as exc:
            actual, ok, failure = {"error": repr(exc)}, False, ["EVAL_EXCEPTION"]
        actual.pop("prompts", None)  # avoid storing potentially sensitive free-text input
        output.append({"id": case["id"], "category": case["category"], "ac": case["ac"],
                       "expected": case["expect"], "actual": actual, "pass": ok, "failures": failure})
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    run_id = now.strftime("%Y-%m-%dT%H%M%S%z") + "_" + uuid.uuid4().hex[:8]
    counts = Counter(c["category"] for c in cases)
    passed = Counter(o["category"] for o in output if o["pass"])
    record = {"run_id": run_id, "scope": "scripted Claude agent-loop and formula parser; NOT live LLM",
              "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
              "pass": sum(x["pass"] for x in output), "total": len(output),
              "metrics": {k: {"pass": passed[k], "total": counts[k]} for k in sorted(counts)},
              "cases": output}
    results_dir.mkdir(parents=True, exist_ok=True)
    dest = results_dir / ("formula_" + run_id + ".json")
    dest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    history = results_dir / "formula_history.csv"
    with history.open("a", encoding="utf-8", newline="") as stream:
        w = csv.writer(stream)
        if stream.tell() == 0:
            w.writerow(["run_id", "dataset_sha256", "pass", "total", "mode"])
        w.writerow([run_id, record["dataset_sha256"], record["pass"], record["total"], "scripted-offline"])
    print(f"FORMULA_EVALS {record['pass']}/{record['total']} passed: {dest}")
    for cat, v in record["metrics"].items():
        print(f"  {cat}: {v['pass']}/{v['total']}")
    return 0 if record["pass"] == record["total"] else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=Path, default=DATASET)
    p.add_argument("--results-dir", type=Path, default=RESULTS)
    args = p.parse_args()
    sys.exit(run(args.dataset, args.results_dir))
