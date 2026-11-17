"""AC-10c/12a/12b/12c deterministic formula golden cases; no skips/xfail.

Uses the very same YAML golden dataset as the independent explanation gate.
The scripted LLM is a controlled substitute; these tests do not claim real Claude quality.
"""
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "diffusion"))
import kr_formula_agent as agent  # noqa: E402
from kr_formula import blend  # noqa: E402
from kr_formula_survey import fallback_formula  # noqa: E402

ALL = yaml.safe_load((ROOT / "tests" / "harness" / "golden_cases.yaml").read_text(encoding="utf-8"))["cases"]
CASES = [x for x in ALL if x["input"]["kind"] in {"formula_agent", "formula_score"}]


def run_case(case):
    raw = case["input"]
    if raw["kind"] == "formula_score":
        formula = raw["formula"]
        mom, pair, report = (np.asarray(raw[k], dtype=float) for k in ("mom", "pair", "report"))
        got = blend(formula, mom, pair, report)
        default = blend("0.5*(0.5*mom + 0.5*pair) + 0.5*report", mom, pair, report)
        return {"status": "PASS", "after_score": got.tolist(),
                "differs_from_default": not np.allclose(got, default)}

    prompts, queue = [], list(raw.get("outputs", []))
    def mock_model(prompt):
        prompts.append(prompt)
        if raw.get("mode") == "unavailable":
            raise RuntimeError("injected CLI authentication failure")
        if not queue:
            raise AssertionError("Scripted response was exhausted; exceeded predefined golden steps")
        return {"formula": queue.pop(0), "explanation": "고정된 테스트 응답"}, {"tokens": 10, "cost_usd": 0.0}

    try:
        if raw["mode"] == "rule":
            outcome = agent.rule_based(raw["profile"])
        else:
            outcome = agent.propose(raw["profile"], raw.get("note", ""), call=mock_model,
                                    max_attempts=raw.get("max_attempts", agent.MAX_ATTEMPTS))
    except ValueError as exc:
        return {"status": "ERROR", "error_type": type(exc).__name__, "attempts": 0}

    attempts = outcome["attempts"]
    return {"status": "OK", "source": outcome["source"],
            "formula": outcome["formula"], "attempts": len(attempts),
            "rejected": sum("error" in a for a in attempts),
            "issues": len(outcome["issues"]), "stop_reason": bool(outcome.get("stop_reason")),
            "prompt_contains": "\n".join(prompts),
            "note_truncated": (not raw.get("note") or
                               raw.get("note", "")[:agent.MAX_NOTE_CHARS] in "\n".join(prompts) and
                               raw.get("note", "") not in "\n".join(prompts))}


def grade(actual, expected):
    errors = []
    for key, want in expected.items():
        if key == "prompt_contains":
            if want not in actual.get("prompt_contains", ""):
                errors.append(f"prompt missing {want!r}")
        elif key == "after_score":
            got = np.asarray(actual.get(key, []), dtype=float)
            if got.shape != (len(want),) or not np.allclose(got, want, atol=1e-10, rtol=0):
                errors.append(f"after_score mismatch {got.tolist()} != {want}")
        elif actual.get(key) != want:
            errors.append(f"{key}: {actual.get(key)!r} != {want!r}")
    return errors


def test_formula_golden_contract():
    assert len(CASES) >= 12
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert {c["category"] for c in CASES} >= {"normal", "boundary", "failure", "prohibited"}
    assert {c["ac"] for c in CASES} >= {"AC-12a", "AC-12b", "AC-12c", "AC-10c"}
    assert all(c["expect"].get("status") in {"PASS", "OK", "ERROR"} for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_formula_golden(case):
    actual = run_case(case)
    failures = grade(actual, case["expect"])
    assert not failures, f"{case['id']} / {case['ac']}: {failures} ; actual: {actual}"


def test_formula_mutant_bypasses_safety_and_is_detected(monkeypatch):
    """Fault injection: a bogus diagnostic accepts forbidden Python as a valid formula."""
    case = next(c for c in CASES if c["id"] == "AG-P01")
    original = run_case(case)
    assert not grade(original, case["expect"])

    real_diagnose = agent.diagnose
    def bypassed_diagnose(formula, signals=None):
        if "__import__" in formula:
            return real_diagnose("0.8*(0.5*mom + 0.5*pair) + 0.2*report", signals)
        return real_diagnose(formula, signals)

    monkeypatch.setattr(agent, "diagnose", bypassed_diagnose)
    mutated = run_case(case)
    failure = grade(mutated, case["expect"])
    assert failure, "The golden failed to detect safety bypass"
    assert mutated["rejected"] == 0
    assert mutated["source"] == "agent"
