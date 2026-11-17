# 최종 제출 안내 — 개미구조대 (2026-11-17)

> **심사 기준 파일:** [README.md](../README.md) · [SPEC.md](../SPEC.md) · [AGENTS.md](../AGENTS.md) · [EVAL_DESIGN.md](../evals/EVAL_DESIGN.md)
>
> 기능 범위는 **현재 구현된 로컬 웹 MVP**로 확정했다. 단위/골든/오프라인 Evals **자동 실행 사실**과 **실제 Claude/Codex의 품질**, **로컬 UI E2E 체험**은 반드시 구분한다.

## A. 평가자가 가장 먼저 체험할 최종 기능

초보 투자자는 수학식을 몰라도 **④ 결합 수식 제안(성향 조사)** 탭에서 네 가지 선호를 선택하고 추가 요청을 적어 Claude가 생성한 수식·설명을 확인할 수 있다. 문법과 신호 영향은 코드에서 검사하고, 문제가 생기면 최대 세 번의 수정 시도를 거쳐 제안한다. 사용할 수식이 없거나 CLI 인증에 실패하면 규칙 기반 제안을 사용할 수 있다. 최종 선택은 이용자가 직접 확정한다.

1. [README 설치 안내](../README.md#2-설치-및-접속)대로 Windows `run_windows.cmd` 또는 macOS `bash ./run_mac.sh`를 실행한다.
2. 웹 `http://127.0.0.1:8501`에서 **④ 성향 조사**를 열고 네 질문을 선택한다. **에이전트에게 제안받기**(Claude CLI 로그인 필요) 또는 **규칙으로만 만들기(LLM 없음)**를 클릭한다.
3. 제안된 수식, 성향 일치 경고, 기본 수식 대비 신호 영향 및 순위 유사도, 최대 3회 시도 기록을 확인한다.
4. **이 수식을 백테스트·포트폴리오에 적용**을 누른다. 수식이 사용 불가하면 오류가 표시되고 적용되지 않는다.
5. **② 특정 매수일 포트폴리오**에서 **2026-11-05**를 선택해 새 슬리브 비중과 리포트 반영 전후 종목 순위를 확인한다.
6. **① 기간 백테스트**에서 동일 수식을 적용하여 NAV·Sharpe·MDD·변동성·비중 및 순위 CSV를 확인한다. 최초 실행에서는 5개 신호만 점검한 뒤 정식 기간 평가를 수행한다.
7. 선택 기능 **③ 리포트 신규 수집**은 기본 수록 자료가 부족할 때만 사용한다. **②의 AI 설명·독립 검증**도 원하면 로그인된 Claude/Codex CLI로 선택해 실행한다.

**중요한 제한:** 모델의 20거래일 시나리오나 리포트 목표가 괴리율은 실현 수익 보장이 아니다. 조회한 한 날짜의 비중은 **새로 사는 1개 슬리브의 내부 비중**이지 전체 20슬리브 자산의 현재 비중이 아니다. 금융 조언이나 실제 주문 기능은 없다.

## B. 최종 MVP AC와 현재 제출 증거

| AC | 제출 기능 | 검증 근거 |
|---|---|---|
| **AC-12a / AC-12b** | 초보 투자자의 성향·추가 요청 → 수식/설명 제안 → 검사·최대 3회 수정·규칙 기반 대체 | `src/diffusion/test_kr_formula_agent.py` 및 코드 |
| **AC-12c** | 사용자 수정·확정 수식을 ① 백테스트와 ② 포트폴리오에 적용 | `src/diffusion/kr_report_web.py` UI 연결, 사용자 E2E 필요 |
| **AC-10a / AC-10c** | 기본 수식 호환·허용 연산 검사·악성 입력 차단 | `src/diffusion/test_kr_formula.py` |
| **AC-06a / AC-07d / AC-07g** | 설명 필수 항목·검증 실패·미검증 게시 차단 | `tests/harness/golden_cases.yaml`(12건) + `evals/evalset.jsonl`(36건) + `evals/results/` |
| **AC-02d / AC-04a / AC-05a** | 리포트 결측·시점·기존 비중 계산 경로의 일부 수용 조건 | `src/diffusion/test_kr_report_engine.py` 및 `test_kr_pair_cpu.py`; 전체 계약 검증으로 과장하지 않음 |

현재 Evals v1은 모의 검증기 판정을 실제 `verify()` 게시 게이트에 주입하는 **36개 결정적 사례**다. **실제 Claude/Codex의 금융 주장 판별 정확도를 측정한 시험이 아니다**. 별도 P30/M30/G30은 정의된 목표이나 실측 통과 결과가 없는 경우 PASS로 기재하지 않는다.

## C. 평가 파일과 자동 실행

| 경로 | 용도 |
|---|---|
| `SPEC.md` | 최종 MVP 제품·AC·시나리오 정본 |
| `README.md` | 설치·실사용 시나리오·입력/출력 |
| `AGENTS.md` | 각 AI 에이전트/결정적 코드 책임과 금지 행동 |
| `docs/PROBLEM.md` | 문제·대상 사용자·관찰 근거·검증 가설 |
| `docs/ontology.yaml` | SUR/LOG 근거와 도메인 관계 |
| `tests/harness/golden_cases.yaml` | 정상/경계/금지 골든 정답 |
| `tests/test_verification_golden.py` | 골든 테스트 하니스 |
| `tests/test_evals_runner_mutation.py` | 오답 주입 시 실패 검출 |
| `evals/EVAL_DESIGN.md` | 지표·합격선·모의 vs 실제 구분 |
| `evals/evalset.jsonl` | 36개 평가 사례 (AC 연결) |
| `evals/run_evals.py` | 실제 함수 호출·채점·개별 결과/집계 저장 |
| `evals/results/history.csv` | 실행별 변경·데이터셋 버전·통과율 |
| `.github/workflows/evals-ci.yml` | 수식/검증 코드 변경 시 자동 회귀 및 Evals 실행 |

Windows Python 3.11 로컬에서 재현하고 싶다면 저장소 루트 기준:

```powershell
$py = ".\src\diffusion\.venv\Scripts\python.exe"
Push-Location src/diffusion
& .\.venv\Scripts\python.exe -m unittest -v test_kr_formula test_kr_formula_agent
Pop-Location
& $py -m pip install -r evals/requirements-evals.txt
& $py -m pytest -q tests/test_verification_golden.py tests/test_evals_runner_mutation.py
& $py evals/run_evals.py --change "local reviewer reproduction" --golden "local tests"
```

**명령 실행은 필수가 아니다.** CI의 현재 결과를 확인하면 된다. 로그인된 Claude로 수식 제안을 실제로 체험하는 것은 **브라우저 UI**에서 진행한다.

## D. 제출 기준일과 결과 상태

- 교수 평가 기준은 **2026-11-18 저장소 `main`**이다. 버전 범위는 기존 기능을 새로 개발하는 것이 아니라 **구현된 네 탭으로 확정**했다.
- 기존 CI 기록에는 수식 문법/에이전트 루프 단위 검사, 골든, Evals가 포함되어 있다. 최신 워크플로 성공 여부는 [Actions](https://github.com/whd8070/AI-Capstone/actions)에서 확인한다.
- **실제 CLI E2E, 실사용자 품질, 의미 검증 정확도는 자동 테스트가 아니라 별도 관찰·라벨링 영역**이며, 실행하지 않은 항목의 성공 사례를 만들어내지 않는다.

## E. 팀 제출 점검

1. 팀원이 각 AC의 기대값·합격선 및 실제 기능 범위가 코드와 맞는지 리뷰한다.
2. 초기 로컬 실행에서 체크포인트와 데이터가 실제 파일인지 확인한다(다운로드 실패 또는 Git LFS 포인터로 인한 장애 주의).
3. ④ 성향·추가 메모 → 제안 수식 → 검사 → 적용 → ② 포트폴리오 → ① 백테스트를 브라우저에서 한 번 검증한다.
4. 현재 `main`의 CI 성공 기록과 `evals/results/history.csv`의 결과를 대조한다.
5. 자료의 민감정보·원문 저작권·계정 토큰이 공개 저장소에 포함되지 않았는지 확인한다.

사용자 데모 실패·실제 CLI 미로그인·Evals 실측 미실시 사실은 명확히 기록한다. **최종 기능 범위 확정은 모든 환경의 실행 성공이나 모델 투자 성과 인증이 아니다.**
