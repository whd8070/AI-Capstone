# Evals 러너 위임·검증 이력 — 2026-11-17

## 위임 내용
`evals/EVAL_DESIGN.md`, `evals/evalset.jsonl` 및 `SPEC.md`의 대상 AC를 읽되 **판정 기준과 기대값은 수정하지 말 것**. Python 러너는 오프라인 검증 게이트에 36개 구조화 입력을 보내 실제 출력을 받고, `status`, `errors`의 기대값과 비교하여 범주별 분모·분자, 케이스별 실제 출력을 저장한다. 실행마다 JSON 새 파일과 `history.csv` 새 행을 만든다. 실제 LLM 판정 정확도를 측정한 것처럼 기록하지 않는다.

## 실행·결함 주입 기록
- 명령: `python evals/run_evals.py --change '2026-11-17 first deterministic verification-gate baseline' --golden '12/12 passed (plus loader 1)' --commit 4e68acea3a7abf0d90ca48f5129b023826caad1c`
- 첫 baseline: **36/36**, 정상 8/8, 경계 10/10, 실패 10/10, 금지 8/8 (오프라인 게시 게이트에 한함).
- 변이 1: 정답이 `FAIL`인 경우에 가짜 `PASS`와 빈 오류를 주입. `grade()`는 `STATUS_MISMATCH`, `MISSING_ERROR:REJECTED_OR_UNGROUNDED`를 반환하여 오답을 실패로 분류.
- 변이 2: 위임받은 골든 하니스에 섹션 누락을 놓치는 가짜 규칙 검사기 주입 → 섹션 누락 사례가 실제 실패로 바뀜.
- 별도 LLM-as-judge **미실행**, 사람 judge 라벨 **미작성**(사람 직접 라벨 전까진 생성 금지).
- 결함 주입 후 구현과 테스트 판정 기준은 원복하였고, 기대값을 성능에 맞춰 수정하지 않았다.

## 한계·수용 보류
이 검사는 실제 사용 중인 설명 생성 모델이 거짓 주장을 얼마나 잘 알아내는지 측정하지 않는다. AC-07a~c의 P30/M30/G30 실측은 후속 평가가 필요하다. 케이스와 합격선은 팀 담당자의 명시적 승인 전까지 **검토 대기**다.
