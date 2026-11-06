# KR STABLE MOM+PAIR 5:5 — 첫 실행 자동 다운로드 + CPU 전용

**이전 배포판과 달리, 원시 데이터 CSV/전처리 NPY는 준비할 필요가 없습니다.** 학습에 사용한 한국 STABLE 모델 `stable_best.pt`만 지정된 곳에 넣으면 됩니다. 첫 인퍼런스 또는 백테스트 실행 시 코드가 과거 시세, 한국 지수, 미국 금융 지표 및 FRED 금리 스프레드를 자동으로 다운로드하고, 과거 값만으로 Kalman β 및 시점별 조건 피처를 부트스트랩합니다.

최초 다운로드 이후에는 다운로드/피처/시나리오/결과물을 별도 폴더에 남깁니다. **인터넷이 없거나 시세 제공처에서 데이터를 주지 않으면 오류로 중단**하며, 부정확한 데이터를 임의로 생성하지 않습니다.

## 1. 설치 파일 구성 (7개)

```text
diffusion/
├── kr_pair_cpu.py                       # CLI: 인퍼런스와 백테스트
├── kr_pair_bootstrap.py                 # 신규: 빈 프로젝트 자동 다운로드
├── kr_pair_core.py                      # STABLE/DDIM/PAIR/위험 최적화
├── KR_MOM_PAIR_20_SLEEVES_CPU.ipynb    # 시가 체결 20슬리브 백테스트
├── test_kr_pair_cpu.py                  # 모의 데이터로 독립 테스트
├── requirements_kr_pair_cpu.txt        # Python 의존성
├── README_KR_PAIR_CPU.md               # 현재 문서
└── checkpoints/kr/
    └── stable_best.pt                  # ★ 사용자가 가진 한국 학습 모델만 배치
```

`checkpoints/kr/stable_best.pt`는 노트북 `KR_STABLE_02_TRAIN_FIXED(3).ipynb`에서 학습한 **한국 모델** 체크포인트여야 합니다. 미국 모델이나 재학습되지 않은 랜덤 모델로 대체해서는 안 됩니다. 모델이 없으면 데이터를 다운로드하기 **전에** 중단합니다.

