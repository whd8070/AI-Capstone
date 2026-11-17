"""Data-driven deterministic golden checks; no skip or xfail allowed."""
from pathlib import Path
import sys
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
from verification_adapter import execute  # noqa: E402
from run_evals import grade  # noqa: E402

GOLDEN = ROOT / "tests" / "harness" / "golden_cases.yaml"
DATA = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))


def test_golden_case_contract():
    assert isinstance(DATA.get("cases"), list)
    assert len(DATA["cases"]) >= 8
    assert len({c["id"] for c in DATA["cases"]}) == len(DATA["cases"])
    assert {c["category"] for c in DATA["cases"]} >= {"normal", "boundary", "prohibited"}
    for c in DATA["cases"]:
        assert c.get("ac") and c.get("input") and c.get("expect")
        assert c["expect"].get("status") in {"PASS", "FAIL", "LOCAL_RULE_ONLY"}


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["id"])
def test_verification_golden(case):
    actual = execute(case["input"])
    passed, problems = grade(actual, case["expect"])
    assert passed, f"{case['id']} / {case['ac']} => {problems} / {actual}"


def test_injected_broken_section_checker_is_detected(monkeypatch):
    """Mutation: replace the real section checker with a broken always-empty result."""
    import verification_adapter as adapter
    mutant = {"kind": "rules", "missing_section": "불확실성"}
    expect = {"status": "FAIL", "errors_contain": ["MISSING_SECTION:불확실성"]}
    true_actual = adapter.execute(mutant)
    assert grade(true_actual, expect)[0] is True
    monkeypatch.setattr(adapter.verifier, "rule_errors", lambda _: [])
    mutated_actual = adapter.execute(mutant)
    passed, problems = grade(mutated_actual, expect)
    assert not passed
    assert "STATUS_MISMATCH" in problems
    assert "MISSING_ERROR:MISSING_SECTION:불확실성" in problems
