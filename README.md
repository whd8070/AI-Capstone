# 개미구조대 — 성향 기반 AI 포트폴리오 수식 제안

> 아주대학교 AI 캡스톤디자인 1팀 · 2026-11-17 MVP 제출 · 문의: whd8070@ajou.ac.kr

**교수 평가 일정:** MVP 평가 2026-11-19(목), **최종평가 2026-12-09(수)** (당일 기본 브랜치 기준). [최종 SPEC](docs/SPEC.md) · [Evals 설계](evals/EVAL_DESIGN.md) · [실행 결과](evals/results/) · [최종 제출 안내](docs/FINAL_SUBMISSION.md)

## 1. 서비스와 최종 MVP

투자 수식을 모르는 사용자도 **4개 성향 질문과 선택적 추가 요청**을 입력하면 Claude 에이전트로부터 MOM·PAIR·REPORT의 **종목 순위 결합식**과 설명을 제안받을 수 있습니다. 코드가 수식 문법·신호 영향을 검사하고, 문제점이 있으면 최대 3회 재제안을 요청합니다. Claude를 사용할 수 없으면 규칙 기반 제안을 선택할 수 있습니다. **사용자가 수식을 검사·확정한 뒤** 포트폴리오와 백테스트에 적용합니다.

| 신호 | 의미 |
|---|---|
| **MOM** | 최근 20거래일 가격 모멘텀의 종목별 순위 |
| **PAIR** | STABLE 확산모델의 동일 초기 노이즈에서 생성한 Full−Macro 차분 신호의 순위 |
| **REPORT** | 투자 시점에 확인 가능한 증권사 목표주가·당시 종가 괴리율의 상대 순위 |

기본 결합식: `0.5*(0.5*mom + 0.5*pair) + 0.5*report` (MOM 25%, PAIR 25%, REPORT 50%). **수식은 투자 비중이 아니라 종목 순위 점수**를 생성하며, 목표 비중은 기존 위험 최적화 코드가 계산합니다. 한국 44종목, 20거래일 생성 경로, 20슬리브 구조를 사용합니다. 실거래·자동 주문 기능은 없습니다.

| 웹 탭 | 기능 |
|---|---|
| **① 기간 백테스트** | 선택 수식에 따른 NAV·Sharpe·MDD·변동성·종목 비중/순위 비교 |
| **② 특정 매수일 포트폴리오** | 신규 1개 슬리브 목표 비중·순위·리포트 근거·시나리오, 로컬/AI 설명 |
| **③ 리포트 신규 수집 (선택)** | PDF 수집, Claude/Codex 구조화·검증, 컨센서스 갱신 |
| **④ 결합 수식 제안 (성향 조사)** | 4문항·추가 메모 → AI/규칙 수식 제안 → 진단·수정·확정 → ①·② 적용 |

## 2. 설치·실행·업데이트

**환경:** Windows 11(64비트 권장) 또는 macOS, Python 3.11(설치 스크립트 지원), 인터넷 연결. 로컬 Streamlit을 CPU로 실행하며 기본 웹 사용에 GPU·Jupyter·Node.js는 필요하지 않습니다. 접속 주소는 **http://127.0.0.1:8501**입니다.

### Windows 11 (PowerShell)

최초 설치와 실행:

```powershell
$bootstrap = Join-Path $env:TEMP 'AI-Capstone-bootstrap.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/whd8070/AI-Capstone/main/bootstrap_windows.ps1' -OutFile $bootstrap
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootstrap
```

기존 설치에서는 실행 중인 웹을 `Ctrl+C`로 종료한 다음 업데이트하고 실행합니다.

```powershell
cd "$HOME\AI-Capstone"    # 다른 경로에 복제했다면 해당 경로 사용
git status                 # 로컬 수정사항 확인
git branch --show-current  # main 브랜치인지 확인
git pull --ff-only origin main
.\run_windows.cmd
```

### macOS (Terminal)

최초 설치와 실행:

```bash
curl -fL https://raw.githubusercontent.com/whd8070/AI-Capstone/main/bootstrap_mac.sh -o /tmp/ai-capstone-bootstrap-mac.sh
bash /tmp/ai-capstone-bootstrap-mac.sh
```

기존 설치 업데이트 및 실행:

```bash
cd "$HOME/AI-Capstone"
git status
git branch --show-current  # main 브랜치인지 확인
git pull --ff-only origin main
bash ./run_mac.sh
```

