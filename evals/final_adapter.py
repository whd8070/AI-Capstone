"""Final-eval adapters: deterministic production-path tests, no live LLM or market fetch.

The UI handler is extracted from the actual Streamlit source and executed with
controlled UI/engine doubles; this tests state transitions, not browser E2E.
The date probe invokes the actual backtest engine up to the market-load boundary.
Attack cases test code gates with synthetic hostile inputs/outputs, not live
prompt-injection resistance.
"""
from __future__ import annotations
import ast
import datetime as dt
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from verification_adapter import execute as verify_execute
import kr_formula
import kr_formula_agent
import kr_report_engine
import kr_trace

SRC = Path(__file__).resolve().parents[1] / "src" / "diffusion"


def portfolio_state(query):
    class UI:
        def __init__(self):
            self.session_state = {"kr_report_portfolio": {
                "buy_date": query["previous_buy_date"], "formula": query["formula"]}}
        def button(self, *args, **kwargs):
            return True
        def status(self, *args, **kwargs):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def empty(self):
            return self
        def update(self, **kwargs):
            pass
        def info(self, *args):
            pass
        def exception(self, *args):
            pass
        def error(self, *args):
            pass

    def fail(*args, **kwargs):
        raise RuntimeError("Missing exact requested session " + query["buy_date"] + "; refuse stale/ffilled signal")

    tree = ast.parse((SRC / "kr_report_web.py").read_text(encoding="utf-8"))
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.If)
             and isinstance(n.test, ast.Call)
             and any(k.arg == "key" and isinstance(k.value, ast.Constant)
                     and k.value.value == "portfolio_run" for k in n.test.keywords)]
    if len(nodes) != 1:
        raise RuntimeError("Portfolio UI handler changed; audit adapter before measuring")
    ui = UI()
    with tempfile.TemporaryDirectory() as folder, patch.object(kr_trace, "PATH", Path(folder) / "trace.jsonl"):
        env = dict(st=ui, trace=kr_trace, eng=SimpleNamespace(portfolio_for_buy_date=fail),
                   PROJECT=SRC, buy_date=dt.date.fromisoformat(query["buy_date"]),
                   pair=.5, report=.5, k=128, seed=0, threads=4, fetch=True, formula=query["formula"])
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SRC / "kr_report_web.py"), "exec"), env)
    remaining = ui.session_state.get("kr_report_portfolio")
    return {"status": "PASS" if remaining is None else "FAIL",
            "remaining_buy_date": remaining.get("buy_date") if remaining else None}


def backtest_date(query):
    class ProbeComplete(Exception):
        pass
    requested = []
    def load_market(project, asof, **kwargs):
        requested.append(str(pd.Timestamp(asof).date()))
        if requested[-1] != query["effective_end"]:
            raise RuntimeError("Exact requested session is not observed")
        raise ProbeComplete
    fake = SimpleNamespace(now_kst=lambda: dt.datetime(2026, 11, 26, 20),
                           CLOSE_READY=dt.time(18), load_market=load_market)
    try:
        with patch.dict(sys.modules, {"kr_pair_cpu": fake}):
            kr_report_engine.backtest(SRC, query["start"], query["end"], fetch=False)
    except ProbeComplete:
        return {"status": "PASS", "market_request": requested[-1]}
    except (ValueError, RuntimeError) as exc:
        return {"status": "FAIL", "market_request": requested[-1] if requested else None,
                "error": type(exc).__name__}
    raise RuntimeError("Date probe did not reach market boundary")


def formula_attack(query):
    payload = query["formula"]
    if query.get("agent"):
        def hostile(_prompt):
            return {"formula": payload, "explanation": "synthetic hostile output"}, {"tokens": 0}
        result = kr_formula_agent.propose(query["profile"], query.get("note", ""), call=hostile)
        accepted = result["source"] == "agent" and result["formula"] == payload
        return {"status": "FAIL" if accepted else "PASS", "attack_success": accepted,
                "source": result["source"], "rejected_attempts": sum("error" in a for a in result["attempts"])}
    try:
        x = np.linspace(-1, 1, 44)
        kr_formula.score(payload, x, x[::-1], np.roll(x, 3))
    except kr_formula.FormulaError:
        return {"status": "PASS", "attack_success": False}
    return {"status": "FAIL", "attack_success": True}


def execute(query):
    kind = query["kind"]
    if kind == "portfolio_state":
        actual = portfolio_state(query)
    elif kind == "backtest_date":
        actual = backtest_date(query)
    elif kind == "formula_attack":
        actual = formula_attack(query)
    elif kind == "verify_attack":
        actual = verify_execute({**query, "kind": "verify"})
        if any(str(x).startswith("VERIFIER_ERROR:") for x in actual.get("errors", [])):
            actual["attack_success"] = None
        else:
            actual["attack_success"] = actual["status"] == "PASS"
        return actual
    else:
        return verify_execute(query)
    actual.update(claim_count=0, content_sha256=hashlib.sha256(
        json.dumps(query, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), errors=[])
    return actual
