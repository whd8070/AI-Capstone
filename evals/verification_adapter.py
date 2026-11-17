"""Evaluation adapter: invokes the real verification gate with controlled inputs.

The injected reviewer is a *test double*, not an LLM. This module evaluates the
publish/format gate only; it cannot measure the underlying LLM's factual accuracy.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "diffusion"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import kr_report_verification as verifier  # noqa: E402

FACTS = {
    "holdings": [{"stock_code": "005930", "weight_after_pct": "10.00%"}],
    "report_records": [{"nid": "123", "stock_code": "005930", "date": "2026-11-04"}],
}


def markdown(query: dict) -> str:
    if query.get("no_claims"):
        return "\n\n".join("## " + x for x in verifier.REQUIRED_SECTIONS)
    excluded = query.get("missing_section")
    source = query.get("reference", "portfolio")
    parts = [f"## {s}\n\n기준시점에 확인된 기록으로 설명합니다. ({source})"
             for s in verifier.REQUIRED_SECTIONS if s != excluded]
    if query.get("extra_decimal"):
        parts.append("추가 관측값은 1.234%입니다. (portfolio)")
    if query.get("raw_missing"):
        parts.append(f"누락값: {query['raw_missing']} (portfolio)")
    text = "\n\n".join(parts)
    if query.get("too_long"):
        text += "가" * 53000
    return text


def reviewer_double(mode: str):
    def run(backend, report, facts, claims):
        if mode == "exception":
            raise TimeoutError("injected verifier timeout")
        all_pass = [dict(claim_id=c["claim_id"], verdict="pass", reason_code="SUPPORTED", evidence_refs=["portfolio"])
                    for c in claims]
        if mode == "all_pass":
            return {"claims": all_pass}
        if mode == "all_reject":
            return {"claims": [dict(x, verdict="reject", reason_code="UNSUPPORTED", evidence_refs=[])
                               for x in all_pass]}
        if mode == "one_reject":
            all_pass[0].update(verdict="reject", reason_code="UNSUPPORTED", evidence_refs=[])
        elif mode == "missing_verdict":
            all_pass.pop()
        elif mode == "duplicate_verdict":
            all_pass[-1] = dict(all_pass[0])
        elif mode == "unknown_reference":
            all_pass[0]["evidence_refs"] = ["report:not-present"]
        elif mode == "empty_reference":
            all_pass[0]["evidence_refs"] = []
        elif mode == "not_cited":
            all_pass[0]["evidence_refs"] = ["risk"]
        elif mode == "warn_valid":
            all_pass[0].update(verdict="warn", reason_code="UNCERTAINTY")
        elif mode == "warn_no_reason":
            all_pass[0].update(verdict="warn", reason_code="")
        elif mode == "unexpected_verdict":
            all_pass[0]["verdict"] = "pending"
        elif mode != "all_pass":
            raise ValueError(f"Unrecognized reviewer double: {mode}")
        return {"claims": all_pass}
    return run


def execute(query: dict) -> dict:
    if not isinstance(query, dict) or query.get("kind") not in ("rules", "verify", "local"):
        raise ValueError("query must contain kind=rules|verify|local")
    text = markdown(query)
    kind = query["kind"]
    if kind == "rules":
        errors = verifier.rule_errors(text)
        return {"status": "PASS" if not errors else "FAIL", "errors": errors,
                "claim_count": len(verifier.split_claims(text)), "content_sha256": verifier.digest(text)}
    if kind == "local":
        return verifier.local_status(text)
    return verifier.verify(text, FACTS, backend="codex", runner=reviewer_double(query.get("reviewer", "all_pass")))
