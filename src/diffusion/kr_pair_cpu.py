#!/usr/bin/env python3
"""CPU-only Korean STABLE MOM+PAIR 50:50 inference and next-open 20-sleeve backtesting.

Project defaults mirror the supplied KR_STABLE_{01,02} and PAPER_14_26_2 notebooks.
First run downloads raw 44-stock history + macro series automatically. Only checkpoint required.
"""
from __future__ import annotations
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''  # BEFORE torch is imported by core
for _k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_k, '1')
import argparse, datetime as dt, hashlib, json, logging, sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import torch

import kr_pair_core as core
from kr_pair_bootstrap import TRAINED_TICKERS, bootstrap_raw, yahoo_download_quiet

KST=ZoneInfo('Asia/Seoul')
CLOSE_READY=dt.time(18, 0)  # conservative publication buffer after KRX's regular close
MACRO_TICKERS={'market_index':'^KS11','dollar_index':'DX-Y.NYB','vix':'^VIX','gold':'GC=F'}
FRED_COL='term_spread_10y_3m'
N=44; NU=120; H=20; SEED_ROOT=14262026


def log(msg): print(msg, file=sys.stderr, flush=True)

def now_kst(): return dt.datetime.now(dt.timezone.utc).astimezone(KST)

def parse_asof(value: str, ready=CLOSE_READY, *, real_clock=True):
    # ISO date alone means 18:30 KST; explicit timestamp accepts timezone offset.
    if len(value)==10:
        parsed=dt.datetime.combine(dt.date.fromisoformat(value),dt.time(18,30),KST)
    else:
        parsed=dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed=parsed.replace(tzinfo=KST)
        parsed=parsed.astimezone(KST)
    if parsed.time()<ready:
        raise ValueError(f'Insufficient post-close publication buffer: {parsed.isoformat()} (need >= {ready} KST)')
    if real_clock and parsed>now_kst()+dt.timedelta(seconds=60):
        raise ValueError(f'Requested asof is in the future: {parsed.isoformat()}')
    return parsed


def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()


def sha_arrays(*arrays):
    h=hashlib.sha256()
    for arr in arrays:
        a=np.ascontiguousarray(arr)
        h.update(str(a.shape).encode());h.update(str(a.dtype).encode());h.update(a.tobytes())
    return h.hexdigest()


def atomic_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False,default=str),encoding='utf-8')
    os.replace(tmp,path)


def atomic_csv(path,df):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+f'.{os.getpid()}.tmp')
    df.to_csv(tmp,float_format='%.15g')
    os.replace(tmp,path)


def read_frame(path, names=None):
    p=Path(path)
    if not p.exists():raise FileNotFoundError(p)
    x=pd.read_csv(p,index_col=0,parse_dates=True)
    x.index=pd.DatetimeIndex(x.index).tz_localize(None).normalize()
    x=x.loc[~x.index.duplicated(keep='last')].sort_index()
    if names is not None:
        x.columns=[str(c).zfill(6) for c in x.columns]
        missing=set(names)-set(x.columns)
        if missing:raise ValueError(f'{p} missing tickers {sorted(missing)}')
        x=x.loc[:,names]
    return x.apply(pd.to_numeric,errors='coerce')


def clean_yahoo(df):
    if df is None or len(df)==0:raise RuntimeError('Yahoo empty data; prices not published yet')
    if isinstance(df.columns,pd.MultiIndex):
        # yfinance sometimes returns (field, ticker)
        df=df.droplevel(1,axis=1)
    df=df.copy();df.index=pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    return df.loc[~df.index.duplicated(keep='last')].sort_index()


def yahoo(symbol,start,end):
    try:import yfinance as yf
    except ImportError as e:raise RuntimeError('pip install yfinance for automatic refresh') from e
    d=yahoo_download_quiet(yf.download,symbol,start=str(pd.Timestamp(start).date()),
                  end=str((pd.Timestamp(end)+pd.Timedelta(days=1)).date()),
                  auto_adjust=False,progress=False,threads=False,timeout=30)
    return clean_yahoo(d)


def field(df,name):
    if name not in df:raise RuntimeError(f'Yahoo missing {name} column: {list(df.columns)}')
    return pd.to_numeric(df[name],errors='coerce')


@dataclass
class MarketData:
    project: Path
    names: list[str]
    close: pd.DataFrame
    macro: pd.DataFrame
    processed: Path
    metadata: pd.DataFrame
    xm: np.ndarray
    xs: np.ndarray
    open_adj: pd.DataFrame|None=None


def processed_path(project):
    # The original preprocessing output, not evaluation-only future-label metadata.
    return project/'data'/'kr'/'processed'


def load_processed(project):
    """Use verified frozen features when available; otherwise build from raw prices.

    Clean install needs NO NPY, NO metadata, and NO login to KRX.
    """
    proc=processed_path(project)
    required=('sample_metadata.csv','X_macro.npy','X_stock_condition.npy')
    present=[(proc/f).is_file() for f in required]
    if any(present) and not all(present):
        raise RuntimeError(f'Partially present processed bundle at {proc}: '
                           f'provide all {required} or remove partial files')
    names=sorted(TRAINED_TICKERS)
    if not any(present):
        # 0 rows means FeatureStore produces causal beta/z-score from downloaded raw.
        meta=pd.DataFrame({'date':pd.to_datetime([]),'ticker':pd.Series([],dtype=str)})
        return proc,meta,names,np.empty((0,10),np.float32),np.empty((0,13),np.float32)
    m=pd.read_csv(proc/'sample_metadata.csv',dtype={'ticker':str},parse_dates=['date'])
    m['date']=pd.to_datetime(m['date']).dt.normalize()
    m['ticker']=m.ticker.astype(str).str.zfill(6)
    if m.duplicated(['date','ticker']).any():raise ValueError('Duplicate processed sample pair')
    actual=sorted(m.ticker.unique().tolist())
    if actual!=names:raise ValueError('Processed universe differs from the frozen model 44: '
                                     f'extra={sorted(set(actual)-set(names))} missing={sorted(set(names)-set(actual))}')
    xm=np.load(proc/'X_macro.npy',mmap_mode='r');xs=np.load(proc/'X_stock_condition.npy',mmap_mode='r')
    if len(m)!=len(xm) or len(m)!=len(xs) or xm.shape[1]!=10 or xs.shape[1]!=13:
        raise ValueError(f'Processed feature dimensions do not match KR frozen model: {len(m)},{xm.shape},{xs.shape}')
    return proc,m,names,xm,xs


