# 실제 Claude/Codex 의미 검증 Evals — 로컬 실행 가이드

현재 `evals/run_evals.py`의 36/36 결과는 **모의 판정 주입 방식의 게시 게이트** 평가입니다. 아래 러너는 `kr_report_verification.model_verdicts()`를 통해 **로그인된 실제 CLI**를 호출합니다.

## 1. 데이터셋 준비 (사람이 직접 승인)

1. 루트에서 `mkdir evals\local`, `copy evals\live_evalset.template.jsonl evals\local\live_claims.jsonl`를 실행합니다.
2. 각 JSONL 행을 **실제 확인 가능한 증권사 원문·원본 버전·실행 계산 결과**를 근거로 다시 작성합니다. 템플릿은 예시일 뿐 평가 데이터가 아닙니다.
3. `claim`은 검증할 단일 주장, `facts`는 검증기의 실제 입력 계약(`holdings`, `report_records`, `scenario` 등), `expected_verdict`는 인간이 확정한 정답, `gold_note`는 사람의 근거 메모입니다.
4. 사람이 원문과 계산을 확인한 경우에만 `human_reviewed: true`로 변경합니다. **원문 자체를 무단 공개하거나 모델에 라벨 작성을 위임하지 않습니다.**
5. 스펙에 맞춰 P30(출처 ID 없음 10/빈 ID 10/존재하지 않는 ID 10), M30(수치·단위·종목·기간·확정성·인과 각 5), G30(정상 30)을 독립적으로 구성합니다.

## 2. Windows PowerShell 명령 (저장소 루트)

```powershell
$py = ".\src\diffusion\.venv\Scripts\python.exe"
& $py -m pip install jsonschema
& $py evals/run_live_verifier.py --dataset evals/local/live_claims.jsonl --dry-run
codex login status
& $py evals/run_live_verifier.py --dataset evals/local/live_claims.jsonl --backend codex --limit 3
```

Claude를 선택하면 `claude auth status`로 로그인 확인 후 `--backend claude`를 사용합니다. CLI 호출은 사용량·접근 권한 및 비용 정책의 영향을 받습니다.

## 3. 전체 90건 실행

```powershell
& $py evals/run_live_verifier.py --dataset evals/local/live_claims.jsonl --dry-run --require-complete
& $py evals/run_live_verifier.py --dataset evals/local/live_claims.jsonl --backend codex --require-complete
```

결과는 기본적으로 `evals/local_results/live_<backend>_*.json`에 생성됩니다. 주기적인 `*.partial.jsonl`에는 도중 진행 결과가 저장되어, 인증·사용량 오류로 중단되어도 이전 케이스를 확인할 수 있습니다. 불완전한 건수는 **파일럿**으로만 표기합니다.

## 4. 합격 기준과 발표

- P30: 27/30 이상 `reject`
- M30: 24/30 이상 `reject`
- G30: 27/30 이상 `pass` 또는 타당한 `warn`
- 실제 보고서 게시 게이트는 별도로 검증하며, 본 러너의 모델 판정 결과만으로 승인 완료를 주장하지 않습니다.
- 코드의 `warn` 자동 점수는 형식상 사유·근거 ID 존재만 확인합니다. **타당성은 사람이 원문과 대조해 사후 검토**해야 하며, 미확인 시 G30 실질 합격을 유보해야 합니다.
- `evals/local/`과 `evals/local_results/`는 Git에서 제외됩니다. 평가 공개가 허용된 경우에만 **민감정보·저작권 있는 텍스트를 제거한 요약본**을 `evals/results/`로 만들어 커밋하고 README/SPEC의 미검증 상태를 업데이트합니다.
