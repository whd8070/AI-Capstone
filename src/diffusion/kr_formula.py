"""신호 결합 수식의 안전한 검사·계산.

사용자가(또는 LLM이) 쓴 수식을 파이썬 코드로 실행하지 않는다(eval/exec 없음).
문자열을 구문 트리로만 분해한 뒤, 아래 허용 목록에 있는 노드만 직접 계산한다.

허용:
  변수  mom, pair, report            (종목별 순위 점수 배열)
  숫자  정수·실수 상수 (절댓값 1000 이하)
  연산  + - * /  단항 -  **(지수는 1~4 정수 상수만)
  비교  > < >= <=                    (결과는 1 또는 0, where의 조건으로 사용)
  함수  abs min max clip tanh sign pos where rank_z
"""
import ast
import math

import numpy as np

VARIABLES = ("mom", "pair", "report")
MAX_CHARS, MAX_NODES, MAX_DEPTH, MAX_CONST = 300, 80, 12, 1000.0


class FormulaError(ValueError):
    """수식이 허용 범위를 벗어났거나 계산 결과를 쓸 수 없을 때."""


def rank_z(x):
    """순위를 평균 0, 분산 1 근처의 점수로 바꾼다(동점은 평균 순위). kr_pair_core.rank_z와 같은 정의."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return np.zeros(n)
    ranks = np.empty(n)
    ranks[np.argsort(x, kind="mergesort")] = np.arange(1, n + 1)
    _, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.zeros(len(cnt))
    np.add.at(sums, inv, ranks)
    ranks = sums[inv] / cnt[inv]
    return (ranks - (n + 1) / 2) / math.sqrt((n * n - 1) / 12)


def _reduce(fn):
    def run(*args):
        out = args[0]
        for a in args[1:]:
            out = fn(out, a)
        return out
    return run


# 이름: (최소 인자 수, 최대 인자 수, 구현)
FUNCTIONS = {
    "abs": (1, 1, np.abs),
    "min": (2, 6, _reduce(np.minimum)),
    "max": (2, 6, _reduce(np.maximum)),
    "clip": (3, 3, lambda x, lo, hi: np.clip(x, lo, hi)),
    "tanh": (1, 1, np.tanh),
    "sign": (1, 1, np.sign),
    "pos": (1, 1, lambda x: np.maximum(x, 0.0)),
    "where": (3, 3, lambda c, a, b: np.where(np.asarray(c) != 0, a, b)),
    "rank_z": (1, 1, None),  # 배열 길이가 필요해 _eval에서 따로 처리
}
_BINOPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide}
_COMPARES = {ast.Gt: np.greater, ast.Lt: np.less, ast.GtE: np.greater_equal, ast.LtE: np.less_equal}


def _check(node, depth, state):
    state["nodes"] += 1
    if state["nodes"] > MAX_NODES:
        raise FormulaError(f"수식이 너무 복잡합니다(항목 {MAX_NODES}개 초과).")
    if depth > MAX_DEPTH:
        raise FormulaError(f"괄호·함수가 너무 깊게 겹쳤습니다({MAX_DEPTH}단계 초과).")
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise FormulaError(f"숫자만 쓸 수 있습니다: {v!r}")
        if not math.isfinite(v) or abs(v) > MAX_CONST:
            raise FormulaError(f"숫자는 절댓값 {MAX_CONST:g} 이하여야 합니다: {v!r}")
    elif isinstance(node, ast.Name):
        if node.id not in VARIABLES:
            raise FormulaError(f"허용되지 않은 이름: {node.id} (변수는 {', '.join(VARIABLES)}만 가능)")
        state["vars"].add(node.id)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        _check(node.operand, depth + 1, state)
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        _check(node.left, depth + 1, state)
        _check(node.right, depth + 1, state)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        e = node.right
        ok = (isinstance(e, ast.Constant) and isinstance(e.value, int)
              and not isinstance(e.value, bool) and 1 <= e.value <= 4)
        if not ok:
            raise FormulaError("거듭제곱의 지수는 1~4 사이 정수 상수만 가능합니다.")
        state["nodes"] += 1
        _check(node.left, depth + 1, state)
    elif isinstance(node, ast.Compare):
        if len(node.ops) != 1 or type(node.ops[0]) not in _COMPARES:
            raise FormulaError("비교는 >, <, >=, <= 중 하나를 한 번만 쓸 수 있습니다.")
        _check(node.left, depth + 1, state)
        _check(node.comparators[0], depth + 1, state)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            name = node.func.id if isinstance(node.func, ast.Name) else "(이름 아님)"
            raise FormulaError(f"허용되지 않은 함수: {name} (가능: {', '.join(FUNCTIONS)})")
        if node.keywords:
            raise FormulaError("함수에 이름 붙은 인자(key=value)는 쓸 수 없습니다.")
        lo, hi, _ = FUNCTIONS[node.func.id]
        if not lo <= len(node.args) <= hi:
            need = f"{lo}개" if lo == hi else f"{lo}~{hi}개"
            raise FormulaError(f"{node.func.id}의 인자는 {need}여야 합니다.")
        for a in node.args:
            _check(a, depth + 1, state)
    else:
        raise FormulaError(f"허용되지 않은 문법: {type(node).__name__}")


def parse(formula):
    """수식을 검사해 구문 트리를 돌려준다. 허용 범위를 벗어나면 FormulaError."""
    if not isinstance(formula, str) or not formula.strip():
        raise FormulaError("수식이 비어 있습니다.")
    if len(formula) > MAX_CHARS:
        raise FormulaError(f"수식이 너무 깁니다({MAX_CHARS}자 초과).")
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        raise FormulaError(f"수식 문법 오류: {getattr(e, 'msg', e)}") from None
    state = {"nodes": 0, "vars": set()}
    _check(tree.body, 1, state)
    if not state["vars"]:
        raise FormulaError("mom, pair, report 중 하나 이상을 써야 합니다.")
    return tree.body


def used_variables(formula):
    state = {"nodes": 0, "vars": set()}
    _check(parse(formula), 1, state)
    return sorted(state["vars"])


def _eval(node, env, n):
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env, n)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, env, n)
        if isinstance(node.op, ast.Pow):
            return np.power(left, node.right.value)
        return _BINOPS[type(node.op)](left, _eval(node.right, env, n))
    if isinstance(node, ast.Compare):
        left, right = _eval(node.left, env, n), _eval(node.comparators[0], env, n)
        return _COMPARES[type(node.ops[0])](left, right).astype(float)
    name = node.func.id  # parse()를 통과했으므로 남은 것은 허용된 함수 호출뿐
    args = [_eval(a, env, n) for a in node.args]
    if name == "rank_z":
        return rank_z(np.broadcast_to(np.asarray(args[0], float), (n,)))
    return FUNCTIONS[name][2](*args)


def raw_values(formula, mom, pair, report):
    """수식의 계산값(순위화 전). 결과가 유한하지 않으면 FormulaError."""
    tree = parse(formula)
    env = {k: np.asarray(v, float) for k, v in zip(VARIABLES, (mom, pair, report))}
    n = len(env["mom"])
    if not all(v.shape == (n,) for v in env.values()):
        raise FormulaError("mom, pair, report의 종목 수가 서로 다릅니다.")
    with np.errstate(all="ignore"):
        out = np.broadcast_to(np.asarray(_eval(tree, env, n), float), (n,)).copy()
    if not np.isfinite(out).all():
        raise FormulaError("계산 결과에 무한대나 숫자가 아닌 값이 있습니다(0으로 나누기 등).")
    return out


MAX_ABS_SCORE = 5.0   # 입력 신호가 대략 -1.7~+1.7이므로, 이보다 크면 계수가 지나치게 큰 수식이다


def blend(formula, mom, pair, report):
    """기존 코드의 after_score 자리에 넣는 값: 수식의 계산값에서 평균만 뺀 것.

    뒤의 위험 최적화는 점수의 순서뿐 아니라 크기와 수준도 쓴다. 그래서
    - 크기는 그대로 둔다(기본 수식 0.5*(0.5*mom+0.5*pair)+0.5*report는 슬라이더 p=r=0.5와 같은 값이 된다).
    - 평균은 0으로 맞춘다(min, where 같은 연산이 전체 점수 수준을 한쪽으로 밀지 않게).
    - 크기가 신호 범위를 크게 벗어나면 거부한다.
    """
    out = raw_values(formula, mom, pair, report)
    if np.ptp(out) < 1e-12:
        raise FormulaError("모든 종목의 점수가 같아 순위를 매길 수 없습니다.")
    out = out - out.mean()
    if np.abs(out).max() > MAX_ABS_SCORE:
        raise FormulaError(f"점수 크기가 너무 큽니다(최대 {np.abs(out).max():.1f}, 허용 {MAX_ABS_SCORE:g}). "
                           "계수의 합이 1 근처가 되게 줄이세요.")
    return out


def score(formula, mom, pair, report):
    """순위 점수(점검·비교용). blend()와 같은 검사를 거친 뒤 순위로 바꾼다."""
    return rank_z(blend(formula, mom, pair, report))
