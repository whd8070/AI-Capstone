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

from kr_report_collection import codex_status, claude_status, collection_plan


@st.cache_data(ttl=60, show_spinner=False)
def get_llm_status():
    return {'codex': codex_status(), 'claude': claude_status()}


def connected_agents():
    states = get_llm_status()
    return [key for key in ('codex', 'claude') if states[key]['ready']]


def display_agent(key):
    return {'local': '데이터 기반 로컬 해설 (LLM 호출 없음)',
            'codex': 'Codex CLI (로그인 확인됨)',
            'claude': 'Claude CLI (로그인 확인됨)'}[key]


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
    available_explain = ['local'] + connected_agents()
    explanation_agent = st.selectbox(
        '포트폴리오 설명 방식', options=available_explain,
        format_func=display_agent, key='portfolio_explain_agent')
    if explanation_agent != 'local':
        st.caption('먼저 수치 포트폴리오와 로컬 설명을 표시합니다. '
                   '이후 별도 버튼으로 선택한 CLI 설명·독립 검증을 수행합니다. '
                   'AI 재설명은 STABLE 추론·위험 최적화를 다시 실행하지 않습니다.')
    elif len(available_explain) == 1:
        st.caption('연결된 Claude/Codex CLI가 없어 로컬 해설을 표시합니다. '
                   '3번째 페이지에서 CLI 설치·로그인을 확인할 수 있습니다.')
    st.info('표시되는 목표비중은 **해당 매수일에 신규 투입/교체할 1개 슬리브 내부의 비중**입니다. 기존 19개 슬리브를 포함한 전체 계좌 보유비중이 아닙니다.')
    st.caption('이 페이지의 날짜는 신호 생성일이 아니라 매수일입니다. '
               '시세 캘린더에서 전 거래일을 찾아 해당 종가까지만 순위를 계산합니다.')
    if st.button('포트폴리오 생성 (수치 먼저 표시)', type='primary', key='portfolio_run'):
        with st.status('포트폴리오 계산 시작', expanded=True) as status:
            stage = st.empty()
            try:
                st.session_state['kr_report_portfolio'] = eng.portfolio_for_buy_date(
                    PROJECT, buy_date, pair_share=pair, report_share=report,
                    K=int(k), seed=int(seed), threads=int(threads), fetch=fetch,
                    agent='local', progress=lambda message: stage.info(message))
                status.update(label='수치 포트폴리오 준비 완료', state='complete',
                              expanded=False)
            except Exception as exc:
                status.update(label='포트폴리오 계산 오류', state='error')
                st.exception(exc)
    current_portfolio = st.session_state.get('kr_report_portfolio')
    if current_portfolio is not None and explanation_agent != 'local':
        if st.button('AI 설명 생성·독립 검증 (모델 추론 재실행 없음)',
                     key='portfolio_ai_explain'):
            with st.status('선택한 에이전트로 설명 및 검증', expanded=True) as status:
                progress_line = st.empty()
                try:
                    updated = eng.regenerate_portfolio_explanation(
                        current_portfolio, explanation_agent,
                        progress=lambda message: progress_line.info(message))
                    st.session_state['kr_report_portfolio'] = updated
                    if updated.get('agent_used') == explanation_agent:
                        status.update(label='AI 설명·검증 완료', state='complete')
                    else:
                        status.update(label='AI 검증 불합격 · 로컬 설명으로 대체', state='error')
                except Exception as exc:
                    status.update(label='AI 설명 처리 실패 · 이전 결과 유지', state='error')
                    st.exception(exc)
    if 'kr_report_portfolio' in st.session_state:
        r=st.session_state['kr_report_portfolio']
        st.success(f'신호일 {r["decision_date"]} 종가 → 매수일 {r["buy_date"]} 시가 · 유효 리포트 {r["report_coverage"]}개 종목')
        st.caption(f'결과 저장: {r["path"]} (사전 비중/순위, 사후 비중/순위, 필요한 컴팩트 리포트, 해설)')
        st.caption('해설 생성: '+display_agent(r.get('agent_used', 'local')))
        elapsed = r.get('stage_seconds')
        if elapsed:
            with st.expander(f"계산 단계별 시간 (총 {elapsed.get('total', 0):.2f}초)"):
                st.dataframe(pd.DataFrame([
                    {'단계': name, '초': f'{seconds:.2f}'}
                    for name, seconds in elapsed.items()
                ]), hide_index=True, use_container_width=True)
        if r.get('agent_warning'):
            st.warning(r['agent_warning'])
        held_only = st.checkbox('실제 편입 종목만 보기 (최종 비중 0% 제외)', value=True,
                                key='portfolio_holdings_only')
        display_rows = eng.display_portfolio_rows(r['comparison'], held_only=held_only)
        st.caption(f"표시 종목 {len(display_rows)}개 / 전체 {len(r['comparison'])}개 · "
                   "비중은 % 단위 소수점 둘째 자리 표시, 변화는 %p 단위입니다. "
                   "표시만 반올림하고 원본 계산/CSV는 정밀도를 유지합니다.")
        st.dataframe(pd.DataFrame(display_rows), hide_index=True, use_container_width=True)
        verification = r.get('verification', {})
        if verification.get('status') == 'PASS':
            st.success(f"독립 검증 승인 · 주장 {verification.get('claim_count', 0)}개 · "
                       f"검증 모델 {verification.get('backend', '-')}")
        elif verification.get('status') == 'LOCAL_RULE_ONLY':
            st.info('로컬 설명: 구조·표시 규칙만 검사했습니다. 독립 LLM 의미 검증은 수행하지 않았습니다.')
        else:
            st.warning('설명 검증 상태를 확인하지 못했습니다. 저장된 검증 결과를 확인하세요.')
        raw_portfolio_df = pd.DataFrame(r['comparison']).sort_values('after_weight', ascending=False)
        st.download_button('최종·기존 포트폴리오 CSV',
                           data=raw_portfolio_df.to_csv(index=False).encode('utf-8-sig'),
                           file_name=f'portfolio_{r["buy_date"]}.csv',mime='text/csv')
        st.subheader('동결 모델 O 생성 시나리오 (20거래일)')
        view=[]
        for label, key in [('REPORT 전','scenario_before'),('REPORT 후','scenario_after')]:
            s=r[key]
            view.append({'구분':label,
                         '생성 평균':f"{s['mean_20d']*100:+.2f}%",
                         '중앙값':f"{s['median_20d']*100:+.2f}%",
                         '5% 분위':f"{s['q05_20d']*100:+.2f}%",
                         '음수 시나리오 비율':f"{s['simulated_loss_frequency']*100:.2f}%"})
        st.dataframe(pd.DataFrame(view),hide_index=True,use_container_width=True)
        st.caption('O 모델이 생성한 20영업일 시나리오의 경험적 통계입니다. 확률 보정·수익 예측력을 검증한 투자 전망은 아닙니다.')
        st.subheader('투자비중 변화 근거 및 모델 시나리오 해석')
        with st.expander('실제 편입 종목별 상대 순위·비중 근거', expanded=False):
            items = r.get('analysis_facts', {}).get('holdings', [])
            if items:
                audit_rows = []
                for item in items:
                    audit_rows.append({
                        '기업': item['company'],
                        '원래 순위': item['rank_before'],
                        '최종 순위': item['rank_after'],
                        'REPORT 점수': item['report_rank_score'],
                        '최종 비중': item['weight_after_pct'],
                        '추월': item['passed_peers_count'],
                        '역전당함': item['passed_by_peers_count'],
                        '리포트': '있음' if item['report_available'] else '없음',
                    })
                st.dataframe(pd.DataFrame(audit_rows), hide_index=True, use_container_width=True)
                st.caption('추월은 상대 점수 역전이며 비중 변화의 인과적 기여도를 뜻하지 않습니다.')
        st.markdown(r['explanation'])
        if r.get('verification'):
            with st.expander('설명 검증 상세 (주장별 판정·근거)'):
                st.json(r['verification'], expanded=False)
        st.download_button('설명 TXT',data=r['explanation'].encode('utf-8'),
                           file_name=f'explanation_{r["buy_date"]}.txt')
        with st.expander('분석에 실제 사용한 컴팩트 리포트'):
            st.json(r['compact'],expanded=False)

