"""성향 조사(버튼 4개)와, 그 답으로 정하는 것들.

- QUESTIONS: 화면에 보일 질문·선택지
- fallback_formula: LLM 없이 규칙만으로 만드는 수식(에이전트가 실패했을 때의 안전망)
- check_expectations: 수식의 점검 결과가 성향과 어긋나는 점(코드가 판정, LLM이 아님)
"""

QUESTIONS = [
    {"key": "base", "text": "과거 주가 흐름과 모델의 전망 중 무엇을 더 믿나요?",
     "options": [("mom", "최근 주가 흐름(모멘텀)"), ("balanced", "둘 다 비슷하게"), ("pair", "확산모델의 종목별 전망")]},
    {"key": "trust", "text": "증권사 리포트의 목표가를 얼마나 믿나요?",
     "options": [("low", "참고만 한다"), ("mid", "보통"), ("high", "많이 믿는다")]},
    {"key": "report_use", "text": "리포트 의견은 언제 반영할까요?",
     "options": [("always", "항상 반영"), ("strong_only", "의견이 뚜렷할 때만")]},
    {"key": "conflict", "text": "신호들이 서로 엇갈리면 어떻게 할까요?",
     "options": [("average", "그대로 평균"), ("conservative", "낮은 쪽 기준으로 보수적으로"),
                 ("follow_strong", "더 강한 신호를 따라간다")]},
]
DEFAULT_PROFILE = {"base": "balanced", "trust": "mid", "report_use": "always", "conflict": "average"}

_P = {"mom": 0.25, "balanced": 0.5, "pair": 0.75}     # 기존 웹의 p (PAIR 비율)
_R = {"low": 0.2, "mid": 0.5, "high": 0.7}            # 기존 웹의 r (REPORT 비율)


def validate_profile(profile):
    for q in QUESTIONS:
        allowed = [v for v, _ in q["options"]]
        if profile.get(q["key"]) not in allowed:
            raise ValueError(f"{q['key']} 값은 {allowed} 중 하나여야 합니다.")
    return {q["key"]: profile[q["key"]] for q in QUESTIONS}


def describe(profile):
    """성향 답변을 사람이 읽는 문장으로."""
    profile = validate_profile(profile)
    lines = []
    for q in QUESTIONS:
        label = dict(q["options"])[profile[q["key"]]]
        lines.append(f"- {q['text']} → {label}")
    return "\n".join(lines)


def fallback_formula(profile):
    """규칙 기반 수식. 가장 단순한 경우는 기존 (1-r)*((1-p)*mom + p*pair) + r*report와 같다."""
    profile = validate_profile(profile)
    p, r = _P[profile["base"]], _R[profile["trust"]]
    base = f"({1 - p:g}*mom + {p:g}*pair)"
    rep = "report" if profile["report_use"] == "always" else "where(abs(report) > 0.8, report, 0)"
    blend = f"{1 - r:g}*{base} + {r:g}*{rep}"
    if profile["conflict"] == "conservative":
        return f"0.5*({blend}) + 0.5*min({base}, {rep})"
    if profile["conflict"] == "follow_strong":
        return f"0.5*({blend}) + 0.5*where(abs({base}) > abs({rep}), {base}, {rep})"
    return blend


TOLERANCE = 0.03   # 영향 비중 비교의 여유(표본이 44종목이라 작은 차이는 무시)


def check_expectations(profile, diag, default_diag):
    """성향과 어긋나는 점의 목록(없으면 빈 리스트). 기준은 기본 수식 대비 상대 비교."""
    profile = validate_profile(profile)
    share, base = diag["share"], default_diag["share"]
    issues = []
    for name, d in diag["direction"].items():
        if d < -0.05:
            issues.append(f"{name} 신호가 거꾸로 반영됩니다(방향 {d:+.2f}). 점수가 높은 종목이 불리해지면 안 됩니다.")
    if profile["report_use"] == "always":   # '뚜렷할 때만'은 일부 종목에만 반영되므로 총량 비교를 하지 않는다
        if profile["trust"] == "low" and share["report"] > base["report"] - TOLERANCE:
            issues.append(f"리포트를 참고만 한다고 했는데 리포트 영향 비중이 기본 수식보다 작지 않습니다"
                          f"({share['report']:.0%} vs 기본 {base['report']:.0%}).")
        if profile["trust"] == "high" and share["report"] < base["report"] + TOLERANCE:
            issues.append(f"리포트를 많이 믿는다고 했는데 리포트 영향 비중이 기본 수식보다 크지 않습니다"
                          f"({share['report']:.0%} vs 기본 {base['report']:.0%}).")
    gap, base_gap = share["mom"] - share["pair"], base["mom"] - base["pair"]
    if profile["base"] == "mom" and gap < base_gap + TOLERANCE:
        issues.append(f"모멘텀을 더 믿는다고 했는데 모멘텀 비중이 모델 전망보다 충분히 크지 않습니다"
                      f"(mom {share['mom']:.0%}, pair {share['pair']:.0%}).")
    if profile["base"] == "pair" and gap > base_gap - TOLERANCE:
        issues.append(f"모델 전망을 더 믿는다고 했는데 모델 전망 비중이 모멘텀보다 충분히 크지 않습니다"
                      f"(mom {share['mom']:.0%}, pair {share['pair']:.0%}).")
    return issues
