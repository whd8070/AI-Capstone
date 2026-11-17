"""Live Claude/Codex semantic-verdict evaluation (AC-07a~c); NOT the offline gate test.

Requires human-approved labels. Do not commit unlicensed source material or private facts.
Examples:
  python evals/run_live_verifier.py --dataset evals/local/live_claims.jsonl --dry-run
  python evals/run_live_verifier.py --dataset evals/local/live_claims.jsonl --backend codex --limit 3
  python evals/run_live_verifier.py --dataset evals/local/live_claims.jsonl --backend codex --require-complete
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "diffusion"
GROUPS = {"P30", "M30", "G30"}
P_TYPES = {"missing_id": 10, "empty_id": 10, "unknown_id": 10}
M_TYPES = {"number": 5, "unit": 5, "stock": 5, "period": 5, "certainty": 5, "causality": 5}


def load_cases(path: Path, *, require_complete: bool = False) -> list[dict]:
    if not path.is_file():
        raise ValueError(f"Missing input dataset: {path}")
    cases = []
    seen = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            case = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL line {line_no}: {exc}") from exc
        if not isinstance(case, dict):
            raise ValueError(f"JSONL line {line_no}: expected JSON object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError(f"JSONL line {line_no}: empty or duplicate id")
        seen.add(case_id)
        group = case.get("group")
        if group not in GROUPS:
            raise ValueError(f"{case_id}: unknown group {group!r}")
        if not isinstance(case.get("claim"), str) or not case["claim"].strip():
            raise ValueError(f"{case_id}: missing claim")
        if not isinstance(case.get("facts"), dict):
            raise ValueError(f"{case_id}: facts must be a dictionary")
        if not isinstance(case.get("gold_note"), str) or not case["gold_note"].strip():
            raise ValueError(f"{case_id}: human gold_note is required")
        gold = case.get("expected_verdict")
        if gold != ("pass_or_warn" if group == "G30" else "reject"):
            raise ValueError(f"{case_id}: invalid expected_verdict for {group}")
        if group == "P30" and case.get("subtype") not in P_TYPES:
            raise ValueError(f"{case_id}: invalid P30 subtype")
        if group == "M30" and case.get("subtype") not in M_TYPES:
            raise ValueError(f"{case_id}: invalid M30 subtype")
        cases.append(case)
    if not cases:
        raise ValueError("Dataset contains zero cases")
    if require_complete:
        groups = Counter(c["group"] for c in cases)
        p_types = Counter(c["subtype"] for c in cases if c["group"] == "P30")
        m_types = Counter(c["subtype"] for c in cases if c["group"] == "M30")
        if groups != Counter({"P30": 30, "M30": 30, "G30": 30}):
            raise ValueError(f"Full evaluation requires P30=30, M30=30, G30=30; found {dict(groups)}")
        if dict(p_types) != P_TYPES or dict(m_types) != M_TYPES:
            raise ValueError(f"Wrong subtype composition: P={dict(p_types)}, M={dict(m_types)}")
    return cases


def grade_one(case: dict, raw_response: dict) -> tuple[bool, str, str]:
    if not isinstance(raw_response, dict):
        return False, "invalid_response", "missing response object"
    claims = raw_response.get("claims")
    if not isinstance(claims, list) or len(claims) != 1 or not isinstance(claims[0], dict):
        return False, "invalid_response", "expected exactly one claim verdict"
    claim = claims[0]
    verdict = claim.get("verdict", "")
    if claim.get("claim_id") != "C001" or verdict not in ("pass", "warn", "reject"):
        return False, str(verdict), "wrong claim_id or unknown verdict"
    if not isinstance(claim.get("reason_code"), str) or not claim["reason_code"].strip():
        return False, verdict, "empty reason_code"
    ok = (verdict == "reject") if case["group"] in ("P30", "M30") else (verdict in ("pass", "warn"))
    if case["group"] == "G30" and ok:
        refs = claim.get("evidence_refs")
        if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r.strip() for r in refs):
            return False, verdict, "normal claim accepted without evidence refs"
    return ok, verdict, "" if ok else "incorrect verdict"


def status_id():
    p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return p.stdout.strip() if p.returncode == 0 else "unavailable"


def run_live(cases: list[dict], backend: str, output_dir: Path, *, limit: int | None, dataset: Path) -> tuple[dict, Path]:
    unreviewed = [c["id"] for c in cases if c.get("human_reviewed") is not True]
    if unreviewed:
        raise ValueError("Human labels are not approved: " + ", ".join(unreviewed[:10]) + ("..." if len(unreviewed) > 10 else ""))
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from kr_report_verification import model_verdicts
    selected = cases[:limit] if limit is not None else cases
    output_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9)))
    run_id = now.strftime("%Y%m%dT%H%M%S%z") + "_" + uuid.uuid4().hex[:6]
    partial_path = output_dir / f"live_{backend}_{run_id}.partial.jsonl"
    results = []
    for index, case in enumerate(selected, 1):
        print(f"[{index}/{len(selected)}] {case['id']} ({case['group']})", flush=True)
        claim = case["claim"]
        try:
            raw = model_verdicts(backend, claim, case["facts"], [{"claim_id": "C001", "text": claim}])
            passed, verdict, error = grade_one(case, raw)
            outcome = {"id": case["id"], "group": case["group"], "subtype": case.get("subtype"),
                       "expected": case["expected_verdict"], "actual": verdict,
                       "correct": passed, "error": error, "reviewer_response": raw}
        except Exception as exc:
            outcome = {"id": case["id"], "group": case["group"], "subtype": case.get("subtype"),
                       "expected": case["expected_verdict"], "actual": "execution_error",
                       "correct": False, "error": type(exc).__name__ + ": " + str(exc)[:500]}
        results.append(outcome)
        with partial_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(outcome, ensure_ascii=False) + "\n")
        if outcome["actual"] == "execution_error":
            print("STOP: model/CLI execution error; previous results are preserved in " + str(partial_path), flush=True)
            break
    counts = Counter(r["group"] for r in results)
    correct = Counter(r["group"] for r in results if r["correct"])
    payload = {
        "run_id": run_id, "timestamp": now.isoformat(), "commit": status_id(),
        "backend": backend, "scope": "actual model semantic verdicts, not offline gate",
        "human_label_required": True,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "full_90": len(results) == 90 and dict(counts) == {"P30": 30, "M30": 30, "G30": 30},
        "n": len(results), "correct": sum(x["correct"] for x in results),
        "metrics": {g: {"correct": correct[g], "total": counts[g], "rate": (correct[g] / counts[g] if counts[g] else None)}
                    for g in sorted(GROUPS)},
        "outcomes": results,
        "warning": "Results are model verdicts against human labels; they do not certify the final published report. Data must be reviewed before public upload."
    }
    output_path = output_dir / f"live_{backend}_{run_id}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial_path.unlink(missing_ok=True)
    return payload, output_path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--backend", choices=("codex", "claude"))
    p.add_argument("--limit", type=int, default=None, help="Pilot only; no 90-case AC claim")
    p.add_argument("--require-complete", action="store_true", help="Require P30/M30/G30 and all subtype quotas")
    p.add_argument("--dry-run", action="store_true", help="Validate dataset only; do not use CLI")
    p.add_argument("--output-dir", type=Path, default=ROOT / "evals" / "local_results")
    args = p.parse_args()
    try:
        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit must be positive")
        cases = load_cases(args.dataset, require_complete=args.require_complete)
        approved = sum(c.get("human_reviewed") is True for c in cases)
        counts = Counter(c["group"] for c in cases)
        print(f"DATASET {len(cases)} cases, human-approved {approved}/{len(cases)}, counts {dict(counts)}")
        if args.dry_run:
            print("DRY RUN ONLY: zero model calls, no accuracy result")
            return 0
        if not args.backend:
            raise ValueError("--backend codex|claude is required without --dry-run")
        record, path = run_live(cases, args.backend, args.output_dir, limit=args.limit, dataset=args.dataset)
        print(f"OUTPUT {path}")
        for group, values in record["metrics"].items():
            print(f"{group}: {values['correct']}/{values['total']}")
        if not record["full_90"]:
            print("PILOT ONLY: incomplete P30/M30/G30. Do not claim AC-07a~c pass.")
        return 0 if record["correct"] == record["n"] else 1
    except (ValueError, OSError) as exc:
        print("ERROR " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
