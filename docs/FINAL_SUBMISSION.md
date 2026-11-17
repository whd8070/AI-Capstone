# 최종 교수 평가 제출 안내 — 개미구조대

**반영 기한:** 2026-11-18(수) · **교수 평가:** 2026-11-19(목), 평가 당일 `main` 기준

평가자는 [README](../README.md)의 **설치 → ④ 성향·수식 제안 → ② 포트폴리오 → ① 백테스트** 순서로 MVP를 확인할 수 있습니다. Claude Code CLI 로그인이 없다면 ④의 **규칙으로만 만들기 (LLM 없음)**로 수식 적용 흐름을 체험할 수 있습니다.

## 1. 평가 항목과 제출 파일

| 교수 평가 항목 | 파일 | 확인 내용 |
|---|---|---|
| **MVP 구현·실행** | [README](../README.md), [SPEC](SPEC.md), [웹 구현](../src/diffusion/kr_report_web.py), [AGENTS](../AGENTS.md) | 네 개 웹 탭·AC·설치/입력/기대 결과 |
| **골든·결정적 검증** | [golden_cases.yaml](../tests/harness/golden_cases.yaml), [설명 하니스](../tests/test_verification_golden.py), [수식 하니스](../tests/test_formula_golden.py), [결함 주입 기록](prompts/delegation_formula_golden.md) | 골든 26건, 정상·경계·금지 입력, 결함 검출 |
| **Evals 설계·실행 결과** | [EVAL_DESIGN](../evals/EVAL_DESIGN.md), [설명 36건](../evals/evalset.jsonl), [수식 24건](../evals/formula_evalset.jsonl), [실행 결과](../evals/results/) | AC별 지표·합격선, 케이스별 판정 JSON·이력 CSV |

관련 근거: [문제 정의](PROBLEM.md), [온톨로지](ontology.yaml), [설명 결함 주입](prompts/delegation_verification_golden.md), [Evals 러너 위임 기록](prompts/delegation_evals.md).

## 2. 실행 근거

- **기준 실행:** [Actions #44023933245](https://github.com/whd8070/AI-Capstone/actions/runs/44023933245) · 평가 소스 `9f194165` · 결과 저장 커밋 `edce0d3`
- **결정적 검증:** pytest 32/32, 모의 에이전트 유닛 테스트 13건
- **Evals:** 설명 36/36, 수식 제안 24/24
- **케이스별 결과:** [설명 JSON](../evals/results/2026-11-17T142511+0900_10fea90f.json), [수식 JSON](../evals/results/formula_2026-11-17T142510+0900_7acd874d.json)
- **실행 이력:** [설명 history.csv](../evals/results/history.csv), [수식 formula_history.csv](../evals/results/formula_history.csv)

이후 실행은 결과에 기록된 평가 커밋을 기준으로 구분합니다. CI는 실행별 Artifact를 보관하고, 평가한 코드가 최신 `main`인 경우에만 결과를 저장소에 푸시합니다.

## 3. 시연 시 확인할 사항

- **④:** 네 질문·추가 요청 → 수식·설명·진단 확인 → 사용자 확정 (AC-12a/12b/12c)
- **②:** 매수일 `2026-11-05`의 종목 순위·신규 1개 슬리브 목표 비중·리포트 근거 (AC-04a/05a/12c)
- **①:** `2026-10-27`~`2026-11-04` 기간 백테스트의 NAV·위험 지표·CSV (AC-12c)
- **금지 행동:** ④의 임의 Python 수식 거부 (AC-10c)
- **선택:** ③ 리포트 수집, ② AI 설명·검증 (AC-06a/07d/07g)

**측정 범위:** 자동 Evals는 통제된 모의 LLM 응답으로 코드의 안전 동작을 검사합니다. 실제 Claude/Codex 판단 정확도나 브라우저 E2E를 통과했다고 주장하지 않습니다. 투자 수익 보장·실주문 기능은 없습니다.