def _load_archives(project,names):
    raw=project/'data'/'kr'/'raw'; cache=project/'data'/'kr'/'live_cache'
    price_file=cache/'kr_close_live.csv' if (cache/'kr_close_live.csv').is_file() else raw/'stable_kospi200_44_adj_close.csv'
    macro_file=cache/'macro_raw_live.csv' if (cache/'macro_raw_live.csv').is_file() else raw/'macro_raw.csv'
    close=read_frame(price_file,names);macro=read_frame(macro_file)
    required=set([*MACRO_TICKERS,FRED_COL])
    if not required.issubset(macro.columns):raise ValueError(f'Missing macro: {required-set(macro.columns)}')
    if len(close)<253:raise ValueError('Need at least 253 historical prices')
    return close,macro


def refresh_market_data(project, names, close, macro, asof, *, need_open_start=None, force=False):
    """Incrementally obtain *confirmed* observations. Never modifies frozen raw files.

    For OHLC, store raw Open and Close. Adjusted entry Open is later constructed
    from asof-appropriate panel AdjClose*(raw Open/raw Close), preserving scale.
    """
    end=pd.Timestamp(asof).normalize()
    cache=project/'data'/'kr'/'live_cache';cache.mkdir(parents=True,exist_ok=True)
    need_extend=end not in close.index
    min_cached_open=None
    opens_file=cache/'kr_yahoo_raw_open.csv';raw_close_file=cache/'kr_yahoo_raw_close.csv'
    open_hist=read_frame(opens_file,names) if opens_file.is_file() else pd.DataFrame(columns=names,dtype=float)
    raw_closes=read_frame(raw_close_file,names) if raw_close_file.is_file() else pd.DataFrame(columns=names,dtype=float)
    if need_open_start is not None:
        need_open_start=pd.Timestamp(need_open_start).normalize()
        if len(open_hist):
            eligible=open_hist.loc[open_hist.index>=need_open_start]
            min_cached_open=eligible.index.min() if len(eligible) else None
        required=close.index[(close.index>=need_open_start)&(close.index<=end)]
        missing_open=(not set(required).issubset(open_hist.index)
                      or not set(required).issubset(raw_closes.index))
        if not missing_open and len(required):
            missing_open=(not np.isfinite(open_hist.loc[required,names].to_numpy(float)).all()
                          or not np.isfinite(raw_closes.loc[required,names].to_numpy(float)).all())
    else:missing_open=False
    if not (force or need_extend or missing_open):return close,macro,open_hist,raw_closes
    # Start 20 calendar days before last archived close when extending, for scaling.
    stock_start=(end-pd.Timedelta(days=28)) if need_extend else (need_open_start or end)
    if need_extend:
        stock_start=min(stock_start, close.index[-1]-pd.Timedelta(days=18))
    if missing_open:stock_start=min(stock_start, need_open_start)
    if force:stock_start=min(stock_start,end-pd.Timedelta(days=28))
    log(f'[refresh] Yahoo {stock_start.date()}..{end.date()} (44 stocks, macro), force={force}')
    new_open={};new_raw_close={};new_adj={}
    for n in names:
        d=yahoo(n+'.KS',stock_start,end)
        new_open[n]=field(d,'Open');new_raw_close[n]=field(d,'Close')
        new_adj[n]=field(d,'Adj Close') if 'Adj Close' in d else field(d,'Close')
        if end not in d.index or not np.isfinite(new_raw_close[n].loc[end]) or not np.isfinite(new_open[n].loc[end]):
            raise RuntimeError(f'Missing exact requested session {end.date()} for {n}; refuse stale/ffilled signal')
    new_open_df=pd.DataFrame(new_open);new_raw_df=pd.DataFrame(new_raw_close);new_adj_df=pd.DataFrame(new_adj)
    if (new_adj_df.loc[end]<=0).any():raise RuntimeError('Non-positive last adjusted close')
    if need_extend:
        old_last=close.index[-1]
        for n in names:
            overlap=close[n].dropna().index.intersection(new_adj_df[n].dropna().index)
            if len(overlap)<2:raise RuntimeError(f'No overlap to stitch {n}: require >=2 observations')
            anchor=overlap[-min(5,len(overlap)):]
            ratio=(close.loc[anchor,n]/new_adj_df.loc[anchor,n]).to_numpy(float)
            if np.ptp(ratio)/abs(float(np.median(ratio)))>0.005:
                raise RuntimeError(f'{n} adjusted-price history revised nonuniformly at bridge; manual review required')
            factor=float(np.median(ratio))
            add=new_adj_df[n].loc[new_adj_df.index>old_last]*factor
            close=close.reindex(close.index.union(add.index))
            close.loc[add.index,n]=add
        # Drop calendar rows with no data from ANY stock, but NEVER fill a missing current one.
        close=close.loc[~close[names].isna().all(axis=1)].sort_index()
        missing=close.loc[close.index>stock_start,names].isna().sum()
        if missing.any():
            raise RuntimeError('Partial KRX panel missing after refresh: '+str(missing[missing>0].to_dict()))
    if force and not need_extend and end==close.index[-1]:
        # A same-day previously cached last close might have been published provisionally.
        frozen_last=read_frame(project/'data'/'kr'/'raw'/'stable_kospi200_44_adj_close.csv',names).index[-1]
        if end>frozen_last:
            for n in names:
                overlap=close[n].dropna().index.intersection(new_adj_df[n].dropna().index)
                anchor=overlap[overlap<end][-5:]
                if len(anchor)<2:raise RuntimeError(f'Insufficient bridge rows to revalidate same-day {n}')
                ratio=(close.loc[anchor,n]/new_adj_df.loc[anchor,n]).to_numpy(float)
                if np.ptp(ratio)/abs(float(np.median(ratio)))>0.005:
                    raise RuntimeError(f'{n} price bridge changed; manual review required')
                close.loc[end,n]=new_adj_df.loc[end,n]*float(np.median(ratio))
    # Merge historical OHLC for requested interval; raw prices *never* interpreted as adjusted.
    open_hist=new_open_df.combine_first(open_hist).sort_index()
    raw_closes=new_raw_df.combine_first(raw_closes).sort_index()
    macro_last=macro.index[-1]
    frozen_macro=read_frame(project/'data'/'kr'/'raw'/'macro_raw.csv')
    frozen_macro_last=frozen_macro.index[-1]
    if need_extend or end not in macro.index or force:
        macro_start=min(stock_start,macro_last-pd.Timedelta(days=18))
        for key,symbol in MACRO_TICKERS.items():
            frame=yahoo(symbol,macro_start,end)
            val=field(frame,'Adj Close') if 'Adj Close' in frame else field(frame,'Close')
            macro=macro.reindex(macro.index.union(val.index))
            # Never rewrite the frozen period from a later Yahoo download.
            updated=val.index[(val.index>macro_last)|((val.index==end)&force&(end>frozen_macro_last))]
            macro.loc[updated,key]=val.loc[updated]
        try:
            from pandas_datareader import data as pdr
            f=pdr.DataReader('T10Y3M','fred',str(macro_start.date()),str(end.date()))['T10Y3M']
            macro=macro.reindex(macro.index.union(f.index))
            updated=f.index[(f.index>macro_last)|((f.index==end)&force&(end>frozen_macro_last))]
            macro.loc[updated,FRED_COL]=pd.to_numeric(f.loc[updated],errors='coerce')
        except Exception as e:
            # Safe only when past FRED is still available; feature uses *lagged* value.
            log(f'[refresh] Warning FRED unavailable: {e} (using older observed spread only)')
            last=macro[FRED_COL].dropna().index.max()
            if (end-last).days>10:raise RuntimeError('FRED past value too old (>10d); abort inference') from e
    if end not in macro.index or not np.isfinite(macro.loc[end,'market_index']):
        raise RuntimeError('KR market index has no official-equivalent close for requested date (holiday/stale provider)')
    # Market close/foreign updates never touch the frozen training CSVs.
    atomic_csv(cache/'kr_close_live.csv',close)
    atomic_csv(cache/'macro_raw_live.csv',macro)
    atomic_csv(opens_file,open_hist)
    atomic_csv(raw_close_file,raw_closes)
    return close,macro,open_hist,raw_closes