with refresh_tab:
    st.subheader('신규 증권사 리포트 수집 · LLM 구조화')
    if st.session_state.get('collection_notice'):
        st.success(st.session_state.pop('collection_notice'))
    st.caption('① 로컬 CLI 로그인 확인 → ② 구조화 엔진 선택 → ③ PDF 수집 및 검증 '
               '→ ④ 컨센서스 반영 → ⑤ 선택적 포트폴리오 계산')
    st.info('새 리포트 구조화는 선택한 Claude/Codex CLI로 실행합니다. '
            '포트폴리오 설명에도 연결된 CLI를 선택할 수 있습니다. '
            '투자비중은 기존 STABLE·BL/CVaR 엔진이 계산합니다.')

    if st.button('CLI 연결 상태 다시 확인', key='llm_recheck'):
        get_llm_status.clear()
    states = get_llm_status()
    cols = st.columns(2)
    for i, key in enumerate(('codex', 'claude')):
        state = states[key]
        with cols[i]:
            st.markdown('**' + ('Codex' if key == 'codex' else 'Claude') + ' CLI**')
            if state['ready']:
                st.success('로그인 확인 · 사용 가능')
                st.caption('실행 파일: ' + state.get('executable', '확인됨'))
            else:
                st.warning(state['message'])

    connected = connected_agents()
    backend = st.selectbox('신규 리포트를 구조화할 LLM', options=connected,
                           format_func=lambda k: 'Codex (연결됨)' if k == 'codex'
                           else 'Claude (연결됨)',
                           placeholder='연결된 CLI 없음', disabled=not connected,
                           key='extract_backend')
    with st.expander('CLI 설치·로그인 안내', expanded=not connected):
        st.markdown('CLI의 로그인 인증 정보는 웹에서 읽거나 저장하지 않습니다.')
        st.markdown('**Codex (필요한 경우 설치):**')
        st.code('npm install -g @openai/codex\ncodex login\ncodex login status', language='bash')
        st.markdown('**Claude (선택 설치 스크립트 및 로그인):**')
        st.code('.\\setup_claude_windows.ps1  # Windows\nbash ./setup_claude_mac.sh  # macOS\nclaude auth login\nclaude auth status', language='bash')
        st.caption('VS Code Codex 확장과 독립 CLI는 로그인 세션을 공유하지 않을 수 있습니다. '
                   '설치 및 로그인 후 연결 상태를 다시 확인하세요.')

    st.divider()
    until = st.date_input('리포트 수집 마감일 (이 날짜까지 공개분)',
                          value=min(dt.date.today(), last.date() + dt.timedelta(days=1)),
                          max_value=dt.date.today(), key='refresh_date')
    try:
        plan = collection_plan(PROJECT, until)
    except Exception as exc:
        st.error(f'수집 범위를 분석하지 못했습니다: {exc}')
        plan = None
    if plan:
        if plan['can_fetch']:
            st.write(f"**수집 대상:** {plan['start']} ~ {plan['end']} · 고정 유니버스 44종목")
            c1, c2, c3 = st.columns(3)
            c1.metric('이미 다운로드한 PDF', f"{plan['already_downloaded']}건")
            c2.metric('이미 구조화한 리포트', f"{plan['already_extracted']}건")
            c3.metric('구조화 대기', f"{plan['pending_extraction']}건")
            st.caption(plan['note'] + ' 기존 Git 추적 handoff 파일은 변경하지 않고 로컬 오버레이에만 반영합니다.')
        else:
            st.info('기본 컨센서스에 해당 날짜까지의 정보가 있습니다. 새 구간이 없습니다.')

    mode = st.radio('수집 단계', ['PDF만 다운로드 (LLM 불필요)',
                               'PDF 다운로드 + 선택한 LLM 구조화 + 컨센서스 반영'],
                    key='collection_mode')
    extract = mode.startswith('PDF 다운로드 +')
    if extract:
        limit = st.number_input('이번 실행 구조화 최대 건수', min_value=1, max_value=300, value=30)
        if backend == 'claude':
            cost = st.number_input('Claude 환산비용 중단 기준 (USD)',
                                   min_value=0.1, max_value=100.0, value=2.0, step=0.5)
            max_tokens = 250000
            st.caption('완료한 호출의 환산 비용을 기준으로 다음 작업을 중단합니다. '
                       '실제 청구액·구독 한도에 대한 하드 캡은 아닙니다.')
        else:
            st.caption('Codex의 누적 토큰 상한은 완료 호출 이후 다음 호출 시작을 중단하는 기준입니다. '
                       '실제 계정 한도에 대한 하드 캡은 아닙니다.')
            max_tokens = st.number_input('이번 실행 누적 토큰 상한 (완료 건 기준)',
                                         min_value=10000, max_value=2000000,
                                         value=250000, step=10000)
            cost = 2.0
        auto_portfolio = st.checkbox('구조화 완료 후 해당 매수일 포트폴리오까지 계산',
                                     key='refresh_auto_portfolio', value=False)
        explain_on_refresh = 'local'
        buy_for_refresh = None
        if auto_portfolio:
            available_explain = ['local'] + connected
            idx = available_explain.index(backend) if backend in available_explain else 0
            explain_on_refresh = st.selectbox(
                '완성된 포트폴리오의 설명 방식', options=available_explain,
                index=idx, format_func=display_agent, key='refresh_explain_agent')
            st.caption('리포트 추출 CLI와 포트폴리오 설명 CLI는 각각 선택합니다. '
                       '비중 최적화 계산에는 LLM이 관여하지 않습니다.')
            suggested = min(dt.date.today(), until + dt.timedelta(days=1))
            buy_for_refresh = st.date_input('포트폴리오 매수일 (실제 KRX 거래일)',
                                            value=suggested, max_value=dt.date.today(),
                                            key='codex_refresh_buy_date')
            st.caption('매수일 전 거래일 종가를 기준으로 신호를 생성합니다. '
                       '매수일 당일 리포트는 사용하지 않으며, 이전 리포트만 적용합니다.')
    else:
        limit, cost, max_tokens, auto_portfolio, buy_for_refresh = 1, 1.0, 250000, False, None
        explain_on_refresh = 'local'
        st.caption('이 단계는 원본 PDF·메타데이터를 수집합니다. '
                   '추출과 컨센서스 및 포트폴리오 갱신은 하지 않습니다.')

    confirm = st.checkbox('수집 범위·선택한 CLI 사용량·시점 제한을 확인했습니다',
                          key='refresh_confirm')
    invalid_dates = bool(auto_portfolio and buy_for_refresh <= until)
    if invalid_dates:
        st.error('포트폴리오 매수일은 수집 마감일 이후여야 합니다. 미래 정보 사용을 방지합니다.')
    allowed = bool(plan and plan['can_fetch'] and confirm and
                   not invalid_dates and (not extract or backend in connected))
    if st.button('선택한 단계 실행', disabled=not allowed, type='primary', key='refresh_run'):
        with st.status('신규 리포트 처리 중', expanded=True) as status_box:
            event_log = st.empty()
            latest_lines = []
            def progress(stage, message):
                latest_lines.append(f'[{stage}] {message}')
                event_log.code('\n'.join(latest_lines[-18:]), language='text')
            try:
                msg = eng.refresh_collection_to(
                    PROJECT, until, limit=int(limit), max_cost=float(cost),
                    max_tokens=int(max_tokens), download_only=not extract,
                    progress=progress, backend=backend if extract else 'codex')
                if extract and auto_portfolio:
                    progress('포트폴리오', '시점별 데이터 갱신 · PAIR 추론 · REPORT 결합')
                    new_result = eng.portfolio_for_buy_date(
                        PROJECT, buy_for_refresh, pair_share=pair, report_share=report,
                        K=int(k), seed=int(seed), threads=int(threads), fetch=fetch,
                        agent='local')
                    st.session_state['kr_report_portfolio'] = new_result
                    if explain_on_refresh != 'local':
                        progress('설명 에이전트', '수치 계산 완료 · 설명과 독립 검증 호출 중')
                        new_result = eng.regenerate_portfolio_explanation(
                            new_result, explain_on_refresh,
                            progress=lambda msg: progress('검증', msg))
                        st.session_state['kr_report_portfolio'] = new_result
                    st.session_state['refresh_portfolio_buy'] = str(new_result['buy_date'])
                    msg += f" · 포트폴리오 생성 완료: {new_result['path']}"
                status_box.update(label='리포트 처리 완료', state='complete', expanded=False)
                st.session_state['collection_notice'] = msg
                get_llm_status.clear()
                st.rerun()
            except Exception as exc:
                status_box.update(label='수집·구조화·포트폴리오 단계 오류', state='error', expanded=True)
                st.error(str(exc))
                st.caption('이미 받은 PDF와 추출 결과는 로컬에 남습니다. 완료 건은 재실행 시 건너뛰며 '
                           '검증되지 않은 부분 수집 결과는 컨센서스로 반영하지 않습니다.')

    # A successful one-click refresh also shows the result in this tab.
    latest_buy = st.session_state.get('refresh_portfolio_buy')
    latest_port = st.session_state.get('kr_report_portfolio')
    if latest_buy and latest_port and str(latest_port.get('buy_date')) == latest_buy:
        st.divider()
        st.subheader(f'리포트 반영 포트폴리오 · 매수일 {latest_buy}')
        st.caption('직전 거래일 종가 신호 → 선택한 매수일 시가 신규 1슬리브 목표비중. '
                   '선택한 LLM은 근거 구조화 담당, 투자비중은 STABLE + BL/CVaR 엔진이 계산합니다.')
        refresh_held = st.checkbox('실제 편입 종목만 보기 (최종 비중 0% 제외)', value=True,
                                   key='refresh_holdings_only')
        st.dataframe(pd.DataFrame(eng.display_portfolio_rows(
            latest_port['comparison'], held_only=refresh_held)),
            hide_index=True, use_container_width=True)
        st.caption('백분율은 소수점 둘째 자리 표시이며 원본 CSV는 계산 정밀도를 유지합니다.')
        port_df = pd.DataFrame(latest_port['comparison']).sort_values('after_weight', ascending=False)
        st.download_button('리포트 반영 포트폴리오 CSV',
                           data=port_df.to_csv(index=False).encode('utf-8-sig'),
                           file_name=f'report_portfolio_{latest_buy}.csv', mime='text/csv')
        if latest_port.get('agent_warning'):
            st.warning(latest_port['agent_warning'])
        with st.expander('투자비중 변화 및 위험 설명'):
            st.caption('해설 생성: '+display_agent(latest_port.get('agent_used', 'local')))
            items = latest_port.get('analysis_facts', {}).get('holdings', [])
            if items:
                st.dataframe(pd.DataFrame([{
                    '기업': x['company'], '원래 순위': x['rank_before'],
                    '최종 순위': x['rank_after'], '최종 비중': x['weight_after_pct'],
                    '추월': x['passed_peers_count'],
                    '리포트': '있음' if x['report_available'] else '없음'
                } for x in items]), hide_index=True, use_container_width=True)
            verification = latest_port.get('verification', {})
            st.caption('설명 검증 상태: ' + verification.get('status', '알 수 없음'))
            st.markdown(latest_port['explanation'])
