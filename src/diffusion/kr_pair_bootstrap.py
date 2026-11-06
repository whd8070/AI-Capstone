"""First-run download of the *fixed* KR STABLE training universe and raw features.

Universe is transcribed from the KR_STABLE_01_PREPROCESS... notebook's STEP3
executed output (44 numbered stock lines). No KRX login or local CSV prerequisite.
The data source is Yahoo Finance (via yfinance) and FRED T10Y3M. Failure is
explicit; there are no synthetic price substitutions or silently changed names.
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import sys
import time
import warnings
import numpy as np
import pandas as pd

# KR_STABLE_01_PREPROCESS_KRX_20250331(3).ipynb, STEP3 cell output, 01/44..44/44
TRAINED_TICKERS = (
    '005930','000660','005380','000270','068270','105560','035420','012450',
    '012330','055550','138040','005490','042660','035720','051910','011200',
    '086790','096770','000810','032830','010130','034020','009540','015760',
    '006400','066570','030200','033780','017670','010140','024110','003550',
    '009150','034730','003670','000100','047050','086280','003490','047810',
    '042700','003230','010950','005830'
)
START='2012-06-01'
MACROS={'market_index':'^KS11','dollar_index':'DX-Y.NYB','vix':'^VIX','gold':'GC=F'}
FRED='term_spread_10y_3m'


def info(msg):
    print('[initial-bootstrap] '+msg, file=sys.stderr,flush=True)


def _write_csv(path, df):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    df.to_csv(tmp)
    tmp.replace(path)


def _normalize(frame):
    frame=frame.copy()
    frame.index=pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    return frame.loc[~frame.index.duplicated(keep='last')].sort_index()


def yahoo_download_quiet(func, *args, **kwargs):
    """Silence only yfinance's pandas-3 inplace deprecation chatter.

    Other warnings, HTTP errors and download exceptions remain visible.
    Download is run with threads=False, so the local warning filter is scoped.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"^The inplace keyword in DataFrame\.(?:set_index|sort_index|rename) is deprecated",
            category=Warning,
            module=r"^yfinance(?:\..*)?$",
        )
        return func(*args, **kwargs)


def _pull_yahoo(symbol,start,end,tries=3):
    import yfinance as yf
    last=None
    for attempt in range(tries):
        try:
            x=yahoo_download_quiet(yf.download, symbol, start=start,
                          end=str((pd.Timestamp(end)+pd.Timedelta(days=1)).date()),
                          auto_adjust=False, progress=False, threads=False, timeout=30)
            if x.empty:raise ValueError(f'empty Yahoo response: {symbol}')
            if isinstance(x.columns,pd.MultiIndex):
                x=x.droplevel(1,axis=1)
            return _normalize(x)
        except Exception as e:
            last=e
            if attempt<tries-1:time.sleep(min(2*(attempt+1),4))
    raise RuntimeError(f'Yahoo download failed for {symbol}: {last}') from last


def _cached_yahoo(symbol,start,end,path,fields,*,retry=True):
    path=Path(path);end=pd.Timestamp(end).normalize()
    if path.is_file():
        try:
            c=_normalize(pd.read_csv(path,index_col=0,parse_dates=True))
            if (set(fields).issubset(c.columns) and c.index.min()<=pd.Timestamp(start)+pd.Timedelta(days=15)
                    and c.index.max()>=end and end in c.index):
                return c
        except Exception:pass
    data=_pull_yahoo(symbol,start,end,3 if retry else 1)
    needed=[f for f in fields if f not in data.columns]
    if needed:raise RuntimeError(f'{symbol} missing Yahoo columns: {needed}')
    data=data.loc[:,fields]
    _write_csv(path,data)
    return data


def _fred_download(start,end):
    from pandas_datareader import data as pdr
    x=pdr.DataReader('T10Y3M','fred',start,str(end))
    if x.empty:raise RuntimeError('FRED T10Y3M empty response')
    return _normalize(x).rename(columns={'T10Y3M':FRED})