def load_market(project, asof, *, fetch=True, force=False, need_open_start=None):
    project=Path(project).expanduser().resolve()
    proc,meta,names,xm,xs=load_processed(project)
    raw=project/'data'/'kr'/'raw'
    cache=project/'data'/'kr'/'live_cache'
    initial=not ((raw/'stable_kospi200_44_adj_close.csv').is_file()
                 and (raw/'macro_raw.csv').is_file())
    if initial:
        if not fetch:
            raise FileNotFoundError('No raw data in this project. Omit --offline for automatic '
                                    '44-stock Yahoo/FRED first-run bootstrap.')
        # One-time full 2012..requested-date download; resume per ticker if interrupted.
        bootstrap_raw(project,asof,need_open_start=need_open_start)
    close,macro=_load_archives(project,names)
    opens_file=cache/'kr_yahoo_raw_open.csv';raw_close_file=cache/'kr_yahoo_raw_close.csv'
    if fetch and not initial:
        current_request=pd.Timestamp(asof).date()==now_kst().date()
        close,macro,op,rc=refresh_market_data(project,names,close,macro,asof,
                                             need_open_start=need_open_start,
                                             force=(force or current_request))
    else:
        op=read_frame(opens_file,names) if opens_file.is_file() else pd.DataFrame(columns=names,dtype=float)
        rc=read_frame(raw_close_file,names) if raw_close_file.is_file() else pd.DataFrame(columns=names,dtype=float)
    date=pd.Timestamp(asof).normalize()
    if date not in close.index:raise ValueError(f'{date.date()} missing in price panel; enable auto download or check KRX trading date')
    if not np.isfinite(close.loc[date,names].to_numpy(float)).all():
        raise ValueError('Latest 44 stocks do not all have confirmed close; refusing signal')
    if date not in macro.index or not np.isfinite(macro.loc[date,'market_index']):
        raise ValueError('KOSPI index not confirmed for session')
    if need_open_start is not None:
        required=close.loc[(close.index>=pd.Timestamp(need_open_start))&(close.index<=date)].index
        if not set(required).issubset(op.index) or not set(required).issubset(rc.index):
            raise ValueError('Missing Yahoo OHLC in backtest range; enable automatic downloads')
        raw_o=op.reindex(required).loc[:,names].to_numpy(float)
        raw_c=rc.reindex(required).loc[:,names].to_numpy(float)
        adjusted=close.reindex(required).loc[:,names].to_numpy(float)*(raw_o/raw_c)
        if not np.isfinite(adjusted).all() or (adjusted<=0).any() or (raw_c<=0).any():
            raise ValueError('Incomplete/invalid adjusted-open panel (do not approximate with close)')
        open_adj=pd.DataFrame(adjusted,index=required,columns=names)
    else:open_adj=None
    return MarketData(project,names,close,macro,proc,meta,xm,xs,open_adj)


def macro_feature_frame(close,macro):
    """Source STEP2/STEP3 exact macro normalization and Korean causal clock."""
    days=close.index
    m=macro.reindex(days).ffill()
    for c in ('dollar_index','vix','gold',FRED_COL):m[c]=m[c].shift(1)
    if not np.isfinite(m.loc[days[-1],'market_index']):
        raise ValueError('Unconfirmed Korean index level')
    change=pd.DataFrame(index=days)
    for c in ('market_index','dollar_index','vix','gold'):
        change[c+'_change']=np.log(m[c]/m[c].shift(1))
    change[FRED_COL+'_change']=m[FRED_COL].diff()
    def rolling_z(x):
        return (x-x.rolling(NU,min_periods=NU).mean())/(x.rolling(NU,min_periods=NU).std(ddof=0)+1e-8)
    a=rolling_z(m);a.columns=[c+'_raw_z' for c in m.columns]
    b=rolling_z(change);b.columns=[c+'_z' for c in change.columns]
    features=pd.concat([a,b],axis=1)
    if list(m.columns)!=['market_index','dollar_index','vix','gold',FRED_COL]:
        # Historical training build relies on macro_raw CSV column order (do not silently reorder).
        raise ValueError(f'Macro source columns/order differ from training: {list(m.columns)}')
    if features.shape[1]!=10:raise AssertionError(features.shape)
    return features


