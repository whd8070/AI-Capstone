"""Run from src/diffusion: streamlit run kr_report_web.py --server.address 127.0.0.1"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import kr_report_jobs as jobs

import pandas as pd
import streamlit as st

import kr_report_engine as eng

st.set_page_config(page_title='MOM + PAIR + REPORT', page_icon='📈', layout='wide')
PROJECT = Path(__file__).resolve().parent

st.title('KR MOM + PAIR + REPORT')
st.caption('로컬 전용 · 동결된 STABLE · 44종목 횡단면 순위 · BL/CVaR 최적화 · 20개 슬리브 · 다음 KRX 시가 체결')
with st.sidebar:
    st.subheader('순위 신호 배합')
    pair = st.slider('PAIR 비율', min_value=0.0, max_value=1.0, value=0.5, step=0.05,
                     help='MOM+PAIR 신호에서 PAIR의 비율 (1−PAIR가 MOM)')
    report = st.slider('REPORT 비율', min_value=0.0, max_value=1.0, value=0.5, step=0.05,
                       help='최종 신호의 REPORT 비율 (1−REPORT가 MOM+PAIR)')
    st.latex(r'z_{base}=(1-p)z_{MOM}+p z_{PAIR}')
    st.latex(r'z_{final}=(1-r)z_{base}+r z_{REPORT}')
    st.caption('숫자는 최종 투자비중의 가중평균이 아니라 위험 최적화 전 순위 신호의 비율입니다.')
    st.divider()
    # Reproducible frozen model configuration; no editable K / seed controls.
    k, seed = eng.FIXED_K, eng.FIXED_SEED
    st.caption(f'추론 설정 고정: K={k}, 시드={seed} (변경 불가)')
    threads = st.number_input('CPU 스레드', min_value=1, max_value=32, value=4, step=1)
    fee = st.number_input('편도 수수료 (bp)', min_value=0.0, max_value=500.0, value=20.0, step=1.0)
    fetch = st.checkbox('원격 시세 자동 다운로드/갱신', value=True)
    st.caption('상태 저장: diffusion/results/kr_report_dashboard/ (Git 추적 대상 아님)')

try:
    consensus = eng.load_consensus(PROJECT)
    last = consensus['date'].max()
    first = consensus['date'].min()
    st.info(f'현재 컨센서스 파일: {str(eng.report_files(PROJECT)["consensus"])} · '
            f'{first.date()} ~ {last.date()} · {len(consensus):,}행. '
            '매수 당일 보고서는 배제하고, 최대 90일 이내의 직전 리포트만 사용합니다.')
except Exception as err:
    st.error(f'리포트 파일을 읽지 못했습니다: {err}')
    st.stop()

bt, portfolio, refresh_tab = st.tabs(['기간 백테스트', '특정 매수일 포트폴리오', '리포트 신규 수집 (선택)'])

with bt:
    st.subheader('REPORT 공개 이후 20슬리브 성과 비교')
    c1,c2,c3 = st.columns([1,1,1])
    start = c1.date_input('시작 신호일', value=first.date(), max_value=dt.date.today(), key='bt_start')
    end = c2.date_input('종료 평가일', value=min(last.date(),dt.date.today()),
                        max_value=dt.date.today(), key='bt_end')
    smoke = c3.checkbox('처음 5개 신호만 점검 (정식 백테스트 아님)', value=False)
    st.caption('시작 신호일 종가로 첫 신호 → 다음 거래일 시가에 첫 슬리브 체결. '
               '지정 기간에 리포트 보유 종목이 2개 미만이면 REPORT 순위화가 불가능해 중단합니다.')
    if st.button('백테스트 실행 (별도 프로세스)', type='primary', key='bt_run'):
        try:
            jobdir, launched = jobs.submit(PROJECT,dict(
                start=str(start),end=str(end),pair_share=pair,report_share=report,
                K=int(k),seed=int(seed),batch=128,threads=int(threads),sleeves=20,
                fee_bps_side=fee,fetch=fetch,max_signals=5 if smoke else None))
            st.session_state['kr_report_job'] = str(jobdir)
            if launched:
                st.success(f'새 백테스트 시작: {jobdir}')
            else:
                st.info('같은 설정의 백테스트가 이미 실행 중입니다.')
        except Exception as exc:
            st.exception(exc)

    all_jobs = sorted([p for p in jobs.jobs_root(PROJECT).iterdir() if p.is_dir()],
                      key=lambda p:p.stat().st_mtime,reverse=True)
    if all_jobs:
        preferred = st.session_state.get('kr_report_job')
        values=[str(p) for p in all_jobs]
        current=values.index(preferred) if preferred in values else 0
        picked=st.selectbox('이전/진행 중인 작업', options=values, index=current,
                            format_func=lambda x:Path(x).name)
        st.session_state['kr_report_job']=picked

        @st.fragment(run_every='5s')
        def show_job(jobdir):
            jobdir=Path(jobdir)
            state=jobs.status(jobdir)
            req=jobdir/'request.json'
            if req.exists():
                conf=json.loads(req.read_text(encoding='utf-8'))
                st.caption(f'요청: 시작={conf.get("start")}, 종료={conf.get("end")}, '
                           f'PAIR={conf.get("pair_share")}, REPORT={conf.get("report_share")}, '
                           f'K={conf.get("K")}, seed={conf.get("seed")}')
            phase=state.get('status')
            if phase in ('running','queued'):
                st.info(f'별도 프로세스 실행 중 · PID {state.get("pid")} · {state.get("step","")}')
                n=state.get('total')
                if n:
                    st.progress(min(1.0,state.get('progress',0)/n))
                elif not list(jobs.active_jobs(PROJECT)):
                    st.warning('실행 프로세스를 찾을 수 없습니다. 로그를 확인하고 재실행할 수 있습니다.')
                else:
                    st.caption('첫 신호 계산 전이거나 원격 시세 다운로드 중입니다.')
            elif phase=='failed':
                st.error(state.get('error','실패'))
                with st.expander('오류 상세'):
                    st.code(state.get('traceback',''))
            elif phase=='done':
                path=Path(state['result_path'])
                metrics=json.loads((path/'metrics.json').read_text(encoding='utf-8'))
                m0,m1=metrics['before'],metrics['after']
                nav0=pd.read_csv(path/'nav_before.csv',index_col=0,parse_dates=True)['nav']
                nav1=pd.read_csv(path/'nav_after.csv',index_col=0,parse_dates=True)['nav']
                st.success(f'계산 완료 · {path}')
                nav=pd.concat([nav0.rename('MOM+PAIR'),nav1.rename('MOM+PAIR+REPORT')],axis=1)
                st.line_chart(nav,use_container_width=True)
                fields=[('누적 수익률','total_return'),('연환산 수익률','annualized_return'),
                        ('샤프 비율','sharpe'),('MDD','max_drawdown'),
                        ('연환산 변동성','annual_volatility'),('총 거래비용','total_fees')]
                rows=[]
                for label,key in fields:
                    def fmt(x):
                        if x is None:return 'N/A'
                        return f'{x:.3f}' if key=='sharpe' else f'{x:.6f} NAV' if key=='total_fees' else f'{x*100:.2f}%'
                    rows.append({'지표':label,'MOM+PAIR':fmt(m0.get(key)),
                                 'REPORT 반영':fmt(m1.get(key))})
                st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
                st.caption('샤프: 무위험수익률 0 · 252거래일 연환산 · 편도 수수료 반영 · 슬리피지/세금 미반영')
                frame=pd.read_csv(path/'daily_rank_weights.csv',dtype={'stock_code':str})
                st.subheader('날짜별 순위·비중 변화')
                st.dataframe(frame,hide_index=True,use_container_width=True)
                st.download_button('전체 날짜별 순위·비중 CSV',data=(path/'daily_rank_weights.csv').read_bytes(),
                                   file_name='kr_report_backtest_rank_weights.csv',mime='text/csv')
            else:
                st.warning(f'작업 상태를 읽지 못했습니다: {phase}')
            with st.expander('로컬 백테스트 로그 (최근 30줄)'):
                logfile=jobdir/'worker.log'
                if logfile.exists():
                    tail='\n'.join(logfile.read_text(encoding='utf-8',errors='replace').splitlines()[-30:])
                    st.code(tail)
        show_job(picked)

with portfolio:
    st.subheader('과거 매수일 선택 → 직전 종가 기준 추론 → 다음 시가 목표비중')
    buy_date = st.date_input('매수일 (실제 KRX 거래일, 과거)',
                             value=min(last.date(),dt.date.today()),
                             max_value=dt.date.today(), key='buy_day')
    agent = st.selectbox('설명 에이전트', options=['local','claude'],
                         format_func=lambda x:'데이터 기반 로컬 설명 (추가 비용 없음)' if x=='local'
                         else 'Claude Code CLI로 한국어 분석 (선택, 로그인/사용량 필요)')
    st.info('표시되는 목표비중은 **해당 매수일에 신규 투입/교체할 1개 슬리브 내부의 비중**입니다. 기존 19개 슬리브를 포함한 전체 계좌 보유비중이 아닙니다.')
    st.caption('이 페이지의 날짜는 신호 생성일이 아니라 매수일입니다. '
               '시세 캘린더에서 전 거래일을 찾아 해당 종가까지만 순위를 계산합니다.')
    if st.button('포트폴리오 생성', type='primary', key='portfolio_run'):
        with st.spinner('전 거래일 시세 갱신 · STABLE 추론 · REPORT 결합 · 컴팩트 근거 생성 중'):
            try:
                st.session_state['kr_report_portfolio'] = eng.portfolio_for_buy_date(
                    PROJECT, buy_date, pair_share=pair, report_share=report,
                    K=int(k), seed=int(seed), threads=int(threads), fetch=fetch, agent=agent)
            except Exception as exc:
                st.exception(exc)
    if 'kr_report_portfolio' in st.session_state:
        r=st.session_state['kr_report_portfolio']
        st.success(f'신호일 {r["decision_date"]} 종가 → 매수일 {r["buy_date"]} 시가 · 유효 리포트 {r["report_coverage"]}개 종목')
        st.caption(f'결과 저장: {r["path"]} (사전 비중/순위, 사후 비중/순위, 필요한 컴팩트 리포트, 해설)')
        if r['agent_warning']:
            st.warning(r['agent_warning'])
        df = pd.DataFrame(r['comparison']).sort_values('after_weight', ascending=False)
        display_columns = ['stock_code','company','before_rank','after_rank','rank_improvement',
                           'before_weight','after_weight','weight_change','report_date',
                           'report_target_price','raw_close','implied_upside']
        st.dataframe(df[display_columns], hide_index=True, use_container_width=True,
                     column_config={
                         'before_weight':st.column_config.NumberColumn('REPORT 전 비중',format='%.4f'),
                         'after_weight':st.column_config.NumberColumn('REPORT 후 비중',format='%.4f'),
                         'weight_change':st.column_config.NumberColumn('비중 변화',format='%+.4f'),
                         'implied_upside':st.column_config.NumberColumn('목표가 괴리율',format='%+.3f')})
        st.download_button('최종·기존 포트폴리오 CSV',
                           data=df.to_csv(index=False).encode('utf-8-sig'),
                           file_name=f'portfolio_{r["buy_date"]}.csv',mime='text/csv')
        st.subheader('동결 모델 O 생성 시나리오 (20거래일)')
        view=[]
        for label, key in [('REPORT 전','scenario_before'),('REPORT 후','scenario_after')]:
            s=r[key]
            view.append({'구분':label,
                         '생성 평균':f"{s['mean_20d']*100:+.2f}%",
                         '중앙값':f"{s['median_20d']*100:+.2f}%",
                         '5% 분위':f"{s['q05_20d']*100:+.2f}%",
                         '음수 시나리오 비율':f"{s['simulated_loss_frequency']*100:.1f}%"})
        st.dataframe(pd.DataFrame(view),hide_index=True,use_container_width=True)
        st.caption('O 모델이 생성한 20영업일 시나리오의 경험적 통계입니다. 확률 보정·수익 예측력을 검증한 투자 전망은 아닙니다.')
        st.subheader('투자비중 변화 근거 및 조건부 전망')
        st.markdown(r['explanation'])
        st.download_button('설명 TXT',data=r['explanation'].encode('utf-8'),
                           file_name=f'explanation_{r["buy_date"]}.txt')
        with st.expander('분석에 실제 사용한 컴팩트 리포트'):
            st.json(r['compact'],expanded=False)

with refresh_tab:
    st.subheader('원본 리포트 신규 수집 · 필요한 부분만 LLM 추출')
    st.warning('별도 선택 기능입니다. 네이버 PDF 다운로드와 Claude Code CLI 추출은 네트워크/로그인이 필요하며 '
               '시간·사용량이 발생할 수 있습니다. 원본 Git 추적 handoff 파일은 수정하지 않습니다.')
    until = st.date_input('리포트 수집 마감일 (매수 전 신호일)',
                          value=min(dt.date.today(),last.date()+dt.timedelta(days=1)),
                          max_value=dt.date.today(),key='refresh_date')
    limit = st.number_input('이번 실행 신규 추출 상한 (건)', min_value=1,max_value=100,value=20)
    cost = st.number_input('신규 추출 API 환산비용 상한 (USD)',min_value=0.1,max_value=100.,value=2.,step=.1)
    confirm = st.checkbox('대상 범위 및 LLM 사용량을 확인했습니다')
    if st.button('신규 리포트만 수집·구조화', disabled=not confirm):
        with st.spinner('선택 날짜 범위의 신규 보고서를 수집/추출하고 있습니다.'):
            try:
                msg=eng.refresh_collection_to(PROJECT,until,limit=int(limit),max_cost=float(cost))
                st.success(msg)
                st.rerun()
            except Exception as exc:
                st.exception(exc)
