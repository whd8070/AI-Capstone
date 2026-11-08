"""Regression tests for WinError 5 progress journal and fixed inference settings."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import datetime as dt
import sys

import kr_report_engine as engine
import kr_report_job as worker
import kr_report_jobs as jobs


class WindowsProgressTests(unittest.TestCase):
    def test_worker_never_replaces_polled_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            engine.write_json(folder/'status.json', {'status':'queued','progress':0})
            worker.update_status(folder,status='running',progress=1,step='first')
            worker.update_status(folder,status='done',progress=2,step='complete')
            self.assertEqual(json.loads((folder/'status.json').read_text())['status'],'queued')
            state=jobs.status(folder)
            self.assertEqual(state['status'],'done')
            self.assertEqual(state['progress'],2)
            self.assertEqual(state['step'],'complete')
            self.assertEqual(len((folder/'status_updates.jsonl').read_text().splitlines()),2)

    def test_partial_last_line_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            engine.write_json(folder/'status.json',{'status':'queued'})
            worker.update_status(folder,status='running',progress=1)
            with (folder/'status_updates.jsonl').open('ab') as fh:
                fh.write(b'{"status":"failed",')  # writer interrupted
            state=jobs.status(folder)
            self.assertEqual(state['status'],'running')
            self.assertEqual(state['progress'],1)

    def test_progress_reads_and_writes_concurrently(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            engine.write_json(folder/'status.json',{'status':'queued'})
            errors=[]
            def send():
                try:
                    for i in range(300):
                        worker.update_status(folder,status='running',progress=i)
                    worker.update_status(folder,status='done',progress=300)
                except Exception as exc:
                    errors.append(exc)
            thread=threading.Thread(target=send)
            thread.start()
            while thread.is_alive():
                try:
                    self.assertIn(jobs.status(folder)['status'],['queued','running','done'])
                except Exception as exc:
                    errors.append(exc)
            thread.join()
            self.assertFalse(errors, errors)
            self.assertEqual(jobs.status(folder)['progress'],300)
            self.assertEqual(jobs.status(folder)['status'],'done')

    def test_write_json_retries_transient_windows_access_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'result.json'
            path.write_text('old',encoding='utf-8')
            original=Path.replace
            count=0
            def flaky_replace(source,target):
                nonlocal count
                count+=1
                if count <= 2:
                    raise PermissionError(5,'WinError 5 simulated')
                return original(source,target)
            with patch.object(Path,'replace',flaky_replace):
                engine.write_json(path,{'ok':True})
            self.assertEqual(count,3)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),{'ok':True})
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_jobs_submit_forces_k128_seed0(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory)
            with patch.object(jobs,'active_jobs',return_value=iter([])), patch.object(
                    jobs.subprocess,'Popen',return_value=SimpleNamespace(pid=321000)):
                folder, launched=jobs.submit(project,dict(
                    start='2025-11-05',end='2025-12-31',pair_share=.3,
                    report_share=.4,K=2,seed=77))
            self.assertTrue(launched)
            request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
            self.assertEqual(request['K'],128)
            self.assertEqual(request['seed'],0)
            self.assertEqual(jobs.status(folder)['pid'],321000)

    def test_worker_forces_k128_seed0_despite_legacy_request(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory)
            folder=project/'results'/'kr_report_dashboard'/'jobs'/'legacy'
            folder.mkdir(parents=True)
            engine.write_json(folder/'status.json', {'status':'queued'})
            engine.write_json(folder/'request.json',{
                'mode':'backtest','project':str(project),'start':'2025-11-05',
                'end':'2025-12-31','K':2,'seed':44})
            seen={}
            def fake_backtest(project_,**opts):
                seen.update(opts)
                opts['progress'](1,1,dt.datetime(2025,11,6))
                return {'metrics_after':{'decisions':1},'path':project}
            with patch.object(worker.engine,'backtest',side_effect=fake_backtest), patch.object(
                    sys,'argv',['kr_report_job.py','--job-dir',str(folder)]):
                worker.main()
            self.assertEqual((seen['K'],seen['seed']),(128,0))
            self.assertEqual(jobs.status(folder)['status'],'done')
            self.assertEqual(json.loads((folder/'status.json').read_text())['status'],'queued')


if __name__=='__main__':
    unittest.main()