def kalman_beta_panel(y, macro_f, *, initial_state=None, start_index=0,
                      return_state=False):
    """Exact Kalman recursion, resumable at a saved daily beta/covariance state.

    Compute the initial observation variance R from the same first 120 valid
    returns as the original implementation, *once*. The covariance P and
    sample counts are persisted so extension never replays old trading dates.
    """
    dates=macro_f.index;n=y.shape[1];x=macro_f.to_numpy(float);r=y.reindex(dates).to_numpy(float)
    valid=np.isfinite(r)&np.isfinite(x).all(axis=1)[:,None]
    d=x.shape[1]
    if initial_state is None:
        if start_index:raise ValueError('Incremental Kalman start requires prior state')
        R=np.empty(n,float)
        for j in range(n):
            ix=np.flatnonzero(valid[:,j])
            if len(ix)<=NU:raise ValueError(f'Insufficient Kalman burn-in for {y.columns[j]}')
            R[j]=max(float(np.var(r[ix[:NU],j],ddof=1)),1e-8)
        beta=np.zeros((n,d),dtype=float)
        P=np.repeat(np.eye(d)[None,:,:],n,axis=0)
        seen=np.zeros(n,int)
    else:
        R=np.asarray(initial_state['R'],dtype=float).copy()
        beta=np.asarray(initial_state['beta'],dtype=float).copy()
        P=np.asarray(initial_state['P'],dtype=float).copy()
        seen=np.asarray(initial_state['seen'],dtype=int).copy()
        if (R.shape!=(n,) or beta.shape!=(n,d) or P.shape!=(n,d,d)
                or seen.shape!=(n,) or start_index<1 or start_index>len(dates)):
            raise ValueError('Invalid saved Kalman state or start index')
    Q=R[:,None,None]*1e-3*np.eye(d)[None,:,:]
    out=np.full((len(dates)-start_index,n,d),np.nan)
    eye=np.eye(d)[None,:,:]
    for t in range(start_index,len(dates)):
        m=x[t];good=valid[t];ix=np.flatnonzero(good)
        if not len(ix):continue
        seen[ix]+=1
        PP=P[ix]+Q[ix]
        v=np.einsum('nij,j->ni',PP,m)
        S=np.maximum(np.einsum('ni,i->n',v,m)+R[ix],1e-8)
        K=v/S[:,None]
        resid=r[t,ix]-beta[ix]@m
        beta[ix]=beta[ix]+K*resid[:,None]
        KH=K[:,:,None]*m[None,None,:]
        I_KH=eye-KH
        P[ix]=I_KH@PP@np.transpose(I_KH,(0,2,1))+(K[:,:,None]*K[:,None,:])*R[ix,None,None]
        exposed=ix[seen[ix]>NU]
        out[t-start_index,exposed,:]=beta[exposed]
    state={'R':R,'beta':beta,'P':P,'seen':seen}
    return (out,state) if return_state else out


def bootstrap_features(market, through, *, start_index=0, initial_state=None,
                       return_state=False):
    """Causal features: extend from a saved Kalman state without replaying dates."""
    through=pd.Timestamp(through).normalize()
    all_px=market.close.loc[:through,market.names].astype(float)
    if through not in all_px.index:raise ValueError(f'Not a trading date: {through}')
    # Only the new period and the minimal 120-day rolling warm-up are processed
    # when a saved Kalman beta/covariance state is supplied. Older features
    # remain untouched on disk; future source rows never enter earlier windows.
    left=max(0,start_index-(NU+3)) if initial_state is not None else 0
    px=all_px.iloc[left:]
    if px.isna().any().any() or (px<=0).any().any():
        raise ValueError('Cannot bootstrap from incomplete/nonpositive historical prices')
    macro=macro_feature_frame(px,market.macro.loc[:through])
    r=np.log(px/px.shift(1)).replace([np.inf,-np.inf],np.nan)
    def z(x):return (x-x.rolling(NU,min_periods=NU).mean())/(x.rolling(NU,min_periods=NU).std(ddof=0)+1e-8)
    close_z=z(px);ret_z=z(r)
    local_start=start_index-left
    beta,state=kalman_beta_panel(r,macro,initial_state=initial_state,
                                 start_index=local_start,return_state=True)
    dates=px.index[local_start:];n=len(market.names)
    basic=np.stack([close_z.to_numpy(float)[local_start:],r.to_numpy(float)[local_start:],
                    ret_z.to_numpy(float)[local_start:]],axis=-1)
    stock=np.concatenate([beta,basic],axis=-1).astype(np.float32)
    macros=np.broadcast_to(macro.to_numpy(np.float32)[local_start:,None,:],
                           (len(dates),n,10)).copy()
    return (dates,macros,stock,state) if return_state else (dates,macros,stock)


