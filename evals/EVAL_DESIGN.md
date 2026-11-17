# Evals 설계 — 최종 MVP (2026-11-17)

**정본 AC:** [docs/SPEC.md `5](../docs/SPEC.md). 두 Evals는 **결정적 코드 안전성·회귀 검사**이며, 실제 Claude/Codex의 금융 사실 판단 정확도나 투자성과를 측정하지 않습니다.

## 1. 평가 지표·합격선

| 평가 범위 | AC | 지표(기대 결과 일치 건수 / 해당 범주 건수) | 합격선 |
|---|---|---|---|
| 설명의 필수 5개 영역·형식 | AC-06a | 정상 응답의 필수 항목 충족률 | 100% |
| 설명의 경계 입력 | AC-06a | 누락·비정상 수치·길이 초과 등 기대 오류 탐지율 | 100% |
| 설명 검증 실패·금지 행동 | AC-07d, AC-07g | 거부·미판정·근거 없는 경고의 게시 차단률 | 100% |
| 수식 정상 제안 | AC-12a | 제안 출처·시도 횟수·진단 결과의 기대값 일치 | 6/6 |
| 수식 경계 입력 | AC-12a, AC-12b | 긴 메모·성향 오류·재시도·규칙 대체의 기대값 일치 | 6/6 |
| 수식 실패 복구 | AC-12b | CLI 오류·무효 수식·재시도·대체 일치 | 6/6 |
| 금지 수식 차단 | AC-10c | 임의 코드·속성 접근 등 거부/안전 대체 | 6/6 |

**합격선 근거:** 임의 코드 실행 금지·미검증 AI 설명 게시 차단·고정 골든 정답의 재현은 절대 규칙이므로 100%를 적용합니다. 고정된 테스트 사례 통과가 실제 모델의 성향 적합도 100%를 뜻하지는 않습니다.

## 2. 데이터셋과 채점

| 평가 | 데이터셋 | 케이스 구성 | 실행 |
|---|---|---|---|
| 설명 검증 게이트 | [evalset.jsonl](evalset.jsonl) | **36건**: 정상 8, 경계 10, 실패 10, 금지 8 | [run_evals.py](run_evals.py) |
| 수식 제안 루프 | [formula_evalset.jsonl](formula_evalset.jsonl) | **24건**: 정상 6, 경계 6, 실패 6, 금지 6 | [run_formula_evals.py](run_formula_evals.py) |
| 결정적 골든 | [golden_cases.yaml](../tests/harness/golden_cases.yaml) | **26건**: 설명 12 + 수식 14 | [설명 하니스](../tests/test_verification_golden.py), [수식 하니스](../tests/test_formula_golden.py) |

설명 JSONL은 `id/category/query/expect/graders/note/ac` 필드를 가지며, `rules`·`verify`·`local` 유형의 구조화 입력을 실제 `kr_report_verification` 함수에 전달합니다. `verify()`의 모델 판정 부분만 통제된 **모의 검증기 응답**으로 대체하고, 코드 채점기로 `status`·오류 코드·주장 수 등을 검사합니다.

수식 JSONL은 `id/category/ac/mode/profile/outputs/note/max_attempts/expect` 필드를 가집니다. 실제 `kr_formula_agent.propose()`를 호출하되 Claude 응답만 사전 고정된 응답으로 대체합니다. 실제 수식 파서·진단기를 통해 문법 오류, 피드백, 최대 3회 재시도·규칙 대체를 검사합니다. 정상 제안은 AC-12a, 오류·대체는 AC-12b, 금지 입력은 AC-10c에 연결합니다.

기대 정답을 함수에 그대로 반환하거나 예외를 PASS 처리하지 않습니다. **AC-12c의 골든은 수식 `blend()`의 수치 계산까지만 검증**하며, ④에서 적용 버튼을 누른 뒤 ②·①까지 이어지는 브라우저 E2E는 별도 확인이 필요합니다.

## 3. 실행·기록·기준선

```bash
python -m pip install -r evals/requirements-evals.txt
python -m pip install numpy pandas
(cd src/diffusion && python -m unittest -v test_kr_formula test_kr_formula_agent)
python -m pytest -q tests/test_verification_golden.py tests/test_formula_golden.py tests/test_evals_runner_mutation.py
python evals/run_formula_evals.py
python evals/run_evals.py --change "manual reproduction" --golden "26 golden cases"
```

각 러너는 케이스별 **실제 출력·기대값·합불**, 범주별 분자·분모를 JSON으로 저장합니다. 설명 실행은 [history.csv](results/history.csv), 수식 실행은 [formula_history.csv](results/formula_history.csv)에 누적하며 데이터셋 SHA-256으로 버전을 구분합니다. 설명 결과에는 평가 소스 커밋도 기록됩니다.

**검증된 기준선:** [GitHub Actions #44023933245](https://github.com/whd8070/AI-Capstone/actions/runs/44023933245) · 평가 소스 `9f1941654b32c99e922af4b60d899f586dd31fc3` · 결과 저장 커밋 `edce0d3`. pytest **32/32**, 수식 유닛 테스트 **13건**, 수식 Evals **24/24**, 설명 Evals **36/36** 통과. [설명 JSON](results/2026-11-17T142511+0900_10fea90f.json)과 [수식 JSON](results/formula_2026-11-17T142510+0900_7acd874d.json)에 사례별 결과가 남아 있습니다. 결과 저장 커밋은 프로그램·평가 코드를 바꾸지 않았습니다.

[자동 평가 워크플로](../.github/workflows/evals-ci.yml)는 새 결과를 Actions Artifact로 보존하고, **평가한 소스 커밋이 여전히 최신 `main`일 때만** 결과 JSON·CSV를 Git에 커밋합니다. 더 새로운 커밋이 존재하면 오래된 실행 결과를 푸시하지 않습니다.

## 4. Judge 및 측정 제외 범위

현재는 **코드 채점만 사용**합니다. [judge_prompt.md](judge_prompt.md)는 미사용 설계안으로, 별도 사람 라벨과 일치율을 측정하지 않았기 때문에 `judge_labels.jsonl`이나 judge 정확도를 제출하지 않습니다.

P30·M30·G30(실제 LLM의 주장 검증), TIME50·EXTRACT100·REPORT20(별도 수치 시험)은 이번 오프라인 60건으로 실측했다고 주장하지 않습니다. 실제 모델의 성향 적합도·초보자 사용성·투자 성과도 해당 Evals의 측정 대상이 아닙니다.

결함 주입 기록: [설명 하니스](../docs/prompts/delegation_verification_golden.md) · [수식 하니스](../docs/prompts/delegation_formula_golden.md) · [Evals 러너](../docs/prompts/delegation_evals.md).
