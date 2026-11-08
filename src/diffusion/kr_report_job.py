"""Persistent subprocess runner for long backtests; no Jupyter/Streamlit session dependency."""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import kr_report_engine as engine


def update_status(folder, **fields):
    """Append one complete status event; do not replace a file Streamlit reads.

    Only this worker writes the journal. The UI reads the latest complete JSONL
    line and ignores any trailing incomplete write. Windows rename conflicts
    with a polling status.json reader are therefore avoided entirely.
    """
    event = {**fields, 'updated_at': datetime.now().isoformat(timespec='seconds'),
             'pid': os.getpid()}
    record = (json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    with (folder/'status_updates.jsonl').open('ab') as out:
        out.write(record)
        out.flush()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--job-dir',required=True,type=Path)
    args=ap.parse_args()
    folder=args.job_dir.expanduser().resolve()
    data=json.loads((folder/'request.json').read_text(encoding='utf-8'))
    if data.get('mode')!='backtest':
        raise ValueError('Only backtest mode supported by worker')
    project=Path(data['project']).resolve()
    if folder.parent.resolve() != (project/'results'/'kr_report_dashboard'/'jobs').resolve():
        raise ValueError('Unrecognized job folder')
    update_status(folder,status='running',step='initializing',progress=0,total=None)
    try:
        warned = False
        def progress(i,n,d):
            nonlocal warned
            try:
                update_status(folder,status='running',step=f'신호 {i}/{n}: {d.date()}',progress=i,total=n)
            except OSError as exc:
                if not warned:
                    print(f'[status] Progress update failed (backtest continues): {exc}',
                          file=sys.stderr, flush=True)
                    warned = True
        keys=['start','end','pair_share','report_share','K','seed','batch','threads',
              'sleeves','fee_bps_side','fetch','max_signals']
        opts={k:data[k] for k in keys if k in data}
        # Never execute arbitrary historical K/seed from a stale queued request.
        opts['K'], opts['seed'] = engine.FIXED_K, engine.FIXED_SEED
        result=engine.backtest(project,**opts,progress=progress)
        update_status(folder,status='done',step='완료',progress=result['metrics_after']['decisions'],
                      total=result['metrics_after']['decisions'],result_path=str(result['path']))
    except Exception as exc:
        update_status(folder,status='failed',step='실패',error=f'{type(exc).__name__}: {exc}',
                      traceback=traceback.format_exc()[-10000:])
        raise


if __name__=='__main__':
    main()