**주의:** `run_windows.cmd`/`run_mac.sh`는 Git 업데이트를 자동으로 수행하지 않습니다. pull 충돌 시 로컬 변경사항을 보존하고 해결하세요(`git reset --hard` 사용 금지). 의존성 재설정이 필요할 때만 Windows `start_windows.cmd` 또는 macOS `bash ./start_mac.sh`를 사용합니다. macOS 설치 스크립트는 제공하지만 전체 백테스트의 실기기 검증은 별도 확인이 필요합니다.

### 최종평가: 로컬 요청 추적 (LLMOps)

수식 제안(에이전트/규칙), 검사·적용·복원, 포트폴리오 계산, AI 설명·검증, 리포트 처리, 백테스트 실행 요청을 저장소 루트의 `logs/trace.jsonl`에 한 요청당 한 JSON 레코드로 누적합니다. 백테스트는 워커가 완료/실패 때 기록합니다. 강제 종료된 프로세스에는 완료 기록이 남지 않을 수 있습니다. 로그는 제품의 계산 및 판정을 변경하지 않습니다.

기본 모드는 자유 텍스트(추가 메모·설명·오류 메시지 등)를 생략합니다. **실제 개인정보·인증 정보를 입력하지 않는 팀원 평가 시연에만** 다음 설정으로 텍스트 기록을 활성화하십시오. 패턴 마스킹은 이름 등 모든 개인정보의 자동 제거를 보장하지 않습니다.

Windows PowerShell (실행 중 웹을 먼저 종료):

```powershell
cd "$HOME\AI-Capstone" # 실제 복제 위치로 변경
git pull --ff-only origin main
$env:AI_CAPSTONE_TRACE_TEXT = '1'
.\run_windows.cmd
```

macOS: `AI_CAPSTONE_TRACE_TEXT=1 bash ./run_mac.sh`. 시연 후 PowerShell에서 `Remove-Item Env:AI_CAPSTONE_TRACE_TEXT`로 설정을 해제합니다.

시연 후 PowerShell에서 `Get-Content .\logs\trace.jsonl -Tail 5 -Encoding UTF8`로 최근 기록을 확인할 수 있습니다. 로그는 기본적으로 Git에서 제외합니다. 공개 저장소 제출 시 팀원이 직접 개인정보·비밀·로컬 경로·권한 없는 원문을 확인하고 정제한 실제 기록만 명시적으로 `git add -f logs/trace.jsonl` 하십시오. 임의의 로그·측정값은 생성하지 않습니다. CLI 기본 모델의 실제 고정 버전을 확인할 수 없는 경우 설정 식별자만 남깁니다. 모델 고정 및 공격 Evals·기준점·개선 회차는 별도 수행합니다.

## 3. 평가자용 대표 시연 (④ → ② → ①)

| 단계 | 입력·실행 예시 | 기대 결과 | AC |
|---|---|---|---|
| **④ 성향 제안** | 네 질문 선택, 예: REPORT 신뢰도 **낮음**, 추가 요청 작성 → **에이전트에게 제안받기** | 제안 수식·설명·진단·시도 기록, 불일치 시 경고 | AC-12a, AC-12b |
| **④ 확정** | 수식을 검사한 뒤 **이 수식을 백테스트·포트폴리오에 적용** | 확정된 수식을 이후 ①·②에서 사용 | AC-10c, AC-12c |
| **② 포트폴리오** | 매수일 **2026-11-05**, **데이터 기반 로컬 해설** → **포트폴리오 생성 (수치 먼저 표시)** | 종목 순위·신규 슬리브 목표 비중·근거·20거래일 시나리오 | AC-04a, AC-05a, AC-12c |
| **① 백테스트** | 시작 신호일 **2026-10-27**~종료 평가일 **2026-11-04** → **백테스트 실행 (별도 프로세스)** | 완료 후 NAV·Sharpe·MDD·변동성·거래비용·날짜별 CSV | AC-12c |
| **④ 금지 입력** | 수식에 `__import__('os').system('calc')` 입력 → 검사/적용 | 코드 실행 없이 오류·미적용 | AC-10c |

**Claude를 연결하지 않은 환경:** ④에서 **규칙으로만 만들기 (LLM 없음)**를 선택해 수식 검사·확정·적용을 체험할 수 있습니다. 실제 Claude 제안은 로컬 Claude Code CLI 설치·로그인이 필요합니다. ②의 로컬 설명은 AI 계정이 필요 없습니다.