def bootstrap_raw(project,asof,*,need_open_start=None):
    """Create raw prices + macro + full historical open cache on a completely clean project.

    Only returns when the requested KR session's 44 closes & ^KS11 are verified.
    A full panel starts in 2012 for rolling windows & Kalman fitting.
    """
    project=Path(project).resolve();end=pd.Timestamp(asof).normalize()
    dat=project/'data'/'kr'; raw=dat/'raw';cache=dat/'cache_prices'; live=dat/'live_cache';meta=dat/'metadata'
    for path in (raw,cache,live,meta):path.mkdir(parents=True,exist_ok=True)
    if len(TRAINED_TICKERS)!=44 or len(set(TRAINED_TICKERS))!=44:raise AssertionError('Corrupt fixed training universe')
    if end<pd.Timestamp('2013-07-01'):
        raise ValueError('Initial download requires >=2013-07-01 to have full Kalman warm-up')
    info(f'Empty project: full history {START}..{end.date()} for exactly 44 frozen stocks')
    idx=_cached_yahoo('^KS11',START,end,cache/'macro_market_index.csv',('Adj Close',))
    if end not in idx.index or not np.isfinite(float(idx.loc[end,'Adj Close'])):
        raise RuntimeError(f'No KOSPI (^KS11) close for {end.date()}: holiday/unpublished/wrong requested date')
    calendar=idx.index[idx.index>=pd.Timestamp('2012-07-02')]
    # Match original preprocessor: index calendar with all-equity shared missing days removed.
    adj={};opens={};raw_closes={};audits=[]
    for i,ticker in enumerate(TRAINED_TICKERS,1):
        cache_file=cache/f'{ticker}_ohlc.csv'
        df=_cached_yahoo(ticker+'.KS',START,end,cache_file,('Open','Close','Adj Close'))
        if end not in df.index or not np.isfinite(df.loc[end,['Open','Close','Adj Close']].to_numpy(float)).all():
            raise RuntimeError(f'{ticker} has no verified Yahoo OHLC on requested session {end.date()}; no stale fill')
        if (df[['Open','Close','Adj Close']].loc[end].to_numpy(float)<=0).any():
            raise RuntimeError(f'{ticker} invalid latest OHLC')
        a=df['Adj Close'].reindex(calendar).astype(float)
        pre=a.loc[:min(end,pd.Timestamp('2025-03-31'))]
        coverage=float(pre.isna().mean())
        first=df['Adj Close'].dropna().index.min()
        audits.append(dict(ticker=ticker,source=ticker+'.KS',first_date=str(first.date()),
                           coverage_missing=coverage,latest_seen=str(df.index.max().date())))
        if first>pd.Timestamp('2012-06-15') or coverage>.01:
            raise RuntimeError(f'{ticker} historical Yahoo data differs from frozen preprocessing coverage: '
                               f'first={first.date()} missing={coverage:.2%}. Cannot silently replace trained stock.')
        adj[ticker]=a
        opens[ticker]=df['Open'].reindex(calendar).astype(float)
        raw_closes[ticker]=df['Close'].reindex(calendar).astype(float)
        info(f'stocks {i:02d}/44: {ticker} ({len(df):,} rows)')
    adj=pd.DataFrame(adj,index=calendar)
    oh=pd.DataFrame(opens,index=calendar)
    rh=pd.DataFrame(raw_closes,index=calendar)
    shared=adj.isna().all(axis=1)
    if shared.any():
        if shared.loc[end]:raise RuntimeError(f'No stock observed at {end.date()}')
        adj=adj.loc[~shared];oh=oh.loc[~shared];rh=rh.loc[~shared]
        info(f'ignored {shared.sum()} shared Yahoo/KOSPI calendar mismatches')
    missing=adj.isna().mean()
    if (missing>.003).any():
        raise RuntimeError('Price missing history exceeds preprocessing threshold: '+str(missing[missing>.003].to_dict()))
    if adj.loc[end].isna().any() or oh.loc[end].isna().any() or rh.loc[end].isna().any():
        raise RuntimeError('One or more of 44 latest OHLC missing; refuse to forward-fill latest session')
    adj=adj.ffill(limit=1)
    if adj.isna().any().any() or (adj<=0).any().any():
        raise RuntimeError('Unresolved historical price gaps (limit=1), cannot compute faithful features')
    if len(adj)<253:raise RuntimeError('Not enough market sessions for historical risk estimates')
    macro={}
    macro['market_index']=idx['Adj Close']
    for key,symbol in list(MACROS.items())[1:]:
        fr=_cached_yahoo(symbol,START,end,cache/f'macro_{key}.csv',('Adj Close',))
        macro[key]=fr['Adj Close']
        info(f'macro {key}: {symbol} ({len(fr):,} rows)')
    fpath=cache/'fred_T10Y3M.csv'
    if fpath.is_file():
        old=_normalize(pd.read_csv(fpath,index_col=0,parse_dates=True))
        if old.index.max()>=end-pd.Timedelta(days=4):f=old
        else:f=_fred_download(START,end);_write_csv(fpath,f)
    else:
        f=_fred_download(START,end);_write_csv(fpath,f)
    if FRED not in f.columns:raise RuntimeError('FRED macro column missing')
    macro[FRED]=f[FRED]
    macro=pd.concat(macro,axis=1).sort_index()
    macro=macro.loc[:end,['market_index','dollar_index','vix','gold',FRED]]
    # Checks strictly the raw data available on the requested Korea close. Foreign series
    # and FRED are shifted one whole KR trading day during feature construction.
    for key in ('dollar_index','vix','gold',FRED):
        prior=macro[key].loc[:end-pd.Timedelta(days=1)].dropna()
        if prior.empty or (end-prior.index[-1]).days>10:
            raise RuntimeError(f'{key} last prior value too old to build as-of features')
    if end not in macro.index or not np.isfinite(macro.loc[end,'market_index']):
        raise RuntimeError('KOSPI index latest price missing in macro panel')
    _write_csv(meta/'stable_kospi200_44.csv',pd.DataFrame({'ticker':TRAINED_TICKERS,
                                    'origin':'KR_STABLE_01_STEP3_EXECUTED_OUTPUT_FIXED_44'}))
    _write_csv(meta/'bootstrap_price_audit.csv',pd.DataFrame(audits))
    _write_csv(meta/'shared_market_session_removed.csv',pd.DataFrame({'date':calendar[shared].astype(str)}))
    # Original-file names are written only if they don't exist. No rewriting of pretrained arrays.
    _write_csv(raw/'stable_kospi200_44_adj_close.csv',adj)
    _write_csv(raw/'macro_raw.csv',macro)
    # The initial download contains the whole OHLC history: backtest can start directly
    # instead of redownloading 44 tickers for each window.
    _write_csv(live/'kr_yahoo_raw_open.csv',oh)
    _write_csv(live/'kr_yahoo_raw_close.csv',rh)
    _write_csv(live/'kr_close_live.csv',adj)
    _write_csv(live/'macro_raw_live.csv',macro)
    info(f'Saved raw & OHLC: {len(adj)} KR sessions × {len(TRAINED_TICKERS)} tickers. '
         f'Features will be built causally when a signal date is requested.')
    return adj,macro
