"""reports.jsonl → 종목·날짜별 묶음 JSON.
같은 날 리포트가 여러 건이면 한 파일의 reports 배열에 증권사별로 그대로 담는다(평균 내지 않음).

    python -m pipeline.export                 # data/out/by_date/{종목코드}/{날짜}.json
    python -m pipeline.export --as-of 2026-06-30   # 기준일 이전 공개분만
"""
import argparse
import json
from collections import defaultdict
from statistics import median

from . import config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", help="이 날짜(포함)까지 공개된 리포트만")
    a = ap.parse_args()

    groups = defaultdict(list)
    with config.REPORTS_JSONL.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if a.as_of and r["report_date"] > a.as_of:
                continue
            groups[(r["stock_code"], r["report_date"])].append(r)

    for (code, day), reps in sorted(groups.items()):
        reps.sort(key=lambda r: (r["broker"], int(r["nid"])))
        tps = [r["target_price"]["value"] for r in reps if r["target_price"]["value"]]
        out = {
            "stock_code": code, "company": reps[0]["company"], "date": day,
            "n_reports": len(reps),
            "brokers": [r["broker"] for r in reps],
            "target_price_summary": ({"median": median(tps), "min": min(tps), "max": max(tps), "n": len(tps)}
                                     if tps else None),
            "reports": reps,
        }
        path = config.BY_DATE_DIR / code / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(groups)}개 (종목, 날짜) 묶음 → {config.BY_DATE_DIR}")


if __name__ == "__main__":
    main()
