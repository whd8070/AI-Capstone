# 한국 주식 MOM + PAIR + REPORT 로컬 웹

이 폴더의 기존 `kr_pair_cpu.py`, `kr_pair_core.py`, `KR_MOM_PAIR_20_SLEEVES_CPU.ipynb`에 REPORT 순위 신호를 추가한 **로컬 Streamlit 실험용 대시보드**입니다. 자동 주문 기능은 없습니다.

> 처음 복제했다면 저장소 [루트 README](../../README.md)의 **Windows / macOS 빠른 시작**을 먼저 따르세요. Windows는 PowerShell 스크립트, macOS는 터미널 명령을 사용합니다.

## 1. 필수 파일과 설치

- 지원 설치 안내: Windows 11(PowerShell), macOS(Intel / Apple Silicon, 터미널) / Python **3.11 (64비트)**. 실제 전체 백테스트 검증은 환경별로 필요합니다.
- 학습된 한국 STABLE 체크포인트: `src/diffusion/checkpoints/kr/stable_best.pt` (`git clone` 후 파일 존재 여부 확인). 임의의 다른 모델이나 무작위 체크포인트로 대체하지 마세요.
- 컨센서스: `agents/collection/data/handoff/daily_consensus.csv`.
- 설명 근거: `agents/collection/data/handoff/reports_compact.jsonl`.
- 최초 실행 또는 최근 날짜 확장 시 Yahoo Finance/FRED 인터넷 접속이 필요합니다.

```powershell
# 저장소 루트에서
cd src\diffusion
.\setup_windows.ps1
.\run_web.ps1
```

PowerShell의 스크립트 실행 제한이 있다면 스크립트 대신 아래의 직접 실행 방법을 사용하세요.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements_kr_report_web.txt
.\.venv\Scripts\python.exe -m unittest test_kr_pair_cpu test_kr_report_engine test_kr_report_status -v
.\.venv\Scripts\python.exe -m streamlit run kr_report_web.py --server.address 127.0.0.1 --server.port 8501
```

macOS에서는 터미널을 열고 아래와 같이 실행합니다. Python 3.11이 없으면 [Homebrew](https://brew.sh/)를 설치한 후 `brew install python@3.11`을 실행하세요.

```bash
# 저장소 루트에서 시작하는 경우
cd src/diffusion

python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements_kr_report_web.txt
python -m ipykernel install --user --name ai-capstone-kr --display-name "AI-Capstone KR (.venv)"
python -m unittest test_kr_pair_cpu test_kr_report_engine test_kr_report_status -v
python -m streamlit run kr_report_web.py --server.address 127.0.0.1 --server.port 8501
```

Mac에서 다시 실행할 때는 `source .venv/bin/activate` 후 마지막 Streamlit 명령만 사용합니다. CPU 추론이므로 MPS/CUDA는 필수 아님에 유의하세요. Mac의 실제 모델 추론 및 원격 데이터 수집 성공 여부는 환경에서 확인해야 합니다.

`http://127.0.0.1:8501`을 브라우저에서 엽니다. Streamlit은 Python 앱으로, 별도의 프런트엔드 컴파일이나 Node.js 빌드가 필요하지 않습니다. 종료할 때는 실행 터미널에서 `Ctrl+C`를 누르세요. VS Code 노트북을 사용한다면 커널 `AI-Capstone KR (.venv)`를 선택합니다.

## 2. 두 가지 핵심 기능

**백테스트:** REPORT 데이터가 있는 기간에서 시작·종료일, PAIR 비율 `p`, REPORT 비율 `r`을 선택합니다. 매 거래일 **종가 신호 → 다음 거래일 시가에 신규 슬리브 1개**를 체결하며 총 **20슬리브를 순환**합니다. REPORT 적용 전·후 NAV 그래프, Sharpe, MDD, 연환산 수익률/변동성, 거래비용, 일별 비중·순위 CSV를 보여 줍니다. 계산은 별도 프로세스에서 실행되며 웹을 닫아도 작업 프로세스는 지속될 수 있습니다.

**특정 매수일 포트폴리오:** 날짜를 **매수일**로 입력하면 직전 KRX 거래일 종가까지 확인된 시세를 확보하고 확산모델을 실행해 해당 매수일 **신규 1개 슬리브의 목표 비중**을 계산합니다. REPORT 적용 전·후 종목별 비중·순위 차이, 목표가 괴리율, 근거/리스크, 20거래일 생성 시나리오를 제공합니다. 전체 20슬리브 계좌의 현재 보유 비중과는 다릅니다.

웹에서 변경 가능한 비율은 다음과 같습니다.

```text
base  = (1 - p) × rank_z(MOM 20일) + p × rank_z(PAIR F−M)
final = (1 - r) × base + r × rank_z(REPORT 목표가 괴리율)
```