class FeatureStore:
    def __init__(self,market,*,persist_daily=True):
        self.market=market;self.map={}
        self.persist_daily=bool(persist_daily)
        groups=market.metadata.groupby('date').indices
        for d,ix in groups.items():
            subset=market.metadata.iloc[ix]
            if len(ix)==len(market.names) and sorted(subset.ticker.tolist())==market.names:
                order=np.argsort(subset.ticker.to_numpy())
                self.map[pd.Timestamp(d)]=np.asarray(ix,dtype=int)[order]
        self._boot=None
        self._boot_dates=None
        self._date_lookup=None

    def _ensure_boot(self,through):
        through=pd.Timestamp(through).normalize()
        if self._boot_dates is not None and self._boot_dates[-1]>=through:return
        px=self.market.close.loc[:through,self.market.names]
        if through not in px.index:raise ValueError(f'Not a trading date: {through}')
        macro_cols=['market_index','dollar_index','vix','gold',FRED_COL]
        raw_macro=self.market.macro.reindex(px.index)[macro_cols].ffill()
        if px.empty or raw_macro.empty:raise ValueError('Missing raw inputs for feature bootstrap')
        feat_dir=self.market.project/'data'/'kr'/'live_cache'/'features'/'panels'
        path=feat_dir/'kr_causal_features_incremental_v3.npz'
        date_index=px.index
        pxv=px.to_numpy(float)
        macv=raw_macro.to_numpy(float)
        loaded=None

        # A single growing panel survives restarts. Check the original rows
        # rather than the entire updated data hash: append-only source growth
        # must not invalidate already calculated Kalman features.
        if path.is_file():
            try:
                with np.load(path,allow_pickle=False) as z:
                    if str(z['schema'])!='KR_CAUSAL_FEATURES_INCREMENTAL_V3':
                        raise ValueError('Unsupported feature schema')
                    names=z['tickers'].tolist()
                    dates=pd.DatetimeIndex(z['dates'].astype('datetime64[ns]'))
                    xm=np.asarray(z['macro'],np.float32)
                    xs=np.asarray(z['stock'],np.float32)
                    cp=np.asarray(z['source_close'],float)
                    cm=np.asarray(z['source_macro'],float)
                    st={k:np.asarray(z['kalman_'+k]) for k in ('R','P','beta','seen')}
                if names!=self.market.names:raise ValueError('Ticker order changed')
                cnt=len(dates)
                if cnt>len(date_index):
                    # This happens when an earlier time window is requested.
                    # Compare its entire source prefix below and return only
                    # those requested rows without changing the disk cache.
                    pass
                common=min(cnt,len(date_index))
                if not dates[:common].equals(date_index[:common]):
                    raise ValueError('KRX calendar/history changed')
                if cp.shape!=(cnt,len(names)) or cm.shape!=(cnt,5):
                    raise ValueError('Cached source dimensions changed')
                if (not np.array_equal(cp[:common],pxv[:common],equal_nan=True)
                    or not np.array_equal(cm[:common],macv[:common],equal_nan=True)):
                    raise ValueError('Historical price/macro observations revised')
                if xm.shape!=(cnt,len(names),10) or xs.shape!=(cnt,len(names),13):
                    raise ValueError('Cached feature dimensions changed')
                loaded=(dates,xm,xs,st,cp,cm)
            except (OSError,ValueError,KeyError,EOFError) as e:
                log(f'[features-cache] Prior history invalid ({e}); full rebuild required')

        # Legacy V2 cache already contains complete, causally calculated
        # feature arrays. Reuse them and reconstruct *only* Kalman P/seen once
        # to migrate into an extendable V3 cache. No repetition on later runs.
        if loaded is None and not path.is_file() and feat_dir.is_dir():
            for legacy in sorted(feat_dir.glob('????????_*.npz'),reverse=True):
                try:
                    with np.load(legacy,allow_pickle=False) as z:
                        old_dates=pd.DatetimeIndex(z['dates'].astype('datetime64[ns]'))
                        if (not len(old_dates) or old_dates[0]!=date_index[0]
                            or len(old_dates)>len(date_index)
                            or not old_dates.equals(date_index[:len(old_dates)])):
                            continue
                        pfx_end=old_dates[-1]
                        old_px=self.market.close.loc[:pfx_end,self.market.names]
                        old_raw=self.market.macro.loc[:pfx_end,macro_cols]
                        h=hashlib.sha256(b'KR_CAUSAL_KALMAN_PANEL_V2;NU=120;MACRO_CLOCK=KR_LAG1')
                        h.update('|'.join(self.market.names).encode('utf-8'))
                        h.update(sha_arrays(old_px.index.asi8,old_px.to_numpy(float),
                                            old_raw.index.asi8,old_raw.to_numpy(float)).encode())
                        if str(z['signature'])!=h.hexdigest():continue
                        old_xm=np.asarray(z['macro'],np.float32)
                        old_xs=np.asarray(z['stock'],np.float32)
                    if old_xm.shape!=(len(old_dates),len(self.market.names),10):continue
                    if old_xs.shape!=(len(old_dates),len(self.market.names),13):continue
                    # Need a covariance state for exact continuation. V2 did
                    # not store it, so replay once while migrating.
                    log(f'[features-cache] Migrating V2 panel {legacy.name}; recovering Kalman state once')
                    _,check_xm,check_xs,st=bootstrap_features(self.market,pfx_end,return_state=True)
                    if not (np.allclose(old_xm[-1],check_xm[-1],rtol=5e-4,atol=1e-4,equal_nan=True)
                            and np.allclose(old_xs[-1],check_xs[-1],rtol=5e-4,atol=1e-4,equal_nan=True)):
                        raise ValueError('Legacy cache content differs from rebuilt state')
                    loaded=(old_dates,old_xm,old_xs,st,pxv[:len(old_dates)],macv[:len(old_dates)])
                    log(f'[features-cache] Recovered {len(old_dates)} cached sessions')
                    break
                except (OSError,ValueError,KeyError,EOFError) as e:
                    log(f'[features-cache] Could not migrate {legacy.name}: {e}')

        if loaded is None:
            log(f'[bootstrap] Initial causal feature build through {through.date()}')
            dates,xm,xs,state=bootstrap_features(self.market,through,return_state=True)
        else:
            dates,xm,xs,state,_,_=loaded
            if dates[-1]>=through:
                # Already covers this date: no Kalman updates or writes.
                stop=int(dates.get_loc(through))+1
                log(f'[features-cache] HIT through {through.date()} ({stop} existing sessions)')
                self._boot=(xm[:stop],xs[:stop]);self._boot_dates=dates[:stop]
                self._date_lookup={d:i for i,d in enumerate(self._boot_dates)}
                self._verify_overlap(through)
                return
            log(f'[features-cache] EXTEND {dates[-1].date()} -> {through.date()} '
                f'({len(date_index)-len(dates)} new sessions; old sessions reused)')
            more_dates,more_xm,more_xs,state=bootstrap_features(
                self.market,through,start_index=len(dates),initial_state=state,
                return_state=True)
            dates=dates.append(more_dates)
            xm=np.concatenate([xm,more_xm],axis=0)
            xs=np.concatenate([xs,more_xs],axis=0)

        # One atomic replacement per extension; the previous cache is left
        # untouched until the new file has been completely written.
        feat_dir.mkdir(parents=True,exist_ok=True)
        tmp=path.with_name(path.stem+f'.{os.getpid()}.tmp.npz')
        try:
            np.savez_compressed(tmp,schema=np.asarray('KR_CAUSAL_FEATURES_INCREMENTAL_V3'),
                                tickers=np.asarray(self.market.names),
                                dates=dates.to_numpy(dtype='datetime64[ns]'),
                                macro=xm,stock=xs,
                                source_close=pxv,source_macro=macv,
                                kalman_R=state['R'],kalman_P=state['P'],
                                kalman_beta=state['beta'],kalman_seen=state['seen'])
            os.replace(tmp,path)
        finally:
            if tmp.exists():tmp.unlink()
        log(f'[features-cache] SAVED {path.name} ({len(dates)} sessions)')
        self._boot=(xm,xs);self._boot_dates=dates
        self._date_lookup={d:i for i,d in enumerate(dates)}
        self._verify_overlap(through)

    def _verify_overlap(self,through):
        overlap=[d for d in self.map if d in self._date_lookup and d<=through]
        if overlap:
            candidate=sorted(overlap)[-min(3,len(overlap)):]
            for d in candidate:
                a,b=self.cached(d)
                i=self._date_lookup[d]
                xm,xs=self._boot
                if (not np.allclose(a,xm[i],rtol=5e-4,atol=1e-4)
                    or not np.allclose(b,xs[i],rtol=5e-4,atol=1e-4)):
                    raise RuntimeError(f'Bootstrap does NOT reproduce frozen features at {d.date()}! '
                                       'Check source revisions and macro clock.')
            log(f'[bootstrap] Verified overlap vs frozen features: {len(candidate)} days')

    def cached(self,date):
        ids=self.map[date]
        return np.asarray(self.market.xm[ids],dtype=np.float32),np.asarray(self.market.xs[ids],dtype=np.float32)

    def get(self,date):
        date=pd.Timestamp(date).normalize()
        if date in self.map:return (*self.cached(date),'preprocessed')
        self._ensure_boot(date)
        if date not in self._date_lookup:raise ValueError(f'No price feature date {date}')
        i=self._date_lookup[date]
        xm,xs=self._boot[0][i],self._boot[1][i]
        if not np.isfinite(xm).all() or not np.isfinite(xs).all():
            raise RuntimeError(f'Non-finite bootstrapped features on {date.date()} (check macro/Kalman burn-in)')
        # Keep legacy one-date feature snapshots for the standalone inference
        # command only. Backtests already persist/reuse one full-panel cache and
        # must not create hundreds of redundant small .npz files.
        if self.persist_daily:
            feat_dir=self.market.project/'data'/'kr'/'live_cache'/'features'
            feat_dir.mkdir(parents=True,exist_ok=True)
            digest=sha_arrays(self.market.close.loc[:date,self.market.names].to_numpy(float),
                              self.market.macro.loc[:date].to_numpy(float))[:16]
            dest=feat_dir/f'{date:%Y%m%d}_{digest}.npz'
            if not dest.exists():
                tmp=dest.with_name(dest.stem+f'.{os.getpid()}.tmp.npz')
                np.savez_compressed(tmp,macro=xm,stock=xs,tickers=np.asarray(self.market.names))
                os.replace(tmp,dest)
        return xm,xs,'bootstrapped'


