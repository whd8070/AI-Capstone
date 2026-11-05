"""누적 사용량 보고서와 전체 작업 예상치.

    python -m pipeline.usage              # 전체 요약 + 남은 작업 예상
    python -m pipeline.usage --by stock   # 종목별
    python -m pipeline.usage --by run     # 실행(run)별
    python -m pipeline.usage --by model   # 모델별
"""
import argparse
import csv
import json
from collections import defaultdict

from . import config


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--by", choices=["stock", "run", "model"])
    a = ap.parse_args()

    if not config.USAGE_CSV.exists():
        return print("아직 사용 기록이 없습니다 (data/out/usage.csv)")
    with config.USAGE_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    uni = json.loads(config.UNIVERSE_FILE.read_text(encoding="utf-8"))

    def summarize(rs):
        n = len(rs)
        i, c, o = (sum(_f(r[k]) for r in rs) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
        cost = sum(_f(r["cost_usd"]) for r in rs)
        exp = sum(r["expanded"] == "True" for r in rs)
        return n, i, c, o, cost, exp

    n, i, c, o, cost, exp = summarize(rows)
    print(f"== 누적 사용량 (호출 기록 {n}건)")
    print(f"입력 {int(i):,} 토큰 (그중 캐시 {int(c):,}, {c / max(i, 1):.0%}) / 출력 {int(o):,} 토큰 / 비용 환산 ${cost:.3f}")
    print(f"건당 평균: 입력 {int(i / n):,} / 출력 {int(o / n):,} / ${cost / n:.4f} / 확장 비율 {exp / n:.0%}")

    if a.by:
        key = {"stock": "stock_code", "run": "run_id", "model": "model"}[a.by]
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        print(f"\n== {a.by}별")
        for k, rs in sorted(groups.items()):
            n2, i2, c2, o2, cost2, exp2 = summarize(rs)
            label = f"{k} {uni.get(k, '')}" if a.by == "stock" else k
            print(f"{label:<24} {n2:>5}건 | 건당 입력 {int(i2 / n2):>7,} 출력 {int(o2 / n2):>6,} | 합계 ${cost2:.3f} | 확장 {exp2 / n2:.0%}")

    # 남은 작업 예상
    if config.MANIFEST.exists():
        with config.MANIFEST.open(encoding="utf-8") as f:
            man = [r for r in csv.DictReader(f) if r.get("pdf_path") and r["stock_code"] in uni]
        done = set()
        if config.REPORTS_JSONL.exists():
            with config.REPORTS_JSONL.open(encoding="utf-8") as f:
                done = {json.loads(l)["nid"] for l in f if l.strip()}
        remain = [r for r in man if r["nid"] not in done]
        per_stock = defaultdict(int)
        for r in man:
            per_stock[r["stock_code"]] += 1
        print(f"\n== 작업 규모: 수집된 리포트 {len(man):,}건 (대상 {len(uni)}개 중 {len(per_stock)}개 기업), "
              f"완료 {len(man) - len(remain):,}건, 남음 {len(remain):,}건")
        missing = [uni[c] for c in uni if c not in per_stock]
        if missing:
            more = f" 외 {len(missing) - 8}개" if len(missing) > 8 else ""
            print(f"   아직 수집 안 된 기업 {len(missing)}개: {', '.join(missing[:8])}{more}")
        k = len(remain)
        print(f"== 남은 {k:,}건 예상 (현재 평균 기준): 입력 {int(i / n * k):,} / 출력 {int(o / n * k):,} 토큰"
              f" / 비용 환산 ${cost / n * k:.2f}")
        print("   ※ Max 요금제 한도는 토큰으로 공개되지 않으므로, 설정의 사용량(%) 변화와 함께 보고 외삽할 것")


if __name__ == "__main__":
    main()
