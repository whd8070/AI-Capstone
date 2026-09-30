# AGENTS.md

이 문서는 두 가지 역할을 한다.
**A부**: 이 저장소에서 작업하는 코딩 에이전트(및 팀원)를 위한 저장소 규칙.
**B부**: 우리가 구축하는 시스템의 에이전트 아키텍처 정의 — 각 에이전트의 책임, 입출력 계약, 금지사항, 관련 AC.

## 프로젝트 개요

기존 포트폴리오 최적화 알고리즘의 산출 비중을, 실시간 크롤링한 뉴스·시황을 근거로 설명하고, 그 설명을 주장 단위로 검증하는 챗봇.
문제 정의: `docs/problem-definition.md` · 요구사항: `docs/spec-v1.md` · 도메인 모델: `docs/ontology-v1.md`

---

# A부 — 저장소 규칙 (코딩 에이전트용)

## 저장소 구조

```
/docs        문제정의서, 온톨로지, 스펙, 설문 분석 (수정 시 근거 태그 유지)
/docs/raw    설문·인터뷰 원본 — 수정 금지 (읽기 전용 취급)
/agents      research/ explanation/ verification/ orchestrator/
/schemas     에이전트 간 입출력 JSON 스키마 (B부의 계약과 1:1)
/tests       AC 검증 테스트 — 테스트 ID는 AC ID와 일치시킨다 (예: test_ac_04a)
/spikes      기술 검증 기록 — 날짜_주제.md, 결론과 AC 임계값 조정 근거 포함
```

## 작업 규칙

- 실행: `pip install -r requirements.txt` → 테스트: `pytest tests/`
- 모든 PR은 관련 FR/AC ID를 본문에 명시한다. AC 없는 기능 추가는 스펙 개정 PR을 먼저 낸다.
- AC 임계값 수정은 `spec-v1.md` 개정 + 근거 스파이크 링크 없이는 금지.
- 시크릿: API 키·크롤링 인증 정보는 `.env`, 커밋 금지 (`.gitignore` 확인).
- `/docs/raw` 하위 파일은 어떤 이유로도 수정하지 않는다 — 인용은 복사로.
- 크롤러 구현 시 대상 사이트의 robots.txt·약관 준수 목록(`agents/research/sources.md`)을 벗어나는 소스 추가 금지.

---

# B부 — 시스템 에이전트 아키텍처

## 파이프라인

```
포트폴리오 최적화기(외부 모듈)
        │ 비중 + t_opt
        ▼
[Research Agent] ──수집 풀──▶ [Explanation Agent] ──설명 초안──▶ [Verification Agent]
        ▲                                                   │
        │                              반려(최대 2회) ◀──────┤
   사용자 질의                                               │ 통과
        │                                                   ▼
   [Orchestrator] ◀────────────────────────────── 검증 완료 응답 ──▶ 사용자
```

검증 실패가 재생성 한도를 초과하면 정직 실패 응답("확인된 출처가 없어 답할 수 없음")으로 전환한다. (AC-04d, 시나리오 S3)

## Research Agent (조사)

- **책임**: 뉴스·시황·공시의 실시간 수집, 메타데이터 부착, 시점 분류
- **입력**: 관심 자산 목록, 포트폴리오 산출 기준시점 `t_opt`
- **출력 계약**: `{source_url, t_pub, t_crawl, source_grade, content, pool}` — `pool ∈ {산출근거, 최신참고}`는 `t_pub`과 `t_opt` 비교로 결정 (AC-02c)
- **금지**: 수집 원문의 해석·요약·왜곡. 메타데이터 4종 중 하나라도 결측인 항목의 적재 (AC-02a). 승인 목록 외 소스 크롤링.
- **관련 AC**: AC-02a ~ AC-02d

## Explanation Agent (설명)

- **책임**: 비중 ↔ 수집 정보 연결 설명 생성, 대화형 질의응답
- **입력**: 비중 벡터 + `t_opt`, Research Agent의 수집 풀, 사용자 질의
- **출력 계약**: 주장(claim) 단위로 구조화된 응답 — `{claim_text, source_ids[], cited_numbers[], pool_label}`
- **금지**: 출처 ID 없는 사실 주장 생성 (AC-03a). 수집 풀 외부 지식으로 수치 생성 (AC-03b). "산출근거"와 "최신참고" 풀의 혼용 표기 (AC-06a). 비중의 산출 원인처럼 뉴스를 서술하는 사후 합리화 문구.
- **관련 AC**: AC-03a ~ AC-03c, AC-06a

## Verification Agent (검증)

- **책임**: 설명 초안의 주장 단위 검증 — ① 출처 존재성, ② 주장-출처 정합성(entailment + 수치 대조), ③ 시점 정합성
- **입력**: Explanation Agent의 구조화 출력 + 수집 풀 원문
- **출력 계약**: 주장별 판정 `{claim_id, verdict ∈ {pass, reject, warn}, reason, layer}` + 감사 로그 (AC-04e)
- **권한**: **설명 출력 전체 또는 일부 주장을 반려(reject)할 수 있다.** 반려된 주장은 사용자에게 무라벨로 노출될 수 없다 (AC-04c). 이 권한은 아키텍처 불변조건이며, 어떤 기능 추가도 이를 우회하는 경로를 만들 수 없다.
- **구현 원칙**: ①·③계층은 규칙 기반(스키마 검사·시각 비교)으로 LLM 비의존, ②계층은 LLM entailment + 결정적 수치 파서 병행 (spec-v1.md §6 리스크 대응)
- **금지**: 판정 없이 통과시키는 기본값(default-pass). 로그 없는 판정.
- **관련 AC**: AC-04a ~ AC-04e, NFR-02

## Orchestrator (조정)

- **책임**: 사용자 세션 관리, 에이전트 호출 순서 제어, 재생성 루프 카운트, 면책 고지 삽입 (NFR-03), 응답 시간 예산 관리 (NFR-01)
- **금지**: Verification 판정을 무시한 응답 전달. 재생성 한도(2회) 초과 루프.

## 에이전트 간 공통 불변조건

1. 모든 에이전트 간 메시지는 `/schemas`의 JSON 스키마를 통과해야 한다 — 스키마 위반은 파이프라인 중단.
2. 시점 정보(`t_opt`, `t_pub`, `t_crawl`)는 파이프라인 전 구간에서 보존되며 어떤 에이전트도 이를 제거·수정할 수 없다.
3. 사용자에게 도달하는 모든 문장은 Verification Agent의 pass 또는 warn 판정을 가진다 — 예외 없음.