이는 **최종 투자비중을 단순 평균하는 방식이 아니라**, 순위 신호를 결합하고 기존 O 경로 공분산 및 BL/CVaR 위험 최적화에 입력하는 방식입니다. **웹의 K=128, 시드=0은 고정**입니다.

## 3. 정보 시점과 데이터

- REPORT: `daily_consensus.csv`의 종목별 최신 `tp_median`과 **신호일 비수정 종가**로 `(목표가/종가) - 1`을 산출해 횡단면 순위화합니다. **매수일 당일 리포트는 제외**하고, 최장 90일 이전의 최신 유효 리포트만 사용합니다.
- 리포트 없는 종목은 유효 종목들의 중앙값으로 중립 처리합니다. 유효 REPORT 종목이 두 개 미만이면 REPORT 비율이 0보다 큰 계산을 중단합니다.
- 리포트 파일의 기본 수록 기간은 **2025-11-04 ~ 2026-11-04**입니다. 신규 리포트 수집은 **선택** 기능이며, 네이버 PDF 다운로드 및 `claude` CLI 구조화가 별도로 필요할 수 있습니다. 과거에 없던 보고서를 임의 생성하지 않습니다.
- 최신 날짜 시장 데이터는 `yfinance` 및 FRED에서 수집합니다. 수정 종가(모델/평가)와 비수정 종가(목표가 괴리율), 조정 시가(체결)를 구분합니다.
- 보고서 발행 시각이 없는 한계 때문에, 당일 보고서를 사용하지 않는 보수적인 정렬을 적용합니다.

## 4. 결과·캐시 및 재실행

- `results/kr_report_dashboard/`: 작업별 설정, 진행 상태 JSONL, 오류 로그, NAV·랭크·비중·설명 출력 (Git 추적 제외).
- `results/kr_pair_cpu/scenarios/`: 기존 O/F/M 시나리오 캐시 (재사용).
- `data/kr/live_cache/`: 다운로드한 시세 및 피처 (재사용, Git 추적 제외).
- Windows의 `WinError 5` 회피를 위해 진행 상태는 `status_updates.jsonl`에 **append-only**로 기록합니다. 별도 프로세스에서 재실행하되, 동일 작업의 이력을 읽어도 기본 캐시를 지우지 않습니다.
- 두 개의 백테스트를 동시에 실행하면 캐시 경쟁이 있을 수 있으므로 작업 관리자가 동시 실행을 제한합니다.

## 5. 테스트·문제 해결

Windows PowerShell:

```powershell
cd src\diffusion
.\.venv\Scripts\python.exe -m unittest test_kr_pair_cpu test_kr_report_engine test_kr_report_status -v
```

macOS 터미널 (`src/diffusion` 위치):

```bash
source .venv/bin/activate
python -m unittest test_kr_pair_cpu test_kr_report_engine test_kr_report_status -v
```

- `ModuleNotFoundError`: 설치에 사용한 `.venv\Scripts\python.exe`로 Streamlit을 실행했는지 확인하세요.
- `stable_best.pt` 없음: `checkpoints/kr/`에 **한국 모델 체크포인트**가 있는지 확인하세요.
- `WinError 5`: 구형 파일이 아닌 Git 최신 `kr_report_job.py`/`kr_report_jobs.py`를 사용하고, 기존 서버·백테스트 프로세스를 종료한 뒤 재실행하세요.
- 시세 다운로드 실패: Yahoo/FRED 연결 및 거래일 시세 제공 여부를 확인하세요. 결측치는 임의의 가격으로 대체하지 않습니다.
- `use_container_width` 경고: Streamlit API의 폐기 경고이며 기능 실패를 의미하지 않습니다.
- 선택적 설명 에이전트: 로컬 기본 설명은 추가 비용이 없지만, `Claude` 모드/신규 PDF 구조화에는 Claude CLI 로그인·설정·사용량이 필요합니다.

## 6. 제한

- 본 전략은 2025-03-31 기준 **고정 44종목**을 이용하므로 생존편향 가능성이 있습니다.
- 일별 컨센서스는 리포트 발행일에 재계산되므로, 리포트가 없는 중간 날짜의 개별 브로커 만료가 엄밀한 일별 재집계와 다를 수 있습니다.
- 리포트 목표가의 기간(보통 6~12개월)과 모델 예측 기간(20거래일)은 다릅니다.
- 수수료는 고려하지만 슬리피지/세금/거래정지 등을 완전히 반영하지 않습니다.
- 위험 최적화 또는 생성 시나리오가 실현 성과를 보장하지 않습니다. 백테스트는 연구용 검증이며 투자 조언·자동 주문이 아닙니다.

더 자세한 기존 MOM+PAIR 구조는 [README_KR_PAIR_CPU.md](README_KR_PAIR_CPU.md)를 참고하세요.
