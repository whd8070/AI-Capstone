"""리포트 1건 처리: 텍스트 준비 → LLM 1회 → 인용 검증 → manifest.csv 기준 수치 보정 → (필요시 1회 확장).

원칙
  - 날짜·기업·증권사·목표가·투자의견은 manifest.csv 값이 기준. LLM 값은 대조용(llm_value)으로만 남긴다.
  - 근거마다 원문 인용(quote)을 받고, 실제 PDF 텍스트에 있는지 코드로 검증한다.
  - 같은 날짜에 리포트가 여러 건이어도 합치지 않는다(리포트 1건 = 레코드 1개). 묶음은 export 단계에서.
"""
import json
import re
from datetime import datetime

from . import config
from .pdf_text import build_input, get_pages

SCHEMA = json.loads(config.SCHEMA_FILE.read_text(encoding="utf-8"))


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def verify_quotes(result, pages):
    whole = _squash("".join(pages))
    for item in result.get("rationale", []) + result.get("risks", []):
        q, p = _squash(item.get("quote")), item.get("page", 0)
        page_text = _squash(pages[p - 1]) if 1 <= p <= len(pages) else ""
        item["quote_verified"] = bool(q) and (q in page_text or q in whole)
        item["page_verified"] = bool(q) and q in page_text


def to_num(s):
    try:
        v = float(str(s).replace(",", ""))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def check_flags(result, meta, pages):
    flags = []
    if len("".join(pages[:config.BASE_PAGES])) < config.MIN_CHARS:
        flags.append("short_text")
    csv_tp, llm_tp = to_num(meta.get("goal_price")), result.get("target_price")
    if csv_tp is None:
        flags.append("no_csv_target")              # 목표가 미제시 리포트이거나 manifest 미기록
    elif llm_tp is None or abs(llm_tp - csv_tp) > 1:
        flags.append("target_mismatch")
    if sum(r.get("quote_verified", False) for r in result.get("rationale", [])) < 2:
        flags.append("few_verified_rationale")
    return flags


# 확장 재시도는 '더 읽으면 나아질 수 있는' 경우에만 (no_csv_target 은 확장해도 해결 안 됨)
EXPANDABLE = {"short_text", "target_mismatch", "few_verified_rationale"}


def _add_usage(a, b):
    out = {k: (a.get(k) or 0) + (b.get(k) or 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens", "turns")}
    out["cost_usd"] = None if a.get("cost_usd") is None and b.get("cost_usd") is None \
        else (a.get("cost_usd") or 0) + (b.get("cost_usd") or 0)
    return out


def process(meta, call):
    nid = meta["nid"]
    pages = get_pages(nid, meta["pdf_path"])
    header = f"리포트: {meta['company']}({meta['stock_code']}) / {meta['broker']} / {meta['date']} / \"{meta['title']}\""

    n = min(config.BASE_PAGES, len(pages))
    result, usage = call(header, build_input(pages, n), SCHEMA)
    verify_quotes(result, pages)
    flags = check_flags(result, meta, pages)

    expanded = bool(EXPANDABLE & set(flags)) and len(pages) > config.BASE_PAGES
    if expanded:
        n = min(config.EXPAND_PAGES, len(pages))
        result, u2 = call(header, build_input(pages, n), SCHEMA)
        usage = _add_usage(usage, u2)
        verify_quotes(result, pages)
        flags = check_flags(result, meta, pages)       # 확장 후에도 남은 문제만 기록

    record = {
        "nid": nid,
        "report_date": meta["date"],
        "stock_code": meta["stock_code"],
        "company": meta["company"],
        "broker": meta["broker"],
        "title": meta["title"],
        "opinion": meta.get("opinion") or None,                    # 기준: manifest
        "target_price": {
            "value": to_num(meta.get("goal_price")),               # 기준: manifest
            "llm_value": result.get("target_price"),               # 대조용
            "horizon": result.get("horizon"),
            "horizon_stated": bool(result.get("horizon_stated")),
        },
        "earnings_forecast": result.get("earnings_forecast", []),
        "rationale": result.get("rationale", []),
        "risks": result.get("risks", []),
        "_meta": {
            "prompt_version": config.PROMPT_VERSION,
            "pages_total": len(pages), "pages_used": n,
            "expanded": expanded, "flags": flags,
            "extracted_at": datetime.now().isoformat(timespec="seconds"),
        },
    }
    return record, usage
