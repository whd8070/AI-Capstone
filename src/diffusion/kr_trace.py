"""Local request observation, independent of investment and validation decisions."""
from __future__ import annotations
import contextvars
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "logs" / "trace.jsonl"
ACTIVE = contextvars.ContextVar("trace", default=None)

def text(value):
    if value is None:
        return None
    if os.environ.get("AI_CAPSTONE_TRACE_TEXT") != "1":
        return "[TEXT OMITTED]"
    s = str(value)[:60000]
    s = re.sub(r"(?i)\b(?:bearer\s+|(?:api[_ -]?key|access[_ -]?token|authorization|password|secret)\s*[:=]\s*)[^\s,;]+", "[REDACTED]", s)
    s = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,})\b", "[REDACTED]", s)
    s = re.sub(r"\b[A-Za-z0-9_-]{25,}\b", "[REDACTED]", s)
    s = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED]", s)
    s = re.sub(r"(?<!\d)(?:\+82[- ]?)?0?1[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)", "[REDACTED]", s)
    s = re.sub(r"(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)", "[REDACTED]", s)
    return re.sub(r"(?i)(?:[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]|/(?:home|Users)/)[^\s\"']+", "[LOCAL PATH]", s)

def formula(value):
    if value is None:
        return None
    s = str(value)
    allowed = {"mom", "pair", "report", "abs", "min", "max", "clip", "tanh", "sign", "pos", "where", "rank_z", "e", "E"}
    if len(s) <= 300 and re.fullmatch(r"[A-Za-z0-9_ .,+*/<>=()\-]+", s) and set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", s)) <= allowed:
        return s
    return text(s)

def model_id(value):
    s = str(value or "")
    return s if re.fullmatch(r"(?:claude|haiku|sonnet|opus|gpt|o[1-9]|codex|stable|local|none)[A-Za-z0-9._:-]{0,80}", s, re.I) else "unresolved"

def version(name):
    try:
        return hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()[:16]
    except OSError:
        return None

def commit():
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=3, check=True)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"

def plain(v):
    if v is None or isinstance(v, (str, bool, int)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if hasattr(v, "item"):
        try:
            return plain(v.item())
        except (TypeError, ValueError):
            pass
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return None

def append(record, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(plain(record), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    with path.with_suffix(".lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if not lock.tell():
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            with path.open("ab") as stream:
                stream.write(payload)
                stream.flush()
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

class Trace:
    def __init__(self, action, inputs, *, model="none", prompt_version=None, path=None, envelope=None):
        self.path = Path(path) if path is not None else PATH
        self.started = time.time()
        self.record = envelope if envelope is not None else dict(
            schema_version=1, request_id=uuid.uuid4().hex,
            ts=dt.datetime.now(dt.timezone.utc).isoformat(), action=action,
            input=plain(inputs), stages=[], output=None, commit=commit(),
            model=model_id(model), model_resolution="configured identifier; CLI default not independently resolved",
            prompt_version=prompt_version, started_epoch=self.started,
            text_capture=os.environ.get("AI_CAPSTONE_TRACE_TEXT") == "1")
        self.started = self.record.get("started_epoch", self.started)
        self.finished = self.deferred = False

    @classmethod
    def resume(cls, envelope):
        return cls("backtest", {}, envelope=envelope)

    def __enter__(self):
        self.token = ACTIVE.set(self)
        return self

    def __exit__(self, kind, exc, tb):
        ACTIVE.reset(self.token)
        if not self.finished and not self.deferred:
            self.finish("error" if exc else "completed", error=exc)
        return False

    def step(self, stage, result=None):
        try:
            self.record["stages"].append(dict(stage=stage, elapsed_ms=max(0, round((time.time()-self.started)*1000)), result=plain(result)))
        except Exception:
            pass

    def defer(self):
        self.deferred = True

    def finish(self, status, output=None, *, error=None):
        if self.finished:
            return
        self.finished = True
        try:
            self.record.update(status=status, output=plain(output),
                latency_ms=max(0, round((time.time()-self.started)*1000)),
                error={"type": type(error).__name__, "message": text(error)} if isinstance(error, BaseException) else {"type": str(error)} if error else None)
            self.record.pop("started_epoch", None)
            append(self.record, self.path)
        except Exception:
            print("[trace] Unable to append request trace; check logs directory permissions.", file=sys.stderr, flush=True)

def observe(stage, result=None):
    tr = ACTIVE.get()
    if tr is not None:
        tr.step(stage, result)

def diagnostic(v):
    return plain({k: v.get(k) for k in ("date", "share", "direction", "similarity_to_default", "top10", "top10_overlap_with_default", "top10_kept_next_day")}) if isinstance(v, dict) else None

def proposal(r):
    return dict(formula=formula(r.get("formula")), explanation=text(r.get("explanation")),
        source=r.get("source"), diag=diagnostic(r.get("diag")), default_diag=diagnostic(r.get("default_diag")),
        issues=[text(x) for x in r.get("issues", [])],
        attempts=[dict(formula=formula(a.get("formula")), explanation=text(a.get("explanation")),
            diag=diagnostic(a.get("diag")), issues=[text(x) for x in a.get("issues", [])],
            error=text(a.get("error"))) for a in r.get("attempts", [])],
        usage={k:r.get("usage", {}).get(k) for k in ("calls","tokens","cost_usd")}, stop_reason=text(r.get("stop_reason")))

def verification(v):
    if not isinstance(v, dict):
        return None
    claims = []
    for item in v.get("claims", [])[:250]:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("claim_id", ""))
        verdict = item.get("verdict")
        refs = item.get("evidence_refs", [])
        claims.append(dict(
            claim_id=cid if re.fullmatch(r"C[0-9]{1,5}", cid) else "[INVALID ID]",
            verdict=verdict if verdict in ("pass", "warn", "reject") else "unknown",
            reason_code=text(item.get("reason_code")),
            evidence_refs=[r if isinstance(r, str) and re.fullmatch(r"(settings|portfolio|risk|scenario|rank:[0-9]{6}|report:[0-9]+)", r) else "[OMITTED]" for r in refs[:8]] if isinstance(refs, list) else []))
    return dict(status=v.get("status"), backend=model_id(v.get("backend")), claim_count=v.get("claim_count"),
        errors=[text(e) for e in v.get("errors", [])], content_sha256=v.get("content_sha256"), claims=claims)

def portfolio(r):
    if not isinstance(r, dict):
        return None
    return dict(buy_date=str(r.get("buy_date")), decision_date=str(r.get("decision_date")),
        formula=formula(r.get("formula")), report_coverage=r.get("report_coverage"),
        agent_used=model_id(r.get("agent_used")), agent_warning=text(r.get("agent_warning")),
        explanation=text(r.get("explanation")), verification=verification(r.get("verification")),
        stage_seconds=r.get("stage_seconds"),
        comparison=[{k:row.get(k) for k in ("stock_code","rank_before","rank_after","before_weight","after_weight","report_available")} for row in r.get("comparison", [])])

def prior_portfolio(state):
    r = state.get("kr_report_portfolio")
    return dict(present=r is not None, buy_date=str(r.get("buy_date")) if isinstance(r, dict) else None,
        formula=formula(r.get("formula")) if isinstance(r, dict) else None)

def metrics(r):
    keys = ("total_return","annualized_return","sharpe","max_drawdown","annual_volatility","total_fees","decisions","trades","first_signal_date","last_mark_date")
    return {side:{k:r.get("metrics_"+side, {}).get(k) for k in keys} for side in ("before","after")}
