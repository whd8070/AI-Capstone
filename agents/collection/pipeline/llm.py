"""LLM 호출. 모든 백엔드는 call(header, text, schema) -> (result_dict, usage_dict).

usage 키: input_tokens(캐시 포함 전체), cached_input_tokens, output_tokens, cost_usd(모르면 None), turns

[claude] Claude Code CLI (Max 구독 로그인)
  토큰 절감 설계:
   - 기본 시스템 프롬프트 대신 짧은 추출 전용 프롬프트(--system-prompt-file)
   - 도구 끔(--tools "") : 리포트 텍스트는 stdin으로 넘기므로 파일 읽기 왕복이 없음 → 1회 호출로 끝
   - 빈 임시 폴더에서 실행 : 프로젝트 CLAUDE.md 가 매 호출에 실리지 않게
   - 기본 모델 haiku
[api]    Claude API 직접 호출 (ANTHROPIC_API_KEY 필요, 대량 처리용)
[mock]   LLM 없이 흐름만 시험 (빈 결과 반환)
"""
import json
import shlex
import shutil
import subprocess
import tempfile

from . import config

_SANDBOX = None


def _sandbox_dir():
    global _SANDBOX
    if _SANDBOX is None:
        _SANDBOX = tempfile.mkdtemp(prefix="rf_claude_")
    return _SANDBOX


def call_claude(header, text, schema):
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("'claude' 명령을 찾을 수 없습니다 (Claude Code CLI 설치·PATH 확인)")
    cmd = [exe, "-p", header + "\n아래 stdin으로 리포트 본문이 주어진다.",
           "--output-format", "json",
           "--json-schema", json.dumps(schema, ensure_ascii=False),
           "--system-prompt-file", str(config.SYSTEM_PROMPT_FILE),
           "--model", config.CLAUDE_MODEL,
           "--max-turns", "3"]
    cmd += shlex.split(config.CLAUDE_EXTRA) if config.CLAUDE_EXTRA else []
    proc = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8",
                          cwd=_sandbox_dir(), timeout=config.CLAUDE_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"claude 실패(code {proc.returncode}): {(proc.stderr or proc.stdout)[-600:]}")
    data = json.loads(proc.stdout)
    if data.get("is_error") or data.get("structured_output") is None:
        raise RuntimeError(f"구조화 결과 없음: {str(data.get('result'))[:300]}")
    u = data.get("usage") or {}
    cached = u.get("cache_read_input_tokens", 0) or 0
    total_in = (u.get("input_tokens", 0) or 0) + cached + (u.get("cache_creation_input_tokens", 0) or 0)
    return data["structured_output"], {"input_tokens": total_in, "cached_input_tokens": cached,
                                       "output_tokens": u.get("output_tokens", 0) or 0,
                                       "cost_usd": data.get("total_cost_usd"),
                                       "turns": data.get("num_turns")}


def call_api(header, text, schema):
    import anthropic
    client = anthropic.Anthropic(max_retries=6)
    system = config.SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    resp = client.messages.create(
        model=config.API_MODEL, max_tokens=2000, temperature=0,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[{"name": "submit", "description": "추출 결과 제출", "input_schema": schema}],
        tool_choice={"type": "tool", "name": "submit"},
        messages=[{"role": "user", "content": f"{header}\n\n{text}"}])
    block = next(b for b in resp.content if b.type == "tool_use")
    u = resp.usage
    cached = getattr(u, "cache_read_input_tokens", 0) or 0
    return block.input, {"input_tokens": u.input_tokens + cached, "cached_input_tokens": cached,
                         "output_tokens": u.output_tokens, "cost_usd": None, "turns": 1}


def call_mock(header, text, schema):
    return ({"target_price": None, "horizon": None, "horizon_stated": False,
             "earnings_forecast": [], "rationale": [], "risks": []},
            {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "cost_usd": None, "turns": 0})


BACKENDS = {"claude": call_claude, "api": call_api, "mock": call_mock}
