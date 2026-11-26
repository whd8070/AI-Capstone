"""Check that grading fails closed for false success and missing evidence."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
from run_evals import grade, read_cases  # noqa: E402


def test_false_pass_injected_into_failed_case_is_caught():
    actual = {"status": "PASS", "errors": [], "claim_count": 5, "content_sha256": "0" * 64}
    expect = {"status": "FAIL", "errors_contain": ["REJECTED_OR_UNGROUNDED"]}
    ok, errors = grade(actual, expect)
    assert not ok
    assert "STATUS_MISMATCH" in errors
    assert "MISSING_ERROR:REJECTED_OR_UNGROUNDED" in errors


def test_evalset_validates_minimum_and_category_coverage():
    cases = read_cases(ROOT / "evals" / "evalset.jsonl")
    assert len(cases) >= 20
    assert {c["category"] for c in cases} == {"normal", "boundary", "failure", "prohibited", "attack"}
    assert sum(c["category"] == "attack" for c in cases) >= 5
    assert any(c["category"] == "failure" and "request_id=" in c["note"] for c in cases)