**빠른 점검:** ①의 **처음 5개 신호만 점검 (정식 백테스트 아님)**으로 동작을 먼저 확인하고, 실제 기간 평가를 위해서는 해당 옵션을 해제하세요. 캐시가 없는 날짜에서는 외부 시세 수집·CPU 모델 추론이 추가되어 시간이 늘어날 수 있습니다.

### 선택 기능

- **AI 설명·검증:** ②에서 포트폴리오 수치를 만든 뒤 **AI 설명 생성·독립 검증 (모델 추론 재실행 없음)**을 실행합니다(Claude/Codex CLI 로그인 필요). 선정 이유·리포트 근거·비중 결정·위험관리·불확실성의 5영역과 검증 상태를 보여주며, 실패하면 로컬 설명으로 대체합니다.
- **새 리포트 반영:** ③에서 **PDF 다운로드 + 선택한 LLM 구조화 + 컨센서스 반영**을 완료한 다음 ②에서 재계산합니다. **PDF만 다운로드**하면 REPORT 점수는 갱신되지 않습니다. 기본 리포트 컨센서스는 2026-11-04까지의 자료를 포함합니다.

**해석 제한:** 매수일 당일·미래의 리포트는 사용하지 않습니다. 유효 리포트가 부족하면 REPORT 계산이 중단될 수 있습니다. ②의 목표 비중은 **새로 편입하는 1개 슬리브 내부 비중**으로 전체 20슬리브 계좌의 비중은 아닙니다. 리포트 목표주가·생성 시나리오·백테스트 수익은 실현 수익을 보장하지 않습니다.

## 4. 교수 평가 제출 산출물

| 평가 항목 | 제출 위치 | 확인할 내용 |
|---|---|---|
| **MVP 구현·실행** | [SPEC](docs/SPEC.md), 본 README, [웹 구현](src/diffusion/kr_report_web.py) | 최종 범위·AC, 설치·실행, 입력과 기대 결과 |
| **결정적 검증** | [골든 YAML](tests/harness/golden_cases.yaml), [설명 하니스](tests/test_verification_golden.py), [수식 하니스](tests/test_formula_golden.py) | 설명 12건 + 수식 제안 14건 |
| **결함 주입** | [설명 기록](docs/prompts/delegation_verification_golden.md), [수식 기록](docs/prompts/delegation_formula_golden.md), [러너 변이 테스트](tests/test_evals_runner_mutation.py) | 의도적 오류의 검출·복원 |
| **Evals 설계·데이터** | [설계서](evals/EVAL_DESIGN.md), [설명 36건](evals/evalset.jsonl), [수식 24건](evals/formula_evalset.jsonl) | AC별 지표·계산 방법·합격선·범주 |
| **Evals 실행 결과** | [설명 러너](evals/run_evals.py), [수식 러너](evals/run_formula_evals.py), [결과 JSON·이력 CSV](evals/results/) | 케이스별 실제 출력·판정 및 실행 이력 |
| **에이전트 역할·근거** | [AGENTS](AGENTS.md), [문제 정의](docs/PROBLEM.md), [온톨로지](docs/ontology.yaml) | 책임·경계·근거 추적 |

**검증된 기준 실행:** [GitHub Actions #44023933245](https://github.com/whd8070/AI-Capstone/actions/runs/44023933245)에서 평가 소스 `9f194165`, 결과 저장 커밋 `edce0d3`. pytest **32/32**, 수식 제안 Evals **24/24**, 설명 검증 Evals **36/36** 통과. [설명 이력](evals/results/history.csv)·[수식 이력](evals/results/formula_history.csv)에 실행 결과가 저장되어 있습니다. 이후 실행은 결과 JSON의 소스 커밋과 이력으로 추적합니다.

**측정 범위:** Evals는 **모의 LLM 응답을 통한 결정적 안전성·회귀 검사**입니다. 실제 Claude/Codex 금융 사실 판단의 정확도나 브라우저 E2E 통과를 의미하지 않습니다.

### 선택: 로컬 재현 명령

```bash
python -m pip install -r evals/requirements-evals.txt
python -m pip install numpy pandas
(cd src/diffusion && python -m unittest -v test_kr_formula test_kr_formula_agent)
python -m pytest -q tests/test_verification_golden.py tests/test_formula_golden.py tests/test_evals_runner_mutation.py
python evals/run_formula_evals.py
python evals/run_evals.py --change "manual reproduction" --golden "26 golden cases"
```

위 검증은 [GitHub Actions](https://github.com/whd8070/AI-Capstone/actions)에서도 자동 실행됩니다. 실제 Claude 제안·시세 조회 등 환경 의존 동작은 웹에서 별도 확인할 수 있습니다.
