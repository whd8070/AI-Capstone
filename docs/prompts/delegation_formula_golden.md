# 성향 기반 수식 제안 골든 하니스 — 위임 범위·검토·결함 주입

## 1. 대상과 기준(사람의 수용 전 확인)

- 기능: 네 문항·추가 요청 → AI/규칙 수식 제안 → 진단·최대 3회 재시도 → 사용자 적용 가능한 안전 수식.
- 읽기 전용: `SPEC.md` AC-10c/12a/12b/12c, `AGENTS.md`, `tests/harness/golden_cases.yaml`.
- 변경 대상: `tests/test_formula_golden.py` 및 설명 하니스의 케이스 필터(`tests/test_verification_golden.py`).
- 범위 밖: 실제 Claude API/CLI 정확도, 외부 시세·브라우저 클릭 E2E. AC-12c는 수식 `blend()`의 **계산 값 계약**만 골든으로 보증.
- 절대 규칙: 기대값을 테스트 성공에 맞춰 바꾸지 않고, skip/xfail로 우회하지 않는다.

## 2. 위임 요청 내용

YAML의 `input.kind=formula_agent` 사례는 실제 `kr_formula_agent.propose()`에 고정 LLM 응답을 공급한다. `formula_score` 사례는 실제 `kr_formula.blend()`의 수치값을 비교한다. 경계 입력은 누락·잘못된 성향·긴 메모, 금지 입력은 Python 명령/속성 접근이다.

하니스는 케이스마다 `expect`의 `status/source/formula/attempts/rejected/issues` 및 피드백 문구 등을 검증해야 하며, 단일 사례를 생략하지 않는다.

## 3. 결함 주입 설계

- 대상: `kr_formula_agent.diagnose`가 금지 Python 수식을 잘못 유효하다고 판단하게끔 임시 함수를 주입.
- 사용 케이스: `AG-P01`, `__import__('os').system('calc')`.
- 정상 기대: 첫 수식 거부, `source=rule`, `rejected=1`.
- 변이 기대: 금지 수식이 유효하게 처리되어 `source=agent`, `rejected=0`; 하니스가 기대값 불일치를 감지해야 한다.
- `monkeypatch`로 함수 대체를 테스트 범위에만 적용하고 이후 복구한다.

## 4. 실제 GitHub Actions 실행·결함 주입 기록

- 실행 커밋: `12f357c55df849a4489f805a06482c0324093e10`.
- 실행 로그: [GitHub Actions 성공 기록](https://github.com/whd8070/AI-Capstone/actions/runs/44020831879)에서 `Golden and mutation tests` 단계 확인.
- 실제 관측: 전체 pytest **32 passed**, 이 안에 **설명 12건 + 수식 제안 14건 골든** 및 독립 결함 주입 검사 포함. 모의 에이전트 13 unittest 성공, 수식 Evals 24/24, 설명 게이트 Evals 36/36.
- 결함 주입 실행: 하니스 `test_formula_mutant_bypasses_safety_and_is_detected`가 변이를 임시 적용했고, 정상 대비 `AG-P01`의 기대 `source=rule / rejected=1` 불일치를 실제 판정하여 테스트가 통과했다. `monkeypatch`가 변이를 종료 후 복원했다.
- 사람 수용 승인: **미완료**, [기준 승인 기록](../reviews/EVAL_APPROVAL.md) 참조.

기존 위임 프롬프트가 실제 원문으로 제공되지 않는 경우 이 문서의 위임 내용은 **현재 보완 작업의 명세**이며 과거 위임 사실이나 인간 검토를 소급해 주장하지 않는다.
