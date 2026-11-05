"""
팀원에게 넘길 '알짜배기' 데이터 생성 (data/handoff/)

  reports_compact.jsonl  리포트 1건 = 1줄. 검증된 근거·리스크만, 인용문 대신 (nid, page) 참조로 압축
  daily_consensus.csv    (종목, 리포트 공개일)마다 그날까지의 증권사별 최신 의견으로 만든 컨센서스 피처
  HANDOFF.md             필드 설명, 기간·기업 커버리지, 사용 규칙(시점 정합성)

    python -m pipeline.handoff
    python -m pipeline.handoff --with-quotes        # 인용문도 포함(검증·디버깅용, 용량 증가)
    python -m pipeline.handoff --as-of 2026-06-30   # 기준일까지 공개된 리포트만으로 생성
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median, pstdev

from . import config


def norm_opinion(op):
    """증권사마다 다른 투자의견 표기를 buy / hold / sell / none 으로 정규화."""
    s = re.sub(r"\s+", "", (op or "").lower())
    if not s or "notrated" in s or s in {"nr", "-"}:
        return "none"
    if any(k in s for k in ("sell", "매도", "underperform", "reduce", "비중축소", "underweight")):
        return "sell"
    if any(k in s for k in ("buy", "매수", "outperform", "overweight", "비중확대", "accumulate")):
        return "buy"
    if any(k in s for k in ("hold", "중립", "neutral", "marketperform", "보유", "equalweight")):
        return "hold"
    return "none"


def _tp_in_text(nid, value):
    """목표가 숫자가 리포트 본문(텍스트 캐시)에 실제로 적혀 있는지: '420,000' / '420000' / '42만' / '15.5만'."""
    cache = config.TEXT_DIR / f"{nid}.json"
    if not cache.exists() or not value:
        return False
    text = re.sub(r"\s+", "", "".join(json.loads(cache.read_text(encoding="utf-8"))["pages"]))
    v = int(value)
    cands = {f"{v:,}", str(v)}
    if v % 1000 == 0:
        cands.add(f"{v / 10000:g}만")
    return any(c in text for c in cands)


def resolve_target(r):
    """목표가 기준값 = 네이버(manifest). 단, LLM이 본문에서 읽은 값이 네이버 값과 다르고 그 숫자가
    본문에 실제로 적혀 있으면 본문 값을 쓴다(네이버 메타데이터 오류 교정, 2026-11 사용자 승인).
    반환: (목표가, 출처 'naver'|'report_text', 네이버 원래 값)"""
    tp = r["target_price"]
    naver, llm = tp["value"], tp.get("llm_value")
    if naver and llm and abs(llm - naver) > 1 and _tp_in_text(r["nid"], llm):
        return float(llm), "report_text", naver
    return naver, "naver", naver


def compact(r, with_quotes):
    def keep(items, fields):
        out = []
        for it in items:
            if not it.get("quote_verified"):
                continue
            d = {k: it[k] for k in fields if k in it}
            if with_quotes:
                d["quote"] = it["quote"]
            out.append(d)
        return out

    tp = r["target_price"]
    rat = r.get("rationale", [])
    tp_value, tp_source, tp_naver = resolve_target(r)
    return {
        "nid": r["nid"], "date": r["report_date"], "stock_code": r["stock_code"], "company": r["company"],
        "broker": r["broker"],
        "opinion": r.get("opinion"), "opinion_norm": norm_opinion(r.get("opinion")),
        "target_price": tp_value,
        "tp_source": tp_source,
        "tp_naver": tp_naver,
        "tp_horizon": tp["horizon"] if tp.get("horizon_stated") else None,
        "earnings_forecast": r.get("earnings_forecast", []),
        "rationale": keep(rat, ("category", "claim", "page")),
        "risks": keep(r.get("risks", []), ("claim", "page")),
        "quality": {
            "rationale_verified": f"{sum(x.get('quote_verified', False) for x in rat)}/{len(rat)}",
            "flags": r["_meta"]["flags"],
        },
    }


DEFAULT_HORIZON_MONTHS = 12    # 기간 미기재 리포트: 국내 관행(12개월)으로 가정하고 horizon_assumed=True


def horizon_months(h):
    """'12M', '12개월', '6개월', '1년' → 개월 수. 해석 못 하면 None."""
    s = re.sub(r"\s+", "", (h or "").upper())
    # '2028년 (밸류에이션 시점)'처럼 연도(4자리)는 기간이 아니므로 1~2자리 숫자만 기간으로 본다
    m = re.search(r"(?<!\d)(\d{1,2})(M|개월)", s)
    if m:
        return int(m.group(1))
    m = re.search(r"(?<!\d)(\d)(Y|년)", s)
    return int(m.group(1)) * 12 if m else None


def add_months(day, months):
    d = date.fromisoformat(day)
    y, mo = divmod(d.month - 1 + months, 12)
    y, mo = d.year + y, mo + 1
    last = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, mo, min(d.day, last)).isoformat()


def forecast_row(r):
    """팀원 요청 형식: {리포트 날짜, 기업, 전망 시점, 전망 가격, 근거} (+ 추적용 nid·증권사)."""
    months = horizon_months(r["tp_horizon"])
    assumed = months is None
    months = months or DEFAULT_HORIZON_MONTHS
    return {
        "report_date": r["date"], "stock_code": r["stock_code"], "company": r["company"],
        "target_date": add_months(r["date"], months), "horizon_months": months, "horizon_assumed": assumed,
        "target_price": r["target_price"], "target_price_source": r["tp_source"],
        "rationale": [x["claim"] for x in r["rationale"]],
        "broker": r["broker"], "opinion": r["opinion_norm"], "nid": r["nid"],
    }


def consensus_rows(reports):
    """공개일마다: 그날(포함)까지 CONSENSUS_WINDOW_DAYS일 안의 증권사별 최신 리포트로 컨센서스를 만든다.
    미래 정보가 섞이지 않도록 각 행은 그 날짜 이전·당일 리포트만 사용한다."""
    win = config.CONSENSUS_WINDOW_DAYS
    by_stock = defaultdict(list)
    for r in reports:
        by_stock[r["stock_code"]].append(r)
    out = []
    for code, rs in sorted(by_stock.items()):
        rs.sort(key=lambda r: (r["date"], int(r["nid"])))
        latest = {}        # broker -> 가장 최근 리포트
        prev_tp = {}       # broker -> 직전 목표가 (상향/하향 판단용)
        days = sorted({r["date"] for r in rs})
        idx = 0
        for day in days:
            ups = downs = 0
            today = []
            while idx < len(rs) and rs[idx]["date"] == day:
                r = rs[idx]
                today.append(r)
                b, tp = r["broker"], r["target_price"]
                if tp and b in prev_tp and prev_tp[b]:
                    ups += tp > prev_tp[b]
                    downs += tp < prev_tp[b]
                if tp:
                    prev_tp[b] = tp
                latest[b] = r
                idx += 1
            cutoff = (date.fromisoformat(day) - timedelta(days=win)).isoformat()
            active = [r for r in latest.values() if r["date"] > cutoff]
            tps = [r["target_price"] for r in active if r["target_price"]]
            ops = [r["opinion_norm"] for r in active if r["opinion_norm"] != "none"]
            out.append({
                "stock_code": code, "company": rs[0]["company"], "date": day,
                "n_reports_today": len(today),
                "brokers_today": "|".join(r["broker"] for r in today),
                "tp_up_today": ups, "tp_down_today": downs,
                f"n_brokers_{win}d": len(active),
                "tp_median": median(tps) if tps else "",
                "tp_mean": round(mean(tps), 1) if tps else "",
                "tp_min": min(tps) if tps else "",
                "tp_max": max(tps) if tps else "",
                "tp_std": round(pstdev(tps), 1) if len(tps) > 1 else "",
                "buy_ratio": round(ops.count("buy") / len(ops), 3) if ops else "",
                "n_rationale_verified_today": sum(len(r["rationale"]) for r in today),
                "nids_today": "|".join(r["nid"] for r in today),
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-quotes", action="store_true")
    ap.add_argument("--as-of", help="이 날짜(포함)까지 공개된 리포트만")
    a = ap.parse_args()

    with config.REPORTS_JSONL.open(encoding="utf-8") as f:
        raw = [json.loads(l) for l in f if l.strip()]
    if a.as_of:
        raw = [r for r in raw if r["report_date"] <= a.as_of]
    uni = json.loads(config.UNIVERSE_FILE.read_text(encoding="utf-8"))
    raw = [r for r in raw if r["stock_code"] in uni]
    reports = sorted((compact(r, a.with_quotes) for r in raw), key=lambda r: (r["date"], r["stock_code"], int(r["nid"])))

    d = config.HANDOFF_DIR
    d.mkdir(parents=True, exist_ok=True)
    with (d / "reports_compact.jsonl").open("w", encoding="utf-8") as f:
        for r in reports:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    fc = [forecast_row(r) for r in reports if r["target_price"]]     # 목표가 없는 리포트는 전망이 없으므로 제외
    with (d / "forecasts.jsonl").open("w", encoding="utf-8") as f:
        for r in fc:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if fc:
        with (d / "forecasts.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(fc[0]))
            w.writeheader()
            w.writerows({**r, "rationale": " | ".join(r["rationale"])} for r in fc)

    rows = consensus_rows(reports)
    if rows:
        with (d / "daily_consensus.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    cover = defaultdict(int)
    for r in reports:
        cover[r["stock_code"]] += 1
    span = f"{reports[0]['date']} ~ {reports[-1]['date']}" if reports else "-"
    raw_size = sum(len(json.dumps(r, ensure_ascii=False)) for r in raw)
    cmp_size = sum(len(json.dumps(r, ensure_ascii=False)) for r in reports)
    lines = [
        "# 리포트 데이터 핸드오프", "",
        f"- 기간: {span}" + (f" (as-of {a.as_of})" if a.as_of else ""),
        f"- 리포트 {len(reports):,}건 / 기업 {len(cover)}개 (대상 {len(uni)}개) / 컨센서스 행 {len(rows):,}개",
        f"- 압축: 추출 원본 대비 {cmp_size / max(raw_size, 1):.0%} 크기",
        "",
        "## 파일",
        "- `forecasts.jsonl` / `forecasts.csv`: **간단 형식.** 리포트 1건 = 1행 "
        "{report_date, company, target_date(전망 시점), target_price(전망 가격), rationale(근거)} + 추적용 broker·opinion·nid. "
        f"target_date = report_date + 목표가 기간. 기간이 리포트에 없으면 {DEFAULT_HORIZON_MONTHS}개월로 가정하고 "
        "horizon_assumed=true. 목표가 없는 리포트는 제외. csv의 rationale은 ' | '로 이어 붙임.",
        "- `reports_compact.jsonl`: 리포트 1건 = 1줄. 근거·리스크는 원문 인용이 검증된 것만 남김. "
        "근거 원문은 (nid, page)로 추적 가능.",
        "- `daily_consensus.csv`: 리포트가 나온 날마다 한 행. 그날까지 공개된 리포트만 사용(미래 정보 없음).",
        "",
        "## 사용 규칙 (중요)",
        "- 날짜는 리포트 공개일. 시각 정보가 없으므로 **T일 행은 T일 장 마감 이후 의사결정에만** 사용한다.",
        f"- 컨센서스는 공개일 기준 직전 {config.CONSENSUS_WINDOW_DAYS}일 안의 증권사별 최신 리포트로 계산한다. "
        "한 증권사가 여러 번 내도 1표.",
        "- 리포트가 없는 날은 행이 없다. 일별 시계열로 쓸 때는 직전 값을 앞으로 채우되(forward fill), 뒤로 채우지 않는다.",
        "- 목표가·투자의견은 네이버 API(manifest) 값. LLM이 읽은 값과 다르면 quality.flags에 target_mismatch.",
        "- 예외: 네이버 목표가가 리포트 본문과 다르고 본문 숫자가 코드로 확인되면 본문 값을 쓴다 "
        "(target_price_source / tp_source = report_text, 원래 네이버 값은 tp_naver).",
        "",
        "## daily_consensus.csv 칼럼",
        "- n_reports_today / brokers_today: 그날 나온 리포트 수·증권사",
        "- tp_up_today / tp_down_today: 그날 직전 대비 목표가를 올린/내린 증권사 수",
        f"- n_brokers_{config.CONSENSUS_WINDOW_DAYS}d: 컨센서스에 들어간 증권사 수",
        "- tp_median / tp_mean / tp_min / tp_max / tp_std: 목표가 분포(의견 분산 = tp_std, max-min)",
        "- buy_ratio: 의견이 있는 증권사 중 매수 계열 비율(opinion_norm 기준)",
        "- nids_today: 그날 리포트 nid → reports_compact.jsonl에서 근거 조회",
        "",
        "## 기업별 리포트 수",
    ] + [f"- {c} {uni[c]}: {cover.get(c, 0)}건" for c in uni]
    fixed = [r for r in reports if r["tp_source"] == "report_text"]
    lines += ["", f"## 목표가 교정 ({len(fixed)}건: 네이버 값 → 리포트 본문 값)"] + [
        f"- {r['date']} {r['company']} / {r['broker']} (nid {r['nid']}): {int(r['tp_naver']):,} → {int(r['target_price']):,}"
        for r in fixed]
    (d / "HANDOFF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"리포트 {len(reports):,}건, 컨센서스 {len(rows):,}행 → {d}  (압축률 {cmp_size / max(raw_size, 1):.0%})")


if __name__ == "__main__":
    main()