def load_model(project, threads=4):
    torch.set_num_threads(int(threads))
    torch.set_num_interop_threads(1) if not getattr(load_model,'_threads_set',False) else None
    load_model._threads_set=True
    ckpt=Path(project)/'checkpoints'/'kr'/'stable_best.pt'
    if not ckpt.is_file():raise FileNotFoundError(f'Trained checkpoint required: {ckpt}')
    try:ck=torch.load(ckpt,map_location='cpu',weights_only=True)
    except Exception as e:raise RuntimeError(f'Cannot load safe frozen checkpoint {ckpt}: {e}') from e
    if (int(ck['macro_dim']),int(ck['stock_cond_dim']),int(ck['horizon']))!=(10,13,H):
        raise ValueError('Checkpoint dimensions incompatible with KR features')
    core.MACRO_DIM=10;core.STOCK_COND_DIM=13
    model=core.build_stable_model(dict(ck['model_config']))
    model.load_state_dict(ck['model_state_dict'],strict=True)
    model.cpu().eval()
    for p in model.parameters():p.requires_grad_(False)
    T=int(ck.get('n_diffusion',200))
    if T!=200:raise ValueError(f'Expected frozen 200-step diffusion; received {T}')
    abar=torch.cumprod(1-torch.linspace(1e-4,0.02,T),dim=0)
    times=np.linspace(0,T-1,30,dtype=np.int64)[::-1].copy()
    return model,abar,times,sha256_file(ckpt)


def signal_weights(market,features,model_data,date,*,seed=0,K=128,batch=128,blend='smooth050',
                   reuse=True,require_repair=False):
    """Inferred weights given date-t close only; fixed K and seed give reproducible CPU draws."""
    if K<1 or batch<1:raise ValueError('K and batch must be positive')
    date=pd.Timestamp(date).normalize()
    if date not in market.close.index:raise ValueError(f'{date.date()} is not a KRX session')
    px=market.close.loc[:date,market.names]
    if len(px)<253:raise ValueError(f'Need >=253 daily price rows up to {date.date()}')
    macro,stock,source=features.get(date)
    model,abar,times,ckhash=model_data
    historical=core.historical_inputs(market.close.loc[:date],str(date.date()),market.names)
    signature=sha_arrays(macro,stock,px.tail(253).to_numpy(float))
    settings=f'v1|{ckhash}|{signature}|K={K}|seed={seed}|seed_root={SEED_ROOT}|steps=30'
    sig=hashlib.sha256(settings.encode()).hexdigest()
    cache=market.project/'results'/'kr_pair_cpu'/'scenarios'/f'{date:%Y%m%d}_s{seed:03d}_{sig[:16]}.npz'
    if cache.is_file() and reuse:
        with np.load(cache,allow_pickle=False) as z:
            if str(z['signature'])!=sig:raise RuntimeError('Cache signature mismatch')
            O,F,M=(np.asarray(z[k],np.float32) for k in ('original','full','macro'))
        scenario_source='cache'
    else:
        seed0=core.stable_seed(SEED_ROOT,'KR',str(date.date()),seed,'O_F_M_SHARED_XT_V1')
        noise=np.random.default_rng(seed0).standard_normal((K,len(market.names),H)).astype('float32')
        O,F,M=core.triple_ddim(model,abar,times,noise,macro,stock,torch.device('cpu'),batch_size=batch)
        cache.parent.mkdir(parents=True,exist_ok=True)
        tmp=cache.with_name(cache.stem+f'.{os.getpid()}.tmp.npz')
        np.savez_compressed(tmp,signature=np.asarray(sig),original=O,full=F,macro=M)
        os.replace(tmp,cache)
        scenario_source='computed_cpu'
    if O.shape!=(K,N) or F.shape!=(K,N) or M.shape!=(K,N):raise ValueError('Scenario shape mismatch')
    cov=core.floor_psd(core.LedoitWolf(assume_centered=False).fit(O).covariance_,1e-5)
    zm=historical['zm'];zp=core.rank_z((F-M).mean(axis=0))
    mixed=.5*zm+.5*zp
    if blend=='rerank050':mixed=core.rank_z(mixed)  # PAPER C, distinct from fixed smooth policy
    elif blend!='smooth050':raise ValueError('blend = smooth050 or rerank050')
    cfg={'beta':.5,'target_ratio':.9,'slack_penalty':1.,'optimizer_max_iter':220}
    weights,diag=core.rank_repair(mixed,cov,historical,cfg)
    if require_repair and not diag['success']:
        raise RuntimeError(f'CVaR optimizer did not converge: {diag}')
    weights=np.asarray(weights,float)
    core.validate_w(weights)
    result=dict(date=date.strftime('%Y-%m-%d'),exchange='KRX',decision_price='adjusted_close',
                execution='next_eligible_trading_session_open',universe='KRX_KOSPI200_20250331_CAP44_frozen',
                policy='MOM+PAIR',blend_mode=blend,momentum_weight=0.5,pair_weight=0.5,
                model='frozen_STABLE_KR_20D',scenario_K=K,inference_seed=int(seed),
                cpu_only=True,feature_source=source,scenario_source=scenario_source,
                checkpoint_sha256=ckhash,feature_and_history_sha256=signature,
                optimizer=dict(success=bool(diag['success']),fallback=bool(diag['fallback']),
                               reason=str(diag['why']),risk_ratio=float(diag['risk_ratio']),
                               slack=float(diag['slack']),iterations=int(diag['iterations'])),
                weights={n:float(w) for n,w in zip(market.names,weights)},
                weights_pct={n:round(float(w)*100,6) for n,w in zip(market.names,weights)})
    return result


