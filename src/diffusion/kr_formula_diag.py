"""수식 점검 도구: 수식을 표본 신호에 적용했을 때의 '성격'만 돌려준다.

수익률·백테스트 성과는 일부러 계산하지 않는다. 에이전트가 과거 수익률을 보고 수식을 고치면
과거 데이터에 끼워 맞춘 수식이 되기 때문이다(평가 구간 튜닝 금지).
"""
from pathlib import Path

import numpy as np
import pandas as pd

from kr_formula import VARIABLES, rank_z, score

SAMPLE = Path(__file__).with_name("kr_formula_sample_signals.csv")
DEFAULT_FORMULA = "0.5*(0.5*mom + 0.5*pair) + 0.5*report"   # 기존 웹의 기본값(p=0.5, r=0.5)
TOP_N = 10


def load_signals(path=SAMPLE):
    """{날짜: DataFrame(stock_code, company, mom, pair, report)} (날짜 오름차순)."""
    df = pd.read_csv(path, dtype={"stock_code": str})
    return {d: g.reset_index(drop=True) for d, g in df.groupby("date", sort=True)}


def _corr(a, b):
    """순위 상관(스피어만). 한쪽이 전부 같은 값이면 None."""
    if np.ptp(a) < 1e-12 or np.ptp(b) < 1e-12:
        return None
    return float(np.corrcoef(rank_z(a), rank_z(b))[0, 1])


def _top(scores, frame):
    return list(frame.loc[np.argsort(-scores, kind="mergesort")[:TOP_N], "company"])


def scores_by_date(formula, signals):
    return {d: score(formula, g["mom"], g["pair"], g["report"]) for d, g in signals.items()}


def _sensitivity(formula, frame, base_score, shuffles=20):
    """신호 하나만 종목 간에 섞었을 때 순위가 얼마나, 어느 방향으로 바뀌는지.

    share: 세 신호가 순위에 미치는 영향의 비중(합 1). 가중 평균 수식이면 계수 비율과 거의 같다.
    direction: 그 신호가 커진 종목의 점수가 오르면 +, 내리면 -.
    신호끼리 상관이 있어도 한 신호만 따로 흔들기 때문에 서로 섞이지 않는다.
    """
    rng = np.random.default_rng(0)                    # 고정 시드: 같은 수식은 항상 같은 결과
    cols = {v: frame[v].to_numpy(float) for v in VARIABLES}
    strength, direction = {}, {}
    for v in VARIABLES:
        moved, dirs = [], []
        for _ in range(shuffles):
            perm = rng.permutation(len(frame))
            changed = dict(cols)
            changed[v] = cols[v][perm]
            try:
                s = score(formula, changed["mom"], changed["pair"], changed["report"])
            except Exception:                         # 섞은 뒤 계산이 안 되는 드문 경우는 건너뜀
                continue
            c = _corr(base_score, s)
            moved.append(0.0 if c is None else max(0.0, 1.0 - c))
            d = _corr(s - base_score, changed[v] - cols[v])
            if d is not None:
                dirs.append(d)
        strength[v] = float(np.sqrt(np.mean(moved))) if moved else 0.0
        direction[v] = float(np.mean(dirs)) if dirs else 0.0
    total = sum(strength.values()) or 1.0
    return {v: strength[v] / total for v in VARIABLES}, direction


def diagnose(formula, signals=None):
    """수식의 성격 요약. 수식이 잘못되면 formula.FormulaError가 난다."""
    signals = signals or load_signals()
    dates = list(signals)
    latest = dates[-1]                       # 리포트가 가장 많이 깔린 최근 날짜로 영향도를 잰다
    mine = scores_by_date(formula, signals)
    base = scores_by_date(DEFAULT_FORMULA, signals)
    g = signals[latest]
    share, direction = _sensitivity(formula, g, mine[latest])
    top_mine, top_base = _top(mine[latest], g), _top(base[latest], g)
    # 연속된 날짜 사이에 상위 종목이 얼마나 유지되는지(낮을수록 매매 회전이 큼)
    keep = [len(set(_top(mine[a], signals[a])) & set(_top(mine[b], signals[b])))
            for a, b in zip(dates, dates[1:])
            if (pd.Timestamp(b) - pd.Timestamp(a)).days <= 7]
    return {
        "date": latest,
        "share": share,                                           # 신호별 영향 비중(합 1)
        "direction": direction,                                   # 신호별 반영 방향(+가 정상)
        "similarity_to_default": _corr(mine[latest], base[latest]),
        "top10": top_mine,
        "top10_overlap_with_default": len(set(top_mine) & set(top_base)),
        "top10_kept_next_day": (float(np.mean(keep)) if keep else None),
    }
