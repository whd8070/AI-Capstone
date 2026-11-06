#!/usr/bin/env python3
# Source-derived definitions from PAPER_14_26_2_US_KR_CAL_EARLY_B_RENAME_SAFE(8).ipynb
# Scientific model, O/F/M DDIM, rank conversion, and CVaR repair retained.
# All execution is CPU-only; CUDA is masked before torch import.
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''
for _k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_k,'1')
import copy, hashlib, math
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from scipy.stats import rankdata
from sklearn.covariance import LedoitWolf

HORIZON=20
MACRO_DIM=10
STOCK_COND_DIM=13
MODEL_CONFIG={}

# Model and portfolio primitives transcribed from audited source workers.
def _valid_group_count(channels, preferred):
    g = min(int(preferred), int(channels))
    while g > 1 and channels % g != 0:
        g -= 1
    return g

class SinusoidalTimeEmbedding(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.dim = dim

    def forward(self, t):
        half = self.dim // 2
        freq = torch.exp(
            -math.log(10000)
            * torch.arange(half, device=t.device, dtype=torch.float32)
            / max(half - 1, 1)
        )
        x = t.float()[:, None] * freq[None, :]
        emb = torch.cat([torch.sin(x), torch.cos(x)], dim=1)
        if self.dim % 2 == 1:
            emb = F.pad(emb, (0, 1))
        return emb

class ResidualBlock1D(nn.Module):
    def __init__(self, in_ch, out_ch, emb_dim, group_norm_groups=4):
        super().__init__()
        groups = _valid_group_count(out_ch, group_norm_groups)
        self.conv1 = nn.Conv1d(in_ch, out_ch, kernel_size=3, padding=1)
        self.conv2 = nn.Conv1d(out_ch, out_ch, kernel_size=3, padding=1)
        self.norm1 = nn.GroupNorm(groups, out_ch)
        self.norm2 = nn.GroupNorm(groups, out_ch)
        self.emb_proj = nn.Linear(emb_dim, out_ch)
        self.skip = (
            nn.Conv1d(in_ch, out_ch, kernel_size=1)
            if in_ch != out_ch else nn.Identity()
        )

    def forward(self, x, emb):
        h = F.silu(self.norm1(self.conv1(x)))
        h = h + self.emb_proj(emb)[:, :, None]
        h = F.silu(self.norm2(self.conv2(h)))
        return h + self.skip(x)

class ConditionalUNet1D(nn.Module):
    def __init__(
        self,
        horizon=20,
        cond_dim=32,
        time_dim=32,
        base_channels=32,
        stage_blocks=1,
        mid_blocks=2,
        group_norm_groups=4,
    ):
        super().__init__()
        self.horizon = horizon
        c1 = int(base_channels)
        c2 = 2 * c1
        c3 = 4 * c1

        if stage_blocks < 1:
            raise ValueError("stage_blocks must be >= 1")
        if mid_blocks < 2:
            raise ValueError("mid_blocks must be >= 2 for checkpoint compatibility")

        self.time_embedding = nn.Sequential(
            SinusoidalTimeEmbedding(time_dim),
            nn.Linear(time_dim, time_dim),
            nn.SiLU(),
            nn.Linear(time_dim, time_dim),
        )
        self.cond_embedding = nn.Sequential(
            nn.Linear(cond_dim, time_dim),
            nn.SiLU(),
            nn.Linear(time_dim, time_dim),
        )
        emb_dim = time_dim

        # Keep original module names so existing current-size checkpoints load.
        self.in_conv = nn.Conv1d(1, c1, kernel_size=3, padding=1)
        self.enc1 = ResidualBlock1D(c1, c1, emb_dim, group_norm_groups)
        self.enc1_extra = nn.ModuleList([
            ResidualBlock1D(c1, c1, emb_dim, group_norm_groups)
            for _ in range(stage_blocks - 1)
        ])

        self.down1 = nn.Conv1d(c1, c2, kernel_size=4, stride=2, padding=1)
        self.enc2 = ResidualBlock1D(c2, c2, emb_dim, group_norm_groups)
        self.enc2_extra = nn.ModuleList([
            ResidualBlock1D(c2, c2, emb_dim, group_norm_groups)
            for _ in range(stage_blocks - 1)
        ])

        self.down2 = nn.Conv1d(c2, c3, kernel_size=4, stride=2, padding=1)

        self.mid1 = ResidualBlock1D(c3, c3, emb_dim, group_norm_groups)
        self.mid2 = ResidualBlock1D(c3, c3, emb_dim, group_norm_groups)
        self.mid_extra = nn.ModuleList([
            ResidualBlock1D(c3, c3, emb_dim, group_norm_groups)
            for _ in range(mid_blocks - 2)
        ])

        self.up2 = nn.ConvTranspose1d(c3, c2, kernel_size=4, stride=2, padding=1)
        self.dec2 = ResidualBlock1D(2 * c2, c2, emb_dim, group_norm_groups)
        self.dec2_extra = nn.ModuleList([
            ResidualBlock1D(c2, c2, emb_dim, group_norm_groups)
            for _ in range(stage_blocks - 1)
        ])

        self.up1 = nn.ConvTranspose1d(c2, c1, kernel_size=4, stride=2, padding=1)
        self.dec1 = ResidualBlock1D(2 * c1, c1, emb_dim, group_norm_groups)
        self.dec1_extra = nn.ModuleList([
            ResidualBlock1D(c1, c1, emb_dim, group_norm_groups)
            for _ in range(stage_blocks - 1)
        ])

        out_groups = _valid_group_count(c1, group_norm_groups)
        self.out = nn.Sequential(
            nn.GroupNorm(out_groups, c1),
            nn.SiLU(),
            nn.Conv1d(c1, 1, kernel_size=3, padding=1),
        )

    @staticmethod
    def _run_extra(x, emb, blocks):
        for block in blocks:
            x = block(x, emb)
        return x

    def forward(self, x, t, cond):
        x = x.unsqueeze(1)
        emb = self.time_embedding(t) + self.cond_embedding(cond)

        x0 = self.in_conv(x)
        e1 = self.enc1(x0, emb)
        e1 = self._run_extra(e1, emb, self.enc1_extra)

        e2 = self.enc2(self.down1(e1), emb)
        e2 = self._run_extra(e2, emb, self.enc2_extra)

        m = self.mid1(self.down2(e2), emb)
        m = self.mid2(m, emb)
        m = self._run_extra(m, emb, self.mid_extra)

        u2 = self.up2(m)
        if u2.shape[-1] != e2.shape[-1]:
            u2 = F.interpolate(u2, size=e2.shape[-1], mode="linear", align_corners=False)
        u2 = self.dec2(torch.cat([u2, e2], dim=1), emb)
        u2 = self._run_extra(u2, emb, self.dec2_extra)

        u1 = self.up1(u2)
        if u1.shape[-1] != e1.shape[-1]:
            u1 = F.interpolate(u1, size=e1.shape[-1], mode="linear", align_corners=False)
        u1 = self.dec1(torch.cat([u1, e1], dim=1), emb)
        u1 = self._run_extra(u1, emb, self.dec1_extra)

        out = self.out(u1)
        if out.shape[-1] != self.horizon:
            out = F.interpolate(out, size=self.horizon, mode="linear", align_corners=False)
        return out.squeeze(1)

class STABLE(nn.Module):
    def __init__(
        self,
        macro_dim,
        stock_dim,
        d_model=16,
        z_max=2.0,
        base_channels=32,
        time_dim=32,
        gate_hidden_dim=32,
        stage_blocks=1,
        mid_blocks=2,
        group_norm_groups=4,
    ):
        super().__init__()
        self.d_model = d_model
        self.z_max = z_max

        self.macro_encoder = nn.Linear(macro_dim, d_model)
        self.stock_encoder = nn.Linear(stock_dim, d_model)
        full_dim = 2 * d_model

        self.unet = ConditionalUNet1D(
            horizon=HORIZON,
            cond_dim=full_dim,
            time_dim=time_dim,
            base_channels=base_channels,
            stage_blocks=stage_blocks,
            mid_blocks=mid_blocks,
            group_norm_groups=group_norm_groups,
        )

        self.gate = nn.Sequential(
            nn.Linear(full_dim, gate_hidden_dim),
            nn.SiLU(),
            nn.Linear(gate_hidden_dim, 1),
            nn.Sigmoid(),
        )

    def encode_conditions(self, macro, stock_cond):
        h_macro = self.macro_encoder(macro)
        h_stock = self.stock_encoder(stock_cond)
        h_full = torch.cat([h_macro, h_stock], dim=1)
        return h_macro, h_stock, h_full

    def forward(
        self,
        x_noisy,
        timestep,
        macro,
        stock_cond,
        return_components=False,
    ):
        h_macro, h_stock, h_full = self.encode_conditions(macro, stock_cond)
        zero_stock = torch.zeros_like(h_macro)
        macro_only_condition = torch.cat([h_macro, zero_stock], dim=1)

        eps_macro = self.unet(x_noisy, timestep, macro_only_condition)
        eps_full = self.unet(x_noisy, timestep, h_full)
        z = self.gate(h_full) * self.z_max
        eps_hat = eps_macro + z * (eps_full - eps_macro)

        if return_components:
            return {
                "eps_hat": eps_hat,
                "eps_macro": eps_macro,
                "eps_full": eps_full,
                "z": z.squeeze(-1),
                "h_macro": h_macro,
                "h_stock": h_stock,
            }
        return eps_hat

def build_stable_model(model_config=None):
    cfg = copy.deepcopy(MODEL_CONFIG if model_config is None else model_config)
    return STABLE(
        macro_dim=MACRO_DIM,
        stock_dim=STOCK_COND_DIM,
        d_model=int(cfg["d_model"]),
        z_max=float(cfg["z_max"]),
        base_channels=int(cfg["base_channels"]),
        time_dim=int(cfg["time_dim"]),
        gate_hidden_dim=int(cfg["gate_hidden_dim"]),
        stage_blocks=int(cfg["stage_blocks"]),
        mid_blocks=int(cfg["mid_blocks"]),
        group_norm_groups=int(cfg["group_norm_groups"]),
    )

def stable_seed(*args):
    return int.from_bytes(hashlib.sha256('|'.join(map(str,args)).encode()).digest()[:8],'little')%(2**32)

def floor_psd(C,rel=1e-5):
    C=np.asarray(C,float);C=(C+C.T)*.5
    e,V=np.linalg.eigh(C)
    return (V*np.maximum(e,max(float(e.max())*rel,1e-9)))@V.T

def hist_cov(px,d,names):
    p=px.loc[px.index<=pd.Timestamp(d),names].dropna().tail(121)
    assert len(p)==121,('Insufficient 121 prices',d,len(p))
    x=np.expm1(np.log(p).diff().dropna().rolling(20).sum().dropna().to_numpy(float))
    assert x.shape==(101,len(names))
    C=np.cov(x,rowvar=False,ddof=1);e,V=np.linalg.eigh((C+C.T)*.5)
    return (V*np.maximum(e,max(float(e.max())*1e-5,1e-12)))@V.T

def orig_weights(view,beta=.5):
    view=np.asarray(view,dtype=np.float64)
    ew=np.full(len(view),1/len(view),dtype=float)
    r=np.linalg.norm(view)/max(np.linalg.norm(ew),1e-12)
    w=np.maximum(ew+(1-beta)/(1+beta*r)*view,0.)
    return w/w.sum() if w.sum()>1e-12 else ew

def rank_z(mu):
    n=len(mu)
    return (rankdata(mu,method='average')-(n+1)/2)/np.sqrt((n*n-1)/12)


@torch.inference_mode()
def triple_ddim(model,abar,times,noise,macro,stock,device,batch_size=4096):
    # O: learned guidance at its own DDIM state; F/M: separate DDIM states, SAME x_T.
    K,N,H=noise.shape
    assert H==20 and len(macro)==len(stock)==N
    flattened=noise.transpose(1,0,2).copy().reshape(N*K,H)
    output=np.empty((3,N*K,H),dtype=np.float32)
    mt=torch.from_numpy(np.asarray(macro,np.float32)).to(device)
    st=torch.from_numpy(np.asarray(stock,np.float32)).to(device)
    for b in range(0,len(flattened),batch_size):
        e=min(b+batch_size,len(flattened))
        ix=torch.arange(b,e,device=device)//K
        hm,hs,hf=model.encode_conditions(mt[ix],st[ix])
        hmacro=torch.cat((hm,torch.zeros_like(hm)),dim=1)
        g=model.gate(hf)*model.z_max
        init=torch.from_numpy(flattened[b:e]).to(device=device,dtype=torch.float32)
        xo=init.clone();xf=init.clone();xm=init.clone()
        for j,t in enumerate(times):
            ti=torch.full((e-b,),int(t),device=device,dtype=torch.long)
            # all evaluations at their respective current diffusion state
            eo_m=model.unet(xo,ti,hmacro)
            eo_f=model.unet(xo,ti,hf)
            eo=eo_m+g*(eo_f-eo_m)
            ef=model.unet(xf,ti,hf)
            em=model.unet(xm,ti,hmacro)
            a=abar[int(t)]
            co=(xo-torch.sqrt(1-a)*eo)/torch.sqrt(a)
            cf=(xf-torch.sqrt(1-a)*ef)/torch.sqrt(a)
            cm=(xm-torch.sqrt(1-a)*em)/torch.sqrt(a)
            if j==len(times)-1:xo,xf,xm=co,cf,cm
            else:
                ap=abar[int(times[j+1])]
                xo=torch.sqrt(ap)*co+torch.sqrt(1-ap)*eo
                xf=torch.sqrt(ap)*cf+torch.sqrt(1-ap)*ef
                xm=torch.sqrt(ap)*cm+torch.sqrt(1-ap)*em
        for k,v in enumerate((xo,xf,xm)):
            output[k,b:e]=v.cpu().numpy()
    terminal=[]
    for array in output:
        paths=array.reshape(N,K,H).transpose(1,0,2)
        terminal.append(np.expm1(np.clip(paths.astype(np.float64).sum(axis=-1),-12,12)).astype(np.float32))
    assert all(x.shape==(K,N) and np.isfinite(x).all() for x in terminal)
    return terminal


# Audited downside-risk repair functions; no runtime import of worker14_13.
def validate_w(w, cap=1.):
    w=np.asarray(w,dtype=np.float64)
    if w.ndim!=1 or not np.isfinite(w).all() or w.min() < -1e-10 or w.max()>cap+1e-9 or abs(w.sum()-1)>1e-9:
        raise RuntimeError('Invalid long-only stock100 portfolio')
    return w

def project_simplex(x,cap=1.,tol=1e-13):
    """Exact up to tolerance Euclidean projection onto capped unit simplex."""
    x=np.asarray(x,dtype=np.float64); n=len(x)
    if x.ndim!=1 or not np.isfinite(x).all() or cap*n < 1-1e-12 or cap<=0:
        raise RuntimeError('Invalid projection input')
    if cap>=1.:
        u=np.sort(x)[::-1]
        ss=np.cumsum(u)-1
        hits=np.flatnonzero(u>ss/(np.arange(n)+1))
        if len(hits)==0: raise RuntimeError('Simplex projection missing rho')
        thresh=ss[hits[-1]]/(hits[-1]+1)
        w=np.maximum(x-thresh,0)
    else:
        lo=np.min(x)-cap-1.;hi=np.max(x)+1.
        for _ in range(75):
            mid=(lo+hi)/2
            if np.clip(x-mid,0,cap).sum()>1:lo=mid
            else:hi=mid
        w=np.clip(x-(lo+hi)/2,0,cap)
    # normalize tiny float error WITHOUT changing binding feasibility
    err=1-w.sum()
    if abs(err)>tol:
        free=np.where((w>tol)&(w<cap-tol))[0]
        if len(free):w[free]+=err/len(free)
    validate_w(w,cap=cap)
    return w

def trailing_20day(prices,date,names,lookback):
    frame=prices.loc[prices.index<=pd.Timestamp(date),names].dropna().tail(int(lookback)+1)
    if len(frame)!=lookback+1:
        raise RuntimeError(f'Insufficient pre-decision data {date}: {len(frame)}/{lookback+1}')
    if frame.index.max()>pd.Timestamp(date):raise RuntimeError('History leakage')
    X=np.expm1(np.log(frame).diff().dropna().rolling(20).sum().dropna().to_numpy(np.float64))
    if X.shape!=(lookback-19,len(names)) or not np.isfinite(X).all():
        raise RuntimeError('Historical scenario shape issue')
    return X

def risk_value_grad(X,w,kind='semi',eps=1e-3):
    """Nonnegative empirical variance / LPM2 / *smoothed* shortfall CVaR90.

    CVaR uses loss=(-Xw)_+, with smoothed hinge and CVaR infimum over VaR t>=0;
    smoothness disclosed in experiment. Observed X denotes 20D asset returns.
    """
    X=np.asarray(X,np.float64);w=np.asarray(w,np.float64)
    if X.ndim!=2 or X.shape[1]!=w.size or not np.isfinite(X).all():raise RuntimeError('Bad risk data')
    r=X@w
    if kind=='variance':
        centered=X-X.mean(axis=0,keepdims=True)
        x=centered@w
        return float(x@x/len(x)),(2/len(x))*centered.T@x
    if kind=='semi':
        bad=np.minimum(r,0.)
        return float(bad@bad/len(r)),(2/len(r))*X.T@bad
    if kind=='cvar90':
        # Smoothed shortfall CVaR: positive-part is softplus_eps, tail hinge softplus_eps.
        # Separate eps values may be configured; same per-scenario horizon across arms.
        e=float(eps)
        short=e*np.logaddexp(0.,-r/e)
        # Find min over VaR t>=0; CVaR at confidence .90 = t+10*E[(short-t)_+]
        # smooth hinge in t and via logistic. Unique t for this smooth objective.
        q=.10;lo=0.;hi=float(short.max()+30*e)
        for _ in range(30):
            t=.5*(lo+hi)
            sig=1/(1+np.exp(np.clip((t-short)/e,-500,500)))
            if sig.mean()>q:lo=t
            else:hi=t
        t=.5*(lo+hi)
        z=(short-t)/e
        tail=e*np.logaddexp(0.,z)
        val=t+float(tail.mean()/q)
        h=1/(1+np.exp(np.clip(r/e,-500,500)))
        g=-(X.T@(sig*h))/(q*len(r))
        return val,g
    raise ValueError(kind)

def optimize_repair(w0,sources,kind='semi',target=.90,penalty=1.,cap=1.,
                    max_iter=180,tol=3e-7):
    """Unique convex objective in w (anchor quadratic + squared positive ratio excess).

    min_{w in simplex_cap} 0.5||w-w0||^2 + penalty/2 * max(0,max_m D_m(w)/D_m(w0)-target)^2
    Slack xi is analytically eliminated; original constraint: ratio <=target+xi, xi>=0.
    For CVaR, D is the explicit differentiable smoothed 90% downside-CVaR surrogate.
    Numerical descent is feasible at every iteration. If not certified, return w0
    (uncapped), otherwise return certified best feasible projected candidate with flag.
    """
    w0=validate_w(w0)
    src=[np.asarray(X,np.float64) for X in sources]
    n=len(w0)
    for X in src:
        if X.ndim!=2 or X.shape[1]!=n or not np.isfinite(X).all():raise RuntimeError('Invalid sources')
    if kind not in ('semi','variance','cvar90'):raise RuntimeError('Invalid risk kind')
    baselines=np.array([risk_value_grad(X,w0,kind)[0] for X in src])
    # A vanishing downside sample gives no evidence for risk adjustment.
    if np.max(baselines) < 1e-9 and cap>=1:
        return w0.copy(),dict(baseline_risk=float(np.max(baselines)),risk_ratio=1.,slack=0.,
                              success=True,iterations=0,grad_residual=0.,fallback=False,why='no_risk')
    # Normalize per-data baseline; pathological near-zero sample is skipped in ratio max.
    denom=np.maximum(baselines,1e-9)
    def objective(w):
        values=[risk_value_grad(X,w,kind) for X in src]
        ratios=[r[0]/d for r,d in zip(values,denom)]
        j=int(np.argmax(ratios));xi=max(0.,ratios[j]-target)
        diff=w-w0
        value=.5*float(diff@diff)+.5*penalty*xi*xi
        grad=diff+(penalty*xi/denom[j])*values[j][1] if xi>0 else diff
        return value,grad,float(ratios[j]),xi
    w=project_simplex(w0,cap)
    initial=objective(w)[0]
    current=initial
    converged=False;residual=np.inf
    for it in range(max_iter):
        loss,gradient,ratio,xi=objective(w)
        if not np.isfinite(loss) or not np.isfinite(gradient).all():raise RuntimeError('NaN in repair optimizer')
        step=1.
        # Majorization/backtracking ensures monotone descent in convex objective.
        for _ in range(28):
            next_w=project_simplex(w-step*gradient,cap)
            delta=next_w-w
            next_val=objective(next_w)[0]
            if next_val<=loss+gradient@delta+float(delta@delta)/(2*step)+1e-13:
                break
            step*=.5
        else:
            # A too-sharp objective can force a numerically flat step.
            break
        new_loss=next_val
        w=next_w
        # gradient mapping uses scale-free bounded step 1e-2, independent of line search
        residual=float(np.max(np.abs(w-project_simplex(w-.01*objective(w)[1],cap))))
        current=new_loss
        if residual<tol or np.max(np.abs(delta))<1e-11:
            converged=True
            break
    if not np.isfinite(residual):residual=float('inf')
    val,grad,ratio,xi=objective(w)
    valid=val<=initial+1e-8 and np.isfinite(val) and np.isfinite(w).all()
    if not valid:raise RuntimeError('Numerical optimizer worsened initial portfolio')
    # Boundaries include w0 projection for cap strategies, never silently declare convergence.
    meta=dict(baseline_risk=float(np.max(baselines)),risk_ratio=float(ratio),slack=float(xi),
              success=bool(converged and residual<5*tol),iterations=it+1,
              grad_residual=residual,fallback=False,why='pg')
    if not meta['success']:
        # Return *feasible* initial allocation, tagged as failed optimization.
        # This avoids fabricating a superior globally optimal portfolio.
        meta.update(fallback=True,why='not_converged')
        w=project_simplex(w0,cap)
        _,_,ratio,xi=objective(w);meta.update(risk_ratio=float(ratio),slack=float(xi))
    validate_w(w,cap)
    return w,meta
def historical_inputs(px,date,names):
    X=trailing_20day(px,date,names,252)
    H=hist_cov(px,date,names)
    G=np.linalg.solve(.05*H+np.diag(.05*np.maximum(np.diag(H),1e-9)),(.05*H).T).T
    scale=float(np.median(np.sqrt(np.maximum(np.diag(H),0))))
    p=px.loc[px.index<=pd.Timestamp(date),names].tail(21)
    assert len(p)==21 and p.index.max()<=pd.Timestamp(date)
    mom=p.iloc[-1].to_numpy(float)/p.iloc[0].to_numpy(float)-1
    return dict(X=X,H=H,G=G,s=scale,zm=rank_z(mom))

def rank_anchor(z,C,h,beta=.5,lam=-1.):
    u=np.linalg.solve(C,h['G']@(h['s']*(np.asarray(z,float)+float(lam))))
    return orig_weights(u,beta)

def rank_repair(z,C,h,cfg):
    anchor=rank_anchor(z,C,h,beta=cfg['beta'],lam=-1.)
    w,diag=optimize_repair(anchor,[h['X']],kind='cvar90',target=cfg['target_ratio'],
                          penalty=cfg['slack_penalty'],max_iter=cfg['optimizer_max_iter'],cap=1.)
    return validate_w(w),diag


