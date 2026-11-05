"""
리포트 → 구조화 JSON 파이프라인 실행기 (사용량 제한 장치 포함)

대상 고르기
    --stock 005930,000660      특정 종목만 (기본: universe.json 전체)
    --since / --until          리포트 날짜 범위
    --per-stock N              종목마다 N건만 (날짜 전체에 고르게 뽑음) → 44개 기업 표본 측정용
    --limit N                  이번 실행 최대 건수
사용량 제한 (넘으면 다음 건을 시작하지 않고 멈춤)
    --max-tokens N             이번 실행 누적 토큰(입력+출력) 상한
    --max-cost USD             이번 실행 누적 비용(Claude Code가 알려주는 API 환산값) 상한
    --max-minutes M            이번 실행 시간 상한
안전
    --dry-run                  LLM 없이 대상 목록과 입력 크기만
    --yes                      20건 초과 실행 시 확인 질문 생략

예)
    python -m pipeline.run --dry-run --per-stock 1
    python -m pipeline.run --per-stock 1 --max-tokens 300000      # 44개 기업 1건씩 표본
    python -m pipeline.run --stock 005930 --limit 30 --max-cost 1.0
    python -m pipeline.usage                                      # 누적 사용량·전체 예상치
"""
import argparse
import csv
import json
import time
from datetime import datetime

from . import config
from .extract import process
from .llm import BACKENDS
from .pdf_text import build_input, get_pages

USAGE_FIELDS = ["run_id", "time", "backend", "model", "nid", "stock_code", "date", "pages_total", "pages_used",
                "expanded", "flags", "input_tokens", "cached_input_tokens", "output_tokens", "cost_usd",
                "turns", "seconds"]


def load_universe():
    return json.loads(config.UNIVERSE_FILE.read_text(encoding="utf-8"))