## 2. Windows PowerShell (VS Code에서 diffusion 폴더 열기)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements_kr_pair_cpu.txt
python test_kr_pair_cpu.py
```

가상환경 설치는 한 번만. `test_kr_pair_cpu.py`는 무작위 데이터/모의 원격 공급자를 이용하므로 실제 데이터를 다운로드하지 않고, 체크포인트 없이도 실행 가능합니다. CPU 외 장치는 사용하지 않습니다.

장 마감 후(기본 최소 18:00 KST), 해당 날짜 **종가가 원격 제공처에 올라왔을 때만** 신호를 생성합니다.

```powershell
python kr_pair_cpu.py --project . --threads 4 infer --asof "2026-11-02T18:30:00+09:00"
```

- CLI에서 `--project .`는 현재 열린 `diffusion` 프로젝트 폴더를 뜻합니다. 생략해도 현재 폴더가 기본 경로입니다.
- 날짜만 입력하면 18:30 KST로 해석합니다. **지금 시각보다 미래의 타임스탬프는 거부**합니다.
- **첫 실행 때 `--offline`을 사용하지 마세요.** 데이터를 다운로드할 수 없게 됩니다.
- `--K 2`는 모델 확인용 초소형 테스트 옵션이고 실전 기본은 K=128입니다.
- 5:5 결합은 `--blend smooth050`(기본)입니다.

## 3. 첫 실행에서 자동으로 만들어지는 경로

```text
diffusion/
├── data/kr/
│   ├── raw/
│   │   ├── stable_kospi200_44_adj_close.csv    # 과거 종가 자동 생성
│   │   └── macro_raw.csv                        # 5개 매크로 시계열
│   ├── metadata/
│   │   ├── stable_kospi200_44.csv               # 고정 유니버스 기록
│   │   ├── bootstrap_price_audit.csv             # 가격 커버리지 확인
│   │   └── shared_market_session_removed.csv
│   ├── cache_prices/
│   │   ├── 005930_ohlc.csv ... (44종목)         # 다운로드 중단 후 재시도시 재사용
│   │   ├── macro_market_index.csv
│   │   ├── macro_dollar_index.csv
│   │   ├── macro_vix.csv
│   │   ├── macro_gold.csv
│   │   └── fred_T10Y3M.csv
│   └── live_cache/
│       ├── kr_close_live.csv
│       ├── macro_raw_live.csv
│       ├── kr_yahoo_raw_open.csv                # 다음 시가 백테스트용
│       ├── kr_yahoo_raw_close.csv
│       └── features/YYYYMMDD_<digest>.npz      # 요청 날짜 10+13 피처
└── results/kr_pair_cpu/
    ├── signals/YYYYMMDD_s000.json              # 44개 목표 비중
    ├── scenarios/*.npz                          # DDIM 캐시
    └── backtests/<기간>/{nav.csv,trades.csv,daily_weights.csv,metrics.json}
```

### 어디에서 종목 목록을 가져오나?

학습 전처리 노트북 `KR_STABLE_01_PREPROCESS_KRX_20250331(3).ipynb`의 STEP3 실행 결과에 **01/44 ~ 44/44로 출력된 44개 종목 코드**를 소스에 고정했습니다. 따라서 사용자가 KRX ID/PW를 입력하거나 최신 KOSPI200 구성종목을 새로 다운로드할 필요가 없습니다. (최신 종목을 재선정하면 기존 모델의 고정 유니버스와 달라집니다.)

가격은 `yfinance`의 Yahoo Finance `종목.KS`로 **2012-06-01부터 요청 날짜까지** 다운받습니다. 매크로는 ^KS11, DX-Y.NYB, ^VIX, GC=F 및 FRED `T10Y3M`입니다. 한국장 종료 후 미국장 당일 종가가 아직 없으므로 외국 매크로와 FRED는 **KR 거래일 한 세션 지연**해 사용합니다. 종가 수준·수익률은 과거를 참조하고, 미래 20일 레이블은 만들지 않습니다.

학습 유니버스 44종목 중 하나라도 요청한 거래일 데이터가 없으면 **종목 교체·직전 종가 대체 없이 실패**합니다. Yahoo 데이터 수정이나 공급처 장애 때문에 최초 부트스트랩이 실제로 성공하는지는 실데이터 환경에서 점검해야 합니다. 새로 수집한 조정종가가 기존 2025년 학습 시점 조정종가와 같다고 보장할 수 없으므로, 가능하면 원본 NPY와 샘플 비교 검증을 권장합니다.

## 4. CPU 인퍼런스 정의

- 동일 초기 확산 노이즈의 **O(원본), F(전체), M(매크로 전용)** 경로를 CPU DDIM 30-step으로 생성. 기본 K=128.
- **PAIR:** `rank_z(mean(F - M))` (각 경로의 20거래일 누적 단순수익률 차이).
- **MOM:** `rank_z(과거 20거래일 단순수익률)`.
- **5:5:** `v=0.5*MOM + 0.5*PAIR`; O 시나리오 공분산과 기존 BL/CVaR risk repair로 **long-only / 총 100%** 포트폴리오 생성.
- `weights` 및 `weights_pct`를 JSON 파일로 저장. 이것은 목표 비중일 뿐 자동 매매 주문은 아닙니다.

## 5. 20슬리브 다음 거래일 시가 백테스트

Jupyter에서 `KR_MOM_PAIR_20_SLEEVES_CPU.ipynb` 열기 → 커널을 `.venv`로 선택 → 첫 셀 실행. `PROJECT = KIT_DIR`이 기본이며 `RUN_INFER=True` 혹은 `RUN_BACKTEST=True` 설정 뒤 실행합니다. `FETCH_DATA=True`가 기본이라 이전 CSV가 없어도 최초 실행에서 자동으로 다운로드합니다. 첫 검증은 `SMOKE_TEST=True`(K=2, 2일)로 권장합니다.

CLI도 지원합니다.

```powershell
python kr_pair_cpu.py --project . --K 2 --threads 4 backtest --start 2024-10-01 --end 2025-03-31 --sleeves 20 --max-signals 2
python kr_pair_cpu.py --project . --K 128 --threads 4 backtest --start 2024-10-01 --end 2025-03-31 --sleeves 20 --fee-bps-side 20
```

`start` 거래일 종가 → **다음 KRX 거래일 시가**에 하나의 슬리브 1/20을 투자/교체. 각 슬리브는 **20거래일** 보유한 후 순차 교체합니다. 기본 거래 비용은 매수·매도 각각 20bp, 일별 NAV는 조정종가 평가. 초기 20세션은 현금에서 차례로 투입되는 구조입니다.

체결 가격은 동 날짜 **Open/Close × 조정종가**로 환산해 가격 단위를 맞추며, 임의의 시가 대체는 금지합니다. 이 체결 기준은 기존 일부 논문 실험의 *다음 종가 체결*과 달라 직접 비교 시 주의해야 합니다. 세금/슬리피지/거래정지는 별도 모델링되지 않았습니다.

## 6. 운영상 주의

- 처음 다운로드하는 44개 티커 + 5개 매크로의 시세는 원격 속도나 요청 제한을 받습니다. 최초 성공 종목의 `_ohlc.csv`는 유지되어 중단 뒤 다시 실행할 때 재사용할 수 있습니다.
- `--offline`은 모든 raw 캐시를 이미 확보했을 때만 사용하세요.
- 주어진 실행 시간이 18:00 KST 이전이거나 미래이거나, 장이 쉬는 날이거나, 필요한 당일 종가가 없으면 신호를 생성하지 않습니다.
- 추론은 CPU-only지만 기간 전체를 하루마다 30-step K=128로 계산하면 부담이 큽니다. 중간 시나리오를 캐시합니다.
- 2025-03-31 시점에 고정한 과거 구성종목을 모든 날짜에 적용하므로 생존편향 가능성이 있습니다. 실제 종목 변경/상폐/거래정지 시 자동 대체하지 않습니다.
- 당일 데이터 다운로드의 성공은 원격 서비스의 응답에 달려 있습니다. **이 키트의 실제 Yahoo/FRED 네트워크 다운로드는 이 제작 환경에서 실행하지 못했습니다.** 테스트는 mock 공급자와 실제 CPU 추론 smoke 범위입니다.