def infer(project,asof,*,fetch=True,force=False,K=128,seed=0,batch=128,threads=4,
          blend='smooth050',require_repair=False,write=True):
    timestamp=parse_asof(asof)
    day=pd.Timestamp(timestamp.date())
    ckpt=Path(project)/'checkpoints'/'kr'/'stable_best.pt'
    if not ckpt.is_file():raise FileNotFoundError(f'Only pre-required model checkpoint: {ckpt}')
    market=load_market(project,day,fetch=fetch,force=force)
    model=load_model(project,threads=threads)
    result=signal_weights(market,FeatureStore(market),model,day,seed=seed,K=K,
                          batch=batch,blend=blend,require_repair=require_repair)
    result['requested_at_kst']=timestamp.isoformat()
    if write:
        path=Path(project)/'results'/'kr_pair_cpu'/'signals'/f'{day:%Y%m%d}_s{seed:03d}.json'
        atomic_json(path,result)
        log(f'[saved] {path}')
    return result


def rebalance_open(shares, cash, target, price, fee):
    """Trade exactly at OPEN; fees assessed on absolute traded value on both sides.

    Solve final asset value x = wealth_before - fee*sum(|target*x - old_position_value|).
    This models self-financing fractional-share trades and avoids fee undercharging.
    """
    old=np.asarray(shares,float)*np.asarray(price,float)
    wealth=float(old.sum()+cash)
    w=np.asarray(target,float)
    if not np.isfinite(wealth) or wealth<=0 or (price<=0).any():raise ValueError('Invalid NAV/open execution')
    core.validate_w(w)
    lo,hi=0.,wealth
    for _ in range(60):
        mid=(lo+hi)/2
        err=mid+fee*np.abs(mid*w-old).sum()-wealth
        if err>0:hi=mid
        else:lo=mid
    x=(lo+hi)/2
    turnover=float(np.abs(x*w-old).sum())
    fees=float(fee*turnover)
    newshares=(x*w)/price
    assert abs((newshares*price).sum()+fees-wealth)<1e-8, 'Non-self-financing rebalance'
    return newshares,0.,turnover,fees


def simulate_open_sleeves(prices_close,prices_open,weights_by_decision,*,sleeves=20,fee_bps_side=20.0):
    """Close decision at t -> OPEN trade t+1 -> same sleeve reused after 20 sessions.

    NAV is close-marked after trades; each sleeve starts with 1/sleeves cash. No
    fractional/overnight lookahead, future price input, or daily cash injection.
    """
    if sleeves<1:raise ValueError('sleeves must be >=1')
    if fee_bps_side<0 or fee_bps_side>=10000:raise ValueError('Invalid fee')
    close=prices_close.copy();opens=prices_open.copy()
    if not close.index.equals(opens.index):raise ValueError('Open/close calendars differ')
    if not close.columns.equals(opens.columns):raise ValueError('Open/close ticker order differs')
    if close.empty or not np.isfinite(close.to_numpy(float)).all() or not np.isfinite(opens.to_numpy(float)).all():
        raise ValueError('Invalid OHLC panel')
    if (close<=0).any().any() or (opens<=0).any().any():raise ValueError('Nonpositive OHLC panel')
    n=close.shape[1];dates=close.index;next_trade={};not_executed=[]
    for j,(decision,weights) in enumerate(sorted(weights_by_decision.items())):
        d=pd.Timestamp(decision).normalize()
        if d not in dates:raise ValueError(f'Signal date not available {d}')
        k=dates.get_loc(d)
        if k+1==len(dates):
            not_executed.append(str(d.date()));continue
        b=dates[k+1]
        if b in next_trade:raise ValueError('Two signals scheduled for the same next open')
        w=np.asarray(weights,float)
        if w.shape!=(n,):raise ValueError('Weight/price dimensions differ')
        core.validate_w(w)
        next_trade[b]=(j%sleeves,d,w)
    positions=np.zeros((sleeves,n),dtype=float)
    cash=np.full(sleeves,1.0/sleeves,dtype=float)
    past=1.0;records=[];trades=[];fee=fee_bps_side/10000.
    for day in dates:
        today_fee=0.;today_turn=0.
        close_today=close.loc[day].to_numpy(float)
        if day in next_trade:
            slot,decision,w=next_trade[day]
            p=opens.loc[day].to_numpy(float)
            before=float(cash[slot]+positions[slot]@p)
            pos,cash_after,turn,commission=rebalance_open(positions[slot],cash[slot],w,p,fee)
            positions[slot]=pos;cash[slot]=cash_after
            today_fee+=commission;today_turn+=turn
            trades.append(dict(decision_date=str(decision.date()),entry_date=str(day.date()),
                               sleeve=slot,account_before_open=before,fee=commission,
                               traded_notional=turn,active_names=int((w>1e-10).sum())))
        close_nav=float(cash.sum()+(positions*close_today[None,:]).sum())
        if not np.isfinite(close_nav) or close_nav<=0:raise RuntimeError('Invalid NAV')
        daily=close_nav/past-1
        records.append(dict(date=day,nav=close_nav,daily_return=daily,
                            fee=today_fee,turnover=today_turn,
                            active_sleeves=int((positions.sum(axis=1)>1e-10).sum()),
                            idle_cash=float(cash.sum())))
        past=close_nav
    return pd.DataFrame(records).set_index('date'),pd.DataFrame(trades),not_executed


def performance(nav):
    r=nav['daily_return'].to_numpy(float)
    if len(r)<2:raise ValueError('Too few NAV records')
    r=r[1:] # first mark is initial baseline, exclude it from annualization
    vol=float(np.std(r,ddof=1))*np.sqrt(252)
    ann_return=float((nav.nav.iloc[-1]/nav.nav.iloc[0])**(252/max(1,len(r)))-1)
    sharpe=float(np.mean(r)*252/vol) if vol>1e-12 else None
    underwater=nav.nav/nav.nav.cummax()-1
    return dict(total_return=float(nav.nav.iloc[-1]/nav.nav.iloc[0]-1),annualized_return=ann_return,
                annual_volatility=vol,sharpe=sharpe,max_drawdown=float(underwater.min()),
                trades=None,total_fees=float(nav.fee.sum()),total_turnover=float(nav.turnover.sum()),
                trading_days=len(r))


