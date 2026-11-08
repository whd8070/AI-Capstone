"""Local-only backtest process manager; prevents duplicate concurrent heavy jobs."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import psutil

import kr_report_engine as engine


def jobs_root(project):
    d=Path(project).resolve()/'results'/'kr_report_dashboard'/'jobs'
    d.mkdir(parents=True,exist_ok=True)
    return d


def status(jobdir):
    """Read queued snapshot + latest COMPLETE append-only worker status.

    Legacy jobs with only status.json continue to work. A partially appended
    line is ignored; the last valid event remains visible.
    """
    folder=Path(jobdir)
    state={'status':'unknown'}
    snapshot=folder/'status.json'
    if snapshot.exists():
        try:
            state.update(json.loads(snapshot.read_text(encoding='utf-8')))
        except (OSError,ValueError,TypeError):
            pass
    journal=folder/'status_updates.jsonl'
    if journal.exists():
        try:
            with journal.open('r',encoding='utf-8') as log:
                for line in log:
                    if not line.endswith('\n'):
                        break  # potentially half-written last record
                    try:
                        event=json.loads(line)
                        if isinstance(event,dict):
                            state.update(event)
                    except ValueError:
                        continue
        except OSError:
            pass
    if not state.get('pid'):
        spawned=folder/'spawn.pid'
        if spawned.exists():
            try:
                state['pid']=int(spawned.read_text(encoding='ascii').strip())
            except (ValueError,OSError):
                pass
    return state


def active_jobs(project):
    for folder in jobs_root(project).iterdir():
        if not folder.is_dir():
            continue
        s=status(folder)
        if s.get('status') not in ('running','queued'):
            continue
        pid=int(s.get('pid') or 0)
        if pid and psutil.pid_exists(pid):
            try:
                cmdline = ' '.join(psutil.Process(pid).cmdline())
                if 'kr_report_job.py' in cmdline and str(folder) in cmdline:
                    yield folder
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue


def submit(project, request):
    project=Path(project).resolve()
    request={'mode':'backtest','project':str(project),**request,
             'K':engine.FIXED_K,'seed':engine.FIXED_SEED}
    signature=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()[:16]
    root=jobs_root(project)
    folder=root/signature
    lock=root/'.launch.lock'
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise RuntimeError('다른 실행 요청을 등록 중입니다. 중복 실행을 피하기 위해 거부했습니다.')
    try:
        os.close(fd)
        concurrent=list(active_jobs(project))
        if concurrent:
            existing=concurrent[0]
            if existing == folder:
                return folder,False
            raise RuntimeError(f'다른 백테스트가 실행 중입니다: {existing}. '
                               '공유 시나리오/피처 캐시 충돌을 피하려면 완료 후 실행하세요.')
        folder.mkdir(parents=True,exist_ok=True)
        engine.write_json(folder/'request.json',request)
        # Re-running the same job ID must not read completed events from its old run.
        (folder/'status_updates.jsonl').write_bytes(b'')
        (folder/'spawn.pid').write_text('',encoding='ascii')
        engine.write_json(folder/'status.json',{'status':'queued','step':'시작 대기','progress':0})
        flags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
        with (folder/'worker.log').open('a',encoding='utf-8') as log:
            proc=subprocess.Popen([sys.executable,str(project/'kr_report_job.py'),
                                   '--job-dir',str(folder)],cwd=project,
                                  stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                                  creationflags=flags,close_fds=True)
        # Worker is the ONLY status-event writer. Parent records PID separately,
        # never replacing status.json while the worker is running.
        (folder/'spawn.pid').write_text(str(proc.pid),encoding='ascii')
        return folder,True
    finally:
        if lock.exists():
            lock.unlink()
