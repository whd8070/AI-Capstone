"""Offline sanity tests; do not need checkpoint, internet, or real price data."""
import datetime as dt
import numpy as np
import pandas as pd
import torch
from zoneinfo import ZoneInfo
from types import SimpleNamespace
import kr_pair_cpu as c
import kr_pair_core as core


def test_time_gate():
    c.parse_asof('2024-10-01T18:31:00+09:00')
    try:c.parse_asof('2024-10-01T15:31:00+09:00')
    except ValueError:pass
    else:raise AssertionError('No pre-close restriction')


def test_self_financing():
    p=np.array([10.,20.]);s=np.array([.05,.01]);w=np.array([.7,.3])
    x,cash,traded,fees=c.rebalance_open(s,0.,w,p,0.002)
    np.testing.assert_allclose((x*p).sum()+fees,(s*p).sum(),atol=1e-9)
    np.testing.assert_allclose((x*p)/(x*p).sum(),w,atol=1e-12)


def test_20_sleeves_open():
    idx=pd.bdate_range('2024-01-01',periods=25)
    a=np.full((25,2),100.)
    close=pd.DataFrame(a,index=idx,columns=['A','B'])
    op=close.copy();op.iloc[1,0]=150. # Asset A enters at next OPEN, subsequent close drops 1/3.
    W={idx[i]:np.array([1.,0.]) for i in range(24)}
    nav,tx,miss=c.simulate_open_sleeves(close,op,W,sleeves=20,fee_bps_side=0)
    assert len(tx)==24 and len(miss)==0
    assert tx.iloc[0].sleeve==0 and tx.iloc[20].sleeve==0
    np.testing.assert_allclose(nav.nav.iloc[0],1.)
    np.testing.assert_allclose(nav.nav.iloc[1],1-1/20/3)
    # With zero commissions and flat prices, post-entry NAV remains flat except first open gap.
    assert nav.nav.iloc[-1]<1.


def test_no_future_bootstrap():
    idx=pd.bdate_range('2022-01-03',periods=260)
    names=[str(i).zfill(6) for i in range(1,45)]
    rng=np.random.default_rng(11)
    returns=rng.normal(0,0.005,(len(idx),44));px=100*np.exp(np.cumsum(returns,axis=0))
    close=pd.DataFrame(px,index=idx,columns=names)
    macro=pd.DataFrame({'market_index':100+np.arange(len(idx))*.05,
                        'dollar_index':98+np.arange(len(idx))*.025,
                        'vix':23+np.sin(np.arange(len(idx))/12),
                        'gold':1500+np.arange(len(idx))*.1,
                        'term_spread_10y_3m':np.cos(np.arange(len(idx))/40)},index=idx)
    m=SimpleNamespace(close=close,names=names,macro=macro)
    date=idx[255]
    d1,ma1,st1=c.bootstrap_features(m,date)
    assert ma1.shape==(256,44,10) and st1.shape==(256,44,13)
    assert np.isfinite(st1[-1]).all()
    # Perturb all FUTURE market data; pre-cutoff features must remain exactly unchanged.
    close.iloc[-3:]*=1.77
    macro.iloc[-3:]*=2
    d2,ma2,st2=c.bootstrap_features(m,date)
    np.testing.assert_array_equal(ma1,ma2)
    np.testing.assert_array_equal(st1,st2)


def test_cpu_model_ddim():
    assert not torch.cuda.is_available() or core.os.environ.get('CUDA_VISIBLE_DEVICES')==''
    core.MACRO_DIM=10;core.STOCK_COND_DIM=13
    model=core.build_stable_model(dict(d_model=16,z_max=2.,base_channels=32,time_dim=32,
                 gate_hidden_dim=32,stage_blocks=1,mid_blocks=2,group_norm_groups=4)).cpu().eval()
    abar=torch.cumprod(1-torch.linspace(.0001,.02,200),dim=0)
    z=np.zeros((1,2,20),dtype='float32')
    mc=np.zeros((2,10),dtype='float32');sc=np.zeros((2,13),dtype='float32')
    out=core.triple_ddim(model,abar,np.array([199,100,0]),z,mc,sc,torch.device('cpu'),batch_size=2)
    assert len(out)==3 and all(a.shape==(1,2) for a in out)
    assert all(np.isfinite(a).all() for a in out)




def test_empty_project_bootstrap_no_manual_csv():
    """Full clean-start smoke using stub providers: no KRX login/raw CSV/NPY needed."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    import kr_pair_bootstrap as boot
    idx=pd.bdate_range('2012-06-01','2024-10-01')
    time=np.arange(len(idx),dtype=float)
    def mock_yahoo(symbol,start,end,path,fields,**kwargs):
        if symbol=='^KS11':
            price=2000*np.exp(.00018*time+.007*np.sin(time/32))
        elif symbol.endswith('.KS'):
            k=int(symbol.split('.')[0]);price=100*np.exp(.0002*time+.003*np.sin(time/12 +k%15))
        else:
            price=100*np.exp(.00005*time+.01*np.sin(time/26+len(symbol)))
        d=pd.DataFrame({'Adj Close':price,'Open':price*.998,'Close':price},index=idx)
        return d.loc[:,list(fields)]
    def fake_fred(start,end):
        return pd.DataFrame({'term_spread_10y_3m':1+.2*np.sin(time/60)},index=idx)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        with patch.object(boot,'_cached_yahoo',side_effect=mock_yahoo),patch.object(boot,'_fred_download',side_effect=fake_fred):
            market=c.load_market(root,pd.Timestamp('2024-10-01'),fetch=True,need_open_start='2024-09-02')
        assert len(market.names)==44 and list(market.names)==sorted(boot.TRAINED_TICKERS)
        assert market.open_adj is not None
        assert (root/'data/kr/raw/stable_kospi200_44_adj_close.csv').is_file()
        assert (root/'data/kr/raw/macro_raw.csv').is_file()
        assert (root/'data/kr/cache_prices').is_dir()
        assert (root/'data/kr/metadata/stable_kospi200_44.csv').is_file()
        assert not (root/'data/kr/processed/X_macro.npy').exists()
        features=c.FeatureStore(market)
        date=pd.Timestamp('2024-10-01')
        xm,xs,source=features.get(date)
        assert source=='bootstrapped'
        assert xm.shape==(44,10) and xs.shape==(44,13)
        assert np.isfinite(xm).all() and np.isfinite(xs).all()
        assert list((root/'data/kr/live_cache/features').glob('20241001_*.npz'))
        # A second invocation must work offline using downloaded archives, without fake providers.
        second=c.load_market(root,date,fetch=False,need_open_start='2024-09-02')
        np.testing.assert_allclose(second.close.loc[date],market.close.loc[date])

if __name__=='__main__':
    torch.set_num_threads(2)
    for name,fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn();print('PASS',name,flush=True)
    print('ALL PASS',flush=True)