def backtest(project,start,end,*,fetch=True,force=False,K=128,seed=0,batch=128,threads=4,
             blend='smooth050',sleeves=20,fee_bps_side=20.,max_signals=None,require_repair=False):
    """Historical close-date signals, next-session OPEN fill, independent 20 sleeves."""
    start=pd.Timestamp(start).normalize();end=pd.Timestamp(end).normalize()
    if start>=end:raise ValueError('start must precede end')
    if end.date()>now_kst().date():raise ValueError('Backtest end is in the future')
    if end.date()==now_kst().date() and now_kst().time()<CLOSE_READY:
        raise ValueError('Today not yet post-close ready')
    ckpt=Path(project)/'checkpoints'/'kr'/'stable_best.pt'
    if not ckpt.is_file():raise FileNotFoundError(f'Only pre-required model checkpoint: {ckpt}')
    log(f'[backtest] loading KR close through {end.date()}, Yahoo OPEN history starting {start.date()}')
    market=load_market(project,end,fetch=fetch,force=force,need_open_start=start)
    if market.open_adj is None:raise ValueError('Backtest requires verified open prices')
    # Always compute on the dates of the universe price panel, not calendar days.
    days=market.close.index[(market.close.index>=start)&(market.close.index<=end)]
    if len(days)<2:raise ValueError('At least two price sessions required')
    signals=list(days[:-1])  # current end's next OPEN is unknown, never assume tomorrow.
    if max_signals is not None:signals=signals[:int(max_signals)]
    features=FeatureStore(market,persist_daily=False)
    # Build missing-date features ONCE for the whole backtest. All transformations
    # (Kalman recursion/rolling normalization) are causal even when computed in bulk.
    if signals and any(d not in features.map for d in signals):
        features._ensure_boot(signals[-1])
    model=load_model(project,threads=threads)
    weightmap={};signal_rows=[]
    for i,date in enumerate(signals):
        result=signal_weights(market,features,model,date,seed=seed,K=K,batch=batch,
                              blend=blend,require_repair=require_repair)
        weightmap[date]=np.array([result['weights'][n] for n in market.names],float)
        signal_rows.append(dict(date=str(date.date()),feature_source=result['feature_source'],
                                scenario_source=result['scenario_source'],
                                optimizer_success=result['optimizer']['success'],
                                optimizer_fallback=result['optimizer']['fallback'],
                                **result['weights']))
        if (i+1)%5==0 or i+1==len(signals):
            log(f'[backtest] {i+1}/{len(signals)} signals, last={date.date()}')
    # Backtest starts at the requested first KR trading session, NOT at the
    # beginning of the 2012+ feature/bootstrap price history. Otherwise
    # pre-start idle NAV biases annualized metrics and chart dates.
    price_dates=days
    if max_signals is not None:
        # Optional debug-only shortcut: mark through the last signal's next OPEN.
        price_dates=days[:len(signals)+1]
    nav,trades,not_executed=simulate_open_sleeves(
        market.close.loc[price_dates,market.names],market.open_adj.loc[price_dates,market.names],
        weightmap,sleeves=sleeves,fee_bps_side=fee_bps_side)
    # One target portfolio per KRX trading day; NEXT trading session's OPEN
    # executes exactly one sleeve. A sleeve is reused after 20 sessions.
    expected_opens=[str(d.date()) for d in price_dates[1:len(signals)+1]]
    expected_sleeves=np.arange(len(signals))%sleeves
    if not_executed or len(trades)!=len(signals):
        raise RuntimeError('Missing daily sleeve execution(s)')
    if len(trades) and (trades['entry_date'].tolist()!=expected_opens or
                        not np.array_equal(trades['sleeve'].to_numpy(dtype=int),expected_sleeves)):
        raise RuntimeError('Daily one-new-sleeve schedule is violated')
    metrics=performance(nav)
    metrics.update(trades=int(len(trades)),decisions=int(len(signals)),
                   first_date=str(days[0].date()),last_signal_date=str(signals[-1].date()) if signals else None,
                   last_mark_date=str(nav.index[-1].date()),unexecuted_signals=not_executed,
                   sleeves=sleeves,per_side_fee_bps=float(fee_bps_side),
                   fill_basis='next_KRX_session_OPEN',mark_basis='same_day_adjusted_CLOSE',
                   seed=seed,K=K,blend_mode=blend,cpu_only=True,
                   source_universe='frozen_2025-03-31_CAP44_survivorship_bias')
    path=Path(project)/'results'/'kr_pair_cpu'/'backtests'/f'{start:%Y%m%d}_{end:%Y%m%d}_s{seed:03d}_{blend}'
    path.mkdir(parents=True,exist_ok=True)
    atomic_csv(path/'nav.csv',nav)
    atomic_csv(path/'trades.csv',trades.set_index('entry_date') if len(trades) else trades)
    atomic_csv(path/'daily_weights.csv',pd.DataFrame(signal_rows).set_index('date'))
    atomic_json(path/'metrics.json',metrics)
    log(f'[backtest] saved {path}')
    return nav,trades,metrics,path


def main(argv=None):
    parser=argparse.ArgumentParser(description='CPU-only KRX MOM+PAIR 50/50: close inference and next-OPEN 20-sleeve backtest')
    parser.add_argument('--project',type=Path,default=Path(os.environ.get('STABLE_PROJECT',str(Path.cwd()))))
    parser.add_argument('--offline',action='store_true',help='No Yahoo/FRED downloads; first clean run requires downloads')
    parser.add_argument('--fetch',action='store_true',help='Refresh source data even if requested date is archived')
    parser.add_argument('--K',type=int,default=128)
    parser.add_argument('--seed',type=int,default=0)
    parser.add_argument('--batch',type=int,default=128)
    parser.add_argument('--threads',type=int,default=4)
    parser.add_argument('--blend',choices=['smooth050','rerank050'],default='smooth050')
    parser.add_argument('--require-repair',action='store_true',help='Abort rather than use optimizer fallback')
    sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('infer',help='Emit JSON portfolio weights')
    p.add_argument('--asof',required=True,help='YYYY-MM-DD or ISO timestamp with timezone')
    p=sub.add_parser('backtest',help='Simulate next-open fills with fixed 20-sleeve stagger')
    p.add_argument('--start',required=True)
    p.add_argument('--end',required=True)
    p.add_argument('--sleeves',type=int,default=20)
    p.add_argument('--fee-bps-side',type=float,default=20.)
    p.add_argument('--max-signals',type=int,default=None)
    args=parser.parse_args(argv)
    opts=dict(fetch=not args.offline,force=args.fetch,K=args.K,seed=args.seed,batch=args.batch,
              threads=args.threads,blend=args.blend,require_repair=args.require_repair)
    if args.mode=='infer':
        result=infer(args.project,args.asof,**opts)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    else:
        nav,trades,metrics,path=backtest(args.project,args.start,args.end,
                           **opts,sleeves=args.sleeves,fee_bps_side=args.fee_bps_side,
                           max_signals=args.max_signals)
        print(json.dumps(metrics,ensure_ascii=False,indent=2,allow_nan=False))
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        log(f'ERROR [{type(exc).__name__}]: {exc}')
        sys.exit(1)
