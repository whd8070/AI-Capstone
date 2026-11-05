# agents/collection — 증권사 리포트 수집·구조화

`universe.json`의 44개 대상 기업에 대해 네이버 증권 '종목분석 리포트' 1년치를 수집하고,
LLM(Claude haiku)으로 목표가·근거를 구조화해 팀원이 바로 쓸 수 있는 데이터로 만든 결과물입니다.

## 바로 쓸 데이터: `data/handoff/forecasts.jsonl` (또는 `forecasts.csv`)

리포트 1건 = 1행. 형식: `{리포트 날짜, 기업, 전망 시점, 전망 가격, 근거}` + 추적용 필드.

```json
{"report_date": "2026-09-14", "stock_code": "105560", "company": "KB금융",
 "target_date": "2027-09-14", "horizon_months": 12, "horizon_assumed": false,
 "target_price": 235000.0, "target_price_source": "naver",
 "rationale": ["3분기 순익 QoQ·YoY 증가 전망, 역대 최대 분기 순익 경신 예상", "..."],
 "broker": "하나증권", "opinion": "buy", "nid": "96136"}
```

| 필드 | 의미 |
|---|---|
| `report_date` | 리포트 공개일 |
| `company`, `stock_code` | 기업 |
| `target_date` | 전망 시점 = `report_date` + `horizon_months` |
| `horizon_months` / `horizon_assumed` | 목표가 기간. 리포트에 없으면 12개월로 가정하고 `horizon_assumed=true` |
| `target_price` | 전망 가격(원). 기준은 네이버 API 값 |
| `target_price_source` | `naver` 또는 `report_text`(네이버 값이 본문과 달라 본문 값으로 교정한 경우) |
| `rationale` | 투자 근거 요약. 원문 인용이 코드로 검증된 근거만 포함 |
| `broker`, `opinion`, `nid` | 증권사, 투자의견(buy/hold/sell/none), 리포트 ID(같은 날 여러 건 구분·원문 추적용) |

- 기간: 2025-11-04 ~ 2026-11-04 / 2,026행(목표가 있는 리포트) / 43개 기업
- **한미반도체(042700)는 최근 1년 네이버 리포트가 없어 데이터 없음**
- 목표가 기간: 12개월 1,853건, 6개월 173건 (그중 1,387건은 기간 미기재 → 12개월 가정)
- 근거 인용 검증 통과율 99.8%. 검증된 근거가 하나도 없는 37행은 `rationale`이 빈 배열

### 사용 시 주의 (시점 정합성)
- 날짜에 시각 정보가 없으므로 **T일 리포트는 T일 장 마감 이후에 알게 된 정보**로 취급한다.
- 어떤 날짜의 피처도 그 날짜 이후 리포트를 쓰면 안 된다.
- 리포트가 없는 날은 행이 없다. 일별 시계열은 직전 값으로 forward fill만 하고 뒤로 채우지 않는다.

## 그 밖의 파일 (`data/handoff/`)
- `HANDOFF.md`: 필드·규칙 설명, 기업별 건수, 목표가 교정 목록
- `daily_consensus.csv`: (종목, 날짜)별 컨센서스 피처. 직전 90일 증권사별 최신 리포트 기준(미래 정보 없음)
- `reports_compact.jsonl`: 실적 추정치(`earnings_forecast`), 리스크, 근거 카테고리·페이지까지 담은 상세판

원문 PDF와 원문 인용문은 저작권 문제로 저장소에 올리지 않았습니다(`.gitignore`).

## 다시 만들기
```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python naver_pdf_fetcher.py --universe               # 1. 수집 → data/pdf/, data/manifest.csv (수 시간)
python -m pipeline.run --max-tokens 30000000 --yes   # 2. 추출 → data/out/reports.jsonl (Claude Code CLI 로그인 필요)
python -m pipeline.usage                             # 3. 사용량 확인
python -m pipeline.handoff                           # 4. 전달 파일 → data/handoff/
```
- 네이버 요청 간격(`DELAY`)은 1초 미만으로 줄이지 않는다.
- 추출은 `claude -p` 단일 호출(도구 끔, 앞 2쪽 텍스트, 필요 시 4쪽 1회 확장). 이번 실행: 2,077건, 약 2,100만 토큰, 9.3시간.
- 중간에 끊겨도 같은 명령을 다시 실행하면 끝난 건은 건너뛴다.
