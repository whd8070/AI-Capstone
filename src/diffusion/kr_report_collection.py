"""Read-only Claude login check, coverage preview and progress-aware local commands.

Never reads or writes Claude tokens; authentication is completed by the user in a
separate terminal via `claude auth login`.
"""
from __future__ import annotations

import csv
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path


def claude_executable():
    """Locate a standalone Claude CLI even if the Streamlit server has a stale PATH.

    Prefer the documented native installation over another command named 'claude'
    (for example a desktop app shim). Never inspect or copy auth files.
    """
    native = Path.home() / '.local' / 'bin' / ('claude.exe' if os.name == 'nt' else 'claude')
    if native.is_file() and (os.name == 'nt' or os.access(native, os.X_OK)):
        return str(native)
    return shutil.which('claude')


def claude_env():
    """Pass an amended PATH only to child jobs; do not alter OS-level settings."""
    env = os.environ.copy()
    exe = claude_executable()
    if exe:
        folder = str(Path(exe).parent)
        parts = [p for p in env.get('PATH', '').split(os.pathsep) if p]
        normalized = os.path.normcase(os.path.normpath(folder))
        if all(os.path.normcase(os.path.normpath(p)) != normalized for p in parts):
            env['PATH'] = folder + (os.pathsep + env['PATH'] if env.get('PATH') else '')
    return env


def claude_status(*, timeout=10):
    """Return a sanitized CLI auth state. Do not surface credential JSON or email."""
    exe = claude_executable()
    if not exe:
        return {'state': 'not_installed', 'ready': False,
                'message': 'Claude Code CLI를 찾지 못했습니다. 선택적 설정 스크립트로 설치/PATH 등록을 진행하세요.'}
    try:
        result = subprocess.run([exe, 'auth', 'status'], capture_output=True,
                                text=True, encoding='utf-8', errors='replace',
                                timeout=timeout, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {'state': 'check_failed', 'ready': False,
                'message': '인증 상태 확인이 실패했습니다. 터미널에서 claude auth status를 실행하세요.'}
    if result.returncode == 1:
        return {'state': 'not_logged_in', 'ready': False,
                'message': 'Claude 로그인 필요: 터미널에서 claude auth login 실행'}
    if result.returncode != 0:
        return {'state': 'check_failed', 'ready': False,
                'message': 'Claude 인증 상태 확인 실패. 터미널에서 claude auth status 실행'}
    try:
        parsed = json.loads(result.stdout)
        if isinstance(parsed, dict) and parsed.get('loggedIn') is False:
            return {'state': 'not_logged_in', 'ready': False,
                    'message': 'Claude 로그인 필요: 터미널에서 claude auth login 실행'}
    except (json.JSONDecodeError, TypeError):
        pass
    # Do not expose auth JSON; only the executable path is visible locally.
    return {'state': 'ready', 'ready': True, 'executable': exe,
            'message': 'Claude CLI 로그인 확인됨. 실행 시 계정 이용한도/요금이 적용될 수 있습니다.'}


def collection_plan(project, until):
    """Local-only preview: no network access, no report downloads or CLI calls."""
    import pandas as pd
    import kr_report_engine as engine
    p = engine.report_files(project)
    source = pd.read_csv(p['original'], encoding='utf-8-sig', usecols=['date'])
    latest = pd.to_datetime(source.date, errors='coerce').dropna().max()
    if pd.isna(latest):
        raise ValueError('기본 컨센서스 날짜를 확인할 수 없습니다.')
    end = pd.Timestamp(until).normalize()
    begin = max(latest + pd.Timedelta(days=1), end - pd.Timedelta(days=engine.WINDOW_DAYS))
    from kr_pair_bootstrap import TRAINED_TICKERS
    allowed = set(TRAINED_TICKERS)
    manifest = engine.repository_root(project)/'agents'/'collection'/'data'/'manifest.csv'
    raw = engine.repository_root(project)/'agents'/'collection'/'data'/'out'/'reports.jsonl'
    known = []
    if manifest.is_file() and begin <= end:
        with manifest.open(encoding='utf-8-sig', newline='') as f:
            known = [row for row in csv.DictReader(f)
                     if row.get('stock_code') in allowed and str(begin.date()) <= row.get('date', '') <= str(end.date())
                     and row.get('pdf_path')]
    done = set()
    if raw.is_file():
        with raw.open(encoding='utf-8-sig') as f:
            for line in f:
                if line.strip():
                    try:
                        done.add(str(json.loads(line)['nid']))
                    except (ValueError, KeyError):
                        continue
    unique = {str(x['nid']): x for x in known if x.get('nid')}
    return {'start': str(begin.date()), 'end': str(end.date()),
            'can_fetch': bool(begin <= end),
            'already_downloaded': len(unique),
            'already_extracted': sum(nid in done for nid in unique),
            'pending_extraction': sum(nid not in done for nid in unique),
            'note': '추가로 네이버에서 발견될 리포트 수는 실제 조회 전에는 알 수 없습니다.'}


def run_stage(argv, *, cwd, stage, callback=None, timeout=7200):
    """Run a fixed argv (never shell input); show sanitized progress without storing keys."""
    proc = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=claude_env(), text=True, encoding='utf-8', errors='replace', bufsize=1)
    lines = deque(maxlen=60)
    q = queue.Queue()

    def drain():
        try:
            for line in proc.stdout:
                q.put(line.rstrip())
        finally:
            q.put(None)

    threading.Thread(target=drain, daemon=True).start()
    deadline = time.monotonic() + timeout
    finished = False
    count = 0
    try:
        while not finished:
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise TimeoutError(f'{stage} 단계 시간 초과')
            try:
                line = q.get(timeout=0.3)
            except queue.Empty:
                continue
            if line is None:
                finished = True
            else:
                # Never pass raw Claude auth output; only process log lines.
                lines.append(line)
                count += 1
                if callback and (count <= 5 or count % 10 == 0 or line.startswith(('[ok', '[fail', '==', '[error'))):
                    callback(stage, line[:350])
    finally:
        if proc.poll() is None:
            proc.kill()
        if proc.stdout:
            proc.stdout.close()
    rc = proc.wait(timeout=5)
    output = '\n'.join(lines)
    if rc:
        raise RuntimeError(f'{stage} 실패 (종료코드 {rc}). 최근 출력:\n{output[-2200:]}')
    return output[-1400:]