def spread_pick(rows, k):
    """날짜순 rows에서 k개를 고르게 뽑는다(앞·중간·뒤가 골고루 들어가게)."""
    if k >= len(rows):
        return rows
    if k == 1:
        return [rows[len(rows) // 2]]
    step = (len(rows) - 1) / (k - 1)
    return [rows[round(i * step)] for i in range(k)]


def select_targets(a, done, only=None):
    uni = load_universe()
    stocks = set(a.stock.split(",")) if a.stock else set(uni)
    with config.MANIFEST.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("pdf_path") and r["stock_code"] in stocks]
    rows = [r for r in rows if (not a.since or r["date"] >= a.since) and (not a.until or r["date"] <= a.until)]
    rows = [r for r in rows if r["nid"] not in done and (only is None or r["nid"] in only)]
    rows.sort(key=lambda r: (r["date"], int(r["nid"])))
    if a.per_stock:
        by = {}
        for r in rows:
            by.setdefault(r["stock_code"], []).append(r)
        rows = [r for code in sorted(by) for r in spread_pick(by[code], a.per_stock)]
        rows.sort(key=lambda r: (r["date"], int(r["nid"])))
    return rows[: a.limit] if a.limit else rows


def load_done():
    if not config.REPORTS_JSONL.exists():
        return set()
    with config.REPORTS_JSONL.open(encoding="utf-8") as f:
        return {json.loads(l)["nid"] for l in f if l.strip()}


def drop_records(nids):
    if not config.REPORTS_JSONL.exists():
        return
    lines = config.REPORTS_JSONL.read_text(encoding="utf-8").splitlines()
    keep = [l for l in lines if l.strip() and json.loads(l)["nid"] not in nids]
    config.REPORTS_JSONL.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")


def log_usage(row):
    new = not config.USAGE_CSV.exists()
    with config.USAGE_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=USAGE_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def dry_run(todo):
    tot2 = totall = 0
    for m in todo:
        pages = get_pages(m["nid"], m["pdf_path"])
        c2, ca = len(build_input(pages, config.BASE_PAGES)), len(build_input(pages, len(pages)))
        tot2, totall = tot2 + c2, totall + ca
        print(f"{m['date']} {m['stock_code']} {m['company'][:8]:<8} {m['broker'][:8]:<8} {len(pages):>2}쪽 "
              f"| 앞2쪽 {c2:>6}자 | 전체 {ca:>7}자 | 목표가 {m.get('goal_price') or '-'}")
    if todo:
        print(f"\n대상 {len(todo)}건, 평균 글자 수: 앞2쪽 {tot2 // len(todo)} / 전체 {totall // len(todo)} "
              f"(전체 대비 {tot2 / max(totall, 1):.0%})")


def confirm(n, a):
    if a.yes or n <= config.CONFIRM_OVER:
        return True
    limits = ", ".join(f"{k}={v}" for k, v in (("max-tokens", a.max_tokens), ("max-cost", a.max_cost),
                                                ("max-minutes", a.max_minutes)) if v) or "없음"
    print(f"{n}건을 LLM으로 처리합니다 (제한: {limits}). 계속할까요? [y/N] ", end="", flush=True)
    try:
        return input().strip().lower() == "y"
    except EOFError:                       # 비대화형 실행에서는 확인 불가 → 중단
        print("\n확인할 수 없어 중단합니다. 진행하려면 --yes를 붙이세요.")
        return False


def main():
    ap = argparse.ArgumentParser(description="리포트 구조화 파이프라인")
    ap.add_argument("--backend", choices=list(BACKENDS), default="claude")
    ap.add_argument("--stock", help="종목코드(쉼표 구분). 기본: universe.json 전체")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--per-stock", type=int, help="종목마다 최대 N건(날짜 전체에 고르게)")
    ap.add_argument("--limit", type=int, help="이번 실행 최대 건수")
    ap.add_argument("--max-tokens", type=int, help="이번 실행 누적 토큰 상한(입력+출력)")
    ap.add_argument("--max-cost", type=float, help="이번 실행 누적 비용 상한(USD, API 환산)")
    ap.add_argument("--max-minutes", type=float, help="이번 실행 시간 상한(분)")
    ap.add_argument("--redo", help="재추출할 nid (쉼표 구분)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="대량 실행 확인 질문 생략")
    a = ap.parse_args()

    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    redo = set(a.redo.split(",")) if a.redo else None
    if redo:
        drop_records(redo)
    done = load_done()
    todo = select_targets(a, done, redo)

    if a.dry_run:
        return dry_run(todo)
    if not todo:
        return print(f"처리할 리포트가 없습니다 (완료 {len(done)}건)")
    if not confirm(len(todo), a):
        return

    model = config.CLAUDE_MODEL if a.backend == "claude" else config.API_MODEL if a.backend == "api" else "-"
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"run={run_id} backend={a.backend} model={model} 대상 {len(todo)}건 (누적 완료 {len(done)}건)")
    call = BACKENDS[a.backend]
    tot = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    ok = fail = 0
    t_start = time.time()
    stop_reason = ""

    for i, meta in enumerate(todo, 1):
        used_tokens = tot["input_tokens"] + tot["output_tokens"]
        if a.max_tokens and used_tokens >= a.max_tokens:
            stop_reason = f"토큰 상한 도달 ({used_tokens:,} ≥ {a.max_tokens:,})"; break
        if a.max_cost and tot["cost_usd"] >= a.max_cost:
            stop_reason = f"비용 상한 도달 (${tot['cost_usd']:.3f} ≥ ${a.max_cost})"; break
        if a.max_minutes and (time.time() - t_start) / 60 >= a.max_minutes:
            stop_reason = f"시간 상한 도달 ({a.max_minutes}분)"; break

        t0 = time.time()
        try:
            record, usage = process(meta, call)
        except Exception as e:
            fail += 1
            print(f"[fail {i}/{len(todo)}] {meta['nid']} {meta['date']} {meta['broker']}: {e}")
            low = str(e).lower()
            if "limit" in low or "usage" in low or "rate" in low:
                stop_reason = "사용량 한도로 보임 — 리셋 후 같은 명령으로 이어서 실행"; break
            continue

        record["_meta"].update(backend=a.backend, model=model, run_id=run_id)
        with config.REPORTS_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        for k in ("input_tokens", "cached_input_tokens", "output_tokens"):
            tot[k] += usage.get(k) or 0
        tot["cost_usd"] += usage.get("cost_usd") or 0
        sec = round(time.time() - t0, 1)
        m = record["_meta"]
        log_usage({"run_id": run_id, "time": m["extracted_at"], "backend": a.backend, "model": model,
                   "nid": meta["nid"], "stock_code": meta["stock_code"], "date": meta["date"], **usage,
                   "pages_total": m["pages_total"], "pages_used": m["pages_used"],
                   "expanded": m["expanded"], "flags": "|".join(m["flags"]), "seconds": sec})
        ok += 1
        v = sum(r["quote_verified"] for r in record["rationale"])
        cost = f" ${usage['cost_usd']:.4f}" if usage.get("cost_usd") is not None else ""
        print(f"[ok {i}/{len(todo)}] {meta['date']} {meta['company'][:8]} {meta['broker'][:8]} "
              f"| 근거 {len(record['rationale'])}(검증 {v}) | {m['pages_used']}쪽{' 확장' if m['expanded'] else ''} "
              f"| in {usage['input_tokens']:,} out {usage['output_tokens']:,}{cost} "
              f"| 누적 {tot['input_tokens'] + tot['output_tokens']:,} tok | {sec}s")

    print("\n== 실행 요약", f"(중단: {stop_reason})" if stop_reason else "")
    print(f"성공 {ok}건, 실패 {fail}건, 남은 대상 {len(todo) - ok - fail}건, {round((time.time() - t_start) / 60, 1)}분")
    if ok:
        print(f"토큰 합계: 입력 {tot['input_tokens']:,} (캐시 {tot['cached_input_tokens']:,}) / 출력 {tot['output_tokens']:,}"
              f" / 비용 환산 ${tot['cost_usd']:.3f}")
        print(f"건당 평균: 입력 {tot['input_tokens'] // ok:,} / 출력 {tot['output_tokens'] // ok:,}"
              f" / ${tot['cost_usd'] / ok:.4f}")
        print("전체 예상치는: python -m pipeline.usage")


if __name__ == "__main__":
    main()
