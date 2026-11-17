# Golden 하니스 위임 및 검증 기록 — 2026-11-17

## 위임 범위
- 변경 가능: `tests/test_verification_golden.py`, `evals/verification_adapter.py`의 테스트 어댑터 부분.
- 읽기 전용: `SPEC.md` AC-06a/07d/07g, `AGENTS.md`, `tests/harness/golden_cases.yaml`, `src/diffusion/kr_report_verification.py`.
- 구현 의도: YAML에서 12개 케이스를 읽고 정상·경계·금지 규칙을 호출하여 기대 status/오류를 검사한다. `skip`·`xfail`·조건부 무시 금지. 정답 파일은 구현과 분리하고 실측에 맞춰 조용히 수정하지 않는다.
- 완료 기준: 12개 골든 케이스 전수 실행, 하니스 유효성 검증, 결함 주입 시 해당 오류 검출, 복원 후 전수 통과.

## 로컬 실행 기록
- 실행: `python -m pytest -q tests/test_verification_golden.py tests/test_evals_runner_mutation.py`
- 관측 결과: **16 passed** (골든 12, 골든 로더 1, 골든 변이 감지 1, Evals 러너 변이/세트 검사 2). skipped/xfail 0.
- 변이 1: 기존 `rule_errors()`를 테스트 중 `lambda _: []`로 치환해 **섹션 누락을 탐지하지 않는 결함**을 주입. `B01` 기대값과 비교 시 `STATUS_MISMATCH` 및 `MISSING_ERROR:MISSING_SECTION:불확실성` 검출. 테스트 후 monkeypatch 자동 복원.
- 검증 원본: `src/diffusion/kr_report_verification.py` blob SHA `7835537d46102687cc5116a382a268208422b83f`; `main`의 해당 파일과 동일.

## 검토 및 보류
- 구현에는 결함을 영구적으로 주입하지 않았으며, 판정 기대값을 수정하지 않았다.
- 팀의 **사람 승인**(케이스 기대값·MVP AC 및 테스트 보호 정책)은 별도로 필요하다. 위 결과를 사람 승인 완료 기록으로 해석하면 안 된다.
