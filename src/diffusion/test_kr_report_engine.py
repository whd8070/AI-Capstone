"""Offline tests for report point-in-time filter; run in src/diffusion after dependencies."""
from __future__ import annotations

import unittest
import hashlib
import tempfile
import types
from unittest.mock import patch
from pathlib import Path
import numpy as np
import pandas as pd

import kr_report_engine as e


class TimeGuardTests(unittest.TestCase):
    def setUp(self):
        self.names = ['000001','000002','000003','000004']
        self.raw = pd.Series([100,200,100,100],index=self.names,dtype=float)
        self.consensus = pd.DataFrame([
            {'stock_code':'000001','date':'2026-01-08','tp_median':120,'n_brokers_90d':2,'company':'A'},
            {'stock_code':'000001','date':'2026-01-12','tp_median':999,'n_brokers_90d':9,'company':'A'},
            {'stock_code':'000002','date':'2026-01-09','tp_median':300,'n_brokers_90d':1,'company':'B'},
            {'stock_code':'000003','date':'2025-07-01','tp_median':10000,'n_brokers_90d':1,'company':'C'},
        ])
        self.consensus['date'] = pd.to_datetime(self.consensus['date'])

    def test_buy_date_report_not_used(self):
        z,meta,count=e.report_view(self.consensus,self.names,'2026-01-09','2026-01-12',self.raw)
        self.assertEqual(count,2)
        self.assertEqual(meta['000001']['report_date'],'2026-01-08')
        self.assertEqual(meta['000002']['report_date'],'2026-01-09')
        self.assertIsNone(meta['000003']['report_date'])
        self.assertGreater(z[1],z[0])
        self.assertAlmostEqual(z[2],z[3])

    def test_no_same_or_future_signal(self):
        with self.assertRaises(ValueError):
            e.report_view(self.consensus,self.names,'2026-01-12','2026-01-12',self.raw)
        with self.assertRaises(ValueError):
            e.report_view(self.consensus,self.names,'2026-01-13','2026-01-12',self.raw)

    def test_no_future_report_even_if_present(self):
        z,meta,count=e.report_view(self.consensus,self.names,'2026-01-08','2026-01-09',self.raw)
        self.assertEqual(count,1)
        self.assertTrue(np.allclose(z,0))
        self.assertIsNone(meta['000002']['report_date'])

    def test_expired_report_is_neutral(self):
        z,meta,count=e.report_view(self.consensus,self.names,'2026-05-31','2026-06-01',self.raw)
        self.assertEqual(count,0)
        self.assertTrue(np.allclose(z,0))

    def test_must_use_raw_close(self):
        with self.assertRaises(ValueError):
            e.report_view(self.consensus,self.names,'2026-01-09','2026-01-12',self.raw.iloc[::-1])


class SignalCompatibilityTests(unittest.TestCase):
    def test_original_50_50_is_preserved_and_report_changes_weights(self):
        from scipy.stats import rankdata
        from dataclasses import dataclass
        from types import SimpleNamespace
        import sys

        names = ['000001','000002','000003','000004']
        d, buy = pd.Timestamp('2026-01-08'), pd.Timestamp('2026-01-09')
        dates = pd.to_datetime(['2026-01-07','2026-01-08','2026-01-09'])
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project/'data'/'kr'/'live_cache').mkdir(parents=True)
            raw = pd.DataFrame([[100,200,100,100]],index=[d],columns=names)
            raw.to_csv(project/'data'/'kr'/'live_cache'/'kr_yahoo_raw_close.csv')
            market = SimpleNamespace(project=project,names=names,
                                     close=pd.DataFrame(100.,index=dates,columns=names))
            O = np.array([[.01,.02,.03,.04],[.03,.04,.05,.06]],dtype=np.float32)
            F = np.array([[.04,.02,.03,.01],[.03,.04,.05,.02]],dtype=np.float32)
            M = np.zeros_like(F)
            seed = 0
            sig0 = 'sample-hash'
            ckhash = 'ckpt-hash'
            config = f'v1|{ckhash}|{sig0}|K=2|seed={seed}|seed_root=14262026|steps=30'
            sig = hashlib.sha256(config.encode()).hexdigest()
            cache = project/'results'/'kr_pair_cpu'/'scenarios'
            cache.mkdir(parents=True)
            np.savez_compressed(cache/f'20260108_s000_{sig[:16]}.npz',signature=np.asarray(sig),
                                original=O,full=F,macro=M)
            basew = np.array([.1,.2,.3,.4])
            fakekr=types.ModuleType('kr_pair_cpu')
            fakekr.SEED_ROOT=14262026
            fakekr.read_frame=lambda p, names: pd.read_csv(p,index_col=0,parse_dates=True).loc[:,names]
            fakekr.signal_weights=lambda *a, **kw: dict(
                date=str(d.date()), weights=dict(zip(names,basew)),
                feature_and_history_sha256=sig0,scenario_source='cache',feature_source='fake',
                checkpoint_sha256=ckhash,optimizer=dict(success=True))
            fakecore=types.ModuleType('kr_pair_core')
            fakecore.rank_z=lambda x: (rankdata(x,method='average')-(len(x)+1)/2)/np.sqrt((len(x)**2-1)/12)
            fakecore.historical_inputs=lambda *a,**kw:dict(zm=np.array([-1.,-.25,.25,1.]))
            fakecore.floor_psd=lambda c,eps:c
            class LW:
                def __init__(self,*a,**kw): pass
                def fit(self,x):
                    self.covariance_=np.cov(x.T)+np.eye(x.shape[1])*.001
                    return self
            fakecore.LedoitWolf=LW
            def repair(scores,*a):
                exp=np.exp(scores-np.max(scores))
                return exp/exp.sum(),dict(success=True)
            fakecore.rank_repair=repair
            fakecore.validate_w=lambda x: self.assertAlmostEqual(float(sum(x)),1,places=9)
            consensus=pd.DataFrame([
                {'stock_code':'000001','date':d,'tp_median':150,'company':'A'},
                {'stock_code':'000002','date':d,'tp_median':320,'company':'B'},
                {'stock_code':'000003','date':buy,'tp_median':999,'company':'C'}])
            consensus['date']=pd.to_datetime(consensus['date'])
            with patch.dict(sys.modules,{'kr_pair_cpu':fakekr,'kr_pair_core':fakecore}):
                base=e.signal(market,None,('','','',ckhash),d,buy,consensus,
                              pair_share=.5,report_share=0,K=2,seed=0)
                self.assertTrue(np.allclose(base['before_weights'],basew))
                self.assertTrue(np.allclose(base['after_weights'],basew))
                final=e.signal(market,None,('','','',ckhash),d,buy,consensus,
                               pair_share=.5,report_share=1,K=2,seed=0)
                self.assertEqual(final['report_coverage'],2)
                self.assertFalse(np.allclose(final['after_weights'],basew))
                c=next(x for x in final['comparison'] if x['stock_code']=='000003')
                self.assertIsNone(c['report_date'])
                self.assertEqual(final['buy_date'],'2026-01-09')


if __name__=='__main__':
    unittest.main()
