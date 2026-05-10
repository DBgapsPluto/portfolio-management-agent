# TODOS

DB GAPS 자산배분 에이전트 v1 (이후) 작업 목록. plan-eng-review (2026-05-10)에서 도출.

---

## 1. MTS export 형식 매핑 확정 (운용 피드백)

**What:** 거래내역·보유현황·일별 평가액 CSV 컬럼을 우리 코드 매핑과 정확히 1:1 일치시키기.

**Why:** 회전율 계산식 = `(매수금액 + 매도금액) / 평균자산`. 수수료·세금·종가 기준 평가액이 MTS 형식에 어떻게 들어가는지 확인하지 않으면 회전율 floor 미달 false positive/negative 발생 가능. **회전율 미달은 컷오프 직결.**

**Pros:** 정확한 회전율 모니터링·monthly 보고서의 수익률 자체평가 정확도 향상.

**Cons:** 첫 거래 후에야 sample export 가능. 사전 작업 불가.

**Context:** 스펙 §15.1·db-gaps-prerequisites.md §5. 6/1 첫 거래 직후 export sample 1개 받아서 `dataflows/transactions.py` 컬럼 매핑 확정.

**Depends on / blocked by:** 6/1 이후 첫 매매 거래내역.

---

## 2. Memory log portfolio-aware 재설계 (lap2)

**What:** D8 결정으로 v1에서 deprecate한 memory log·reflection 시스템을 portfolio 단위로 재설계.

**Why:** 자산배분 결정의 사후 alpha 평가는 weight vector 단위로 해야 함. `Reflector.reflect_on_final_decision`이 단일 ticker 가정이라 portfolio 결정에 적용 불가. 6월·7월 운용 데이터를 받아 8월 리밸런싱·9월 retro에 반영.

**Pros:** 70점 평가 "철학 일관성" 증거 보강·다음 회차(lap2)에 운용 학습 반영.

**Cons:** 풀 재설계 ~150줄. 운용 중 데이터 모이기 전엔 설계 검증 어려움.

**Context:** 스펙 §12.1·D8 결정. portfolio_decisions.jsonl을 base로 하고 위에 reflection layer 추가.

**Depends on / blocked by:** 6월·7월 운용 데이터.

---

## 3. LLM provider rate limit 처리 (Critical gap)

**What:** OpenAI·Anthropic·Google API의 rate limit 장애 시 명시적 처리. exponential backoff retry + 사용자에게 명확한 surface 메시지.

**Why:** plan-eng-review에서 발견된 critical gap. 현재 설계에서 rate limit이 발생하면 ValidationError로 silent하게 위로 전파될 가능성. 5/28 마감 직전·월말 리밸런싱 시점에 운용자가 "쿼터 초과"인지 "코드 버그"인지 구분 못 하면 시간 낭비.

**Pros:** 운용 안정성·문제 surface 명확.

**Cons:** `tradingagents/llm_clients/`의 각 provider client에 backoff wrapper 추가. ~50줄.

**Context:** plan-eng-review Failure modes 표·D7 retry는 schema 실패에만 적용. rate limit은 별개. tenacity 또는 자체 backoff.

**Depends on / blocked by:** 없음. v1에 포함하는 게 안전하지만 시간 압박 시 lap2.

---

## 4. Subagent 비용 실측 후 model 강등 검토

**What:** 5/28 dry-run 후 monthly 풀 파이프라인 실제 토큰·비용 측정. deep model로 설정된 subagent 중 quick으로 강등 가능한 것 식별.

**Why:** 스펙 §15.1 추정 monthly ~$15는 거친 추정. 실측 후 비용 폭주 시 `classify_event_impact`·`pick_optimization_method` 등 일부 subagent를 quick model로 옮길 여지. `subagent_model_policy` 설정만 바꾸면 됨.

**Pros:** 비용 최적화·운용 3개월간 ~$45→$30 절감 가능성.

**Cons:** 측정 자체에 시간 소요. quick으로 강등 시 품질 저하 가능 — A/B 비교 필요.

**Context:** 스펙 §15.1·D6 BaseSubagent 결정으로 model_tier 변경이 1줄 수정만으로 가능. 측정만 하면 결정 빠름.

**Depends on / blocked by:** 5/28 dry-run 완료.

---

## 6. Historical universe snapshots (Survivorship-bias-aware backtests)

**What:** `data/universe/2024-01-01.json`, `data/universe/2025-06-01.json` 등 시점별 universe 스냅샷을 구축. 또는 KRX historical listing 데이터 소싱.

**Why:** v1에서 `Universe.tradable_at(as_of)` 인프라는 들어갔지만 `listed_since` 채울 데이터 소스가 한정적. pykrx의 ETF 상장일 조회는 일부 종목에서만 작동. `gaps simulate`로 2024년 등 과거 시점 백테스트 시, 그 시점에 상장 안 된 ETF가 universe에 포함되어 있으면 survivorship bias로 수익률 과대평가됨. 현재 5/28 plan은 2026 시점이라 영향 없음 — 백테스트 신뢰도 향상이 동기.

**Pros:** `gaps simulate` 결과 신뢰도 ↑, 평가자가 백테스트 근거 인용 시 정직한 데이터.

**Cons:** KRX historical listing 데이터 수집 인프라 필요 (월 1회 cron). 외부 데이터 부재 시 KIS·DataGuide 같은 유료 데이터 vendor 검토.

**Context:** Plan 1 Task 14 `_fetch_listed_since` 헬퍼는 best-effort. lap2에서 정식 historical universe 시스템 구축.

**Depends on / blocked by:** 백테스트 기반 의사결정 비중에 따라 우선순위 조정. v1에서는 5/28 live plan에 영향 없음.

---

## 7. KRX/US 타임존 정밀 처리

**What:** 미국 매크로 데이터(FRED) 발표 시각과 KRX 장 마감(15:30 KST) 간 정렬을 정확히 처리.

**Why:** 현재 publication_lag은 calendar-day 단위라 코어스. 예: FOMC 회의가 미 동부 14:00에 끝나도 KST로는 다음 날 04:00. 같은 날 한국 ETF 종가에 반영 가능 vs. 익영업일 반영 vs. 무관 — 시점별 타이밍 차이가 수익률에 영향.

**Pros:** 백테스트·rebalance 의사결정 시점 정밀도 향상.

**Cons:** 시리즈별 발표 시각 메타데이터 필요. 보수적 접근 (cutoff D+1)으로도 충분할 가능성.

**Context:** Plan 1 Task 17 `_publication_cutoff` 함수 코멘트에 명시됨. 보수적 D+1 일률 적용 중.

**Depends on / blocked by:** 백테스트 정밀도 요구 수준에 따라 조정.

---

## 8. Cache + publication_lag 결합 (TieredCache로 FRED/ECOS wrap)

**What:** 현재 publication_lag은 fetcher 내부에서만 적용되고 TieredCache wrap은 pykrx prices에만 있음. FRED/ECOS도 TieredCache로 감싸서 D-1 cache fallback이 유지되도록 통일.

**Why:** plan-eng-review 2차에서 발견. live 운용 중 FRED API 일시 장애 시 cache fallback 활성화. 단 publication_lag을 캐시 키에 포함시켜 as_of_date별로 다른 캐시 파일 생성하도록 설계 필요. v1 5/28 라이브에서는 영향 작지만 monthly rebalance 회복력 향상.

**Pros:** 외부 API 장애 시 회복력 통일.

**Cons:** cache 키 설계 주의 (as_of, series, lag 조합). ~30줄 + 캐시 일관성 검증 테스트.

**Context:** plan-eng-review 2차 NOT-in-scope. publication_lag을 fetcher 외부에서 적용하는 패턴으로 리팩토링하면 cache가 raw data를 저장하고 lag은 read-time 적용 가능.

**Depends on / blocked by:** 6월 운용 중 FRED 장애 빈도 관찰.

---

## 9. `_ConditionParser` 괄호·중첩 식 지원 (daily 트리거)

**What:** Plan 4 Task 9의 `_ConditionParser`가 `(A AND B) OR C` 같은 중첩 표현 미지원. v1은 단순 AND/OR만 처리.

**Why:** 향후 트리거 룰셋 정교화 시 필요. 예: `(vix > 30 AND vkospi > 25) OR (kospi_return_1d < -0.03 AND any_etf_weight > 0.18)` 같은 복합 조건. v1 룰셋은 단순 OR/AND라 충분.

**Pros:** 표현력 향상. 운용 중 발견한 새 risk 패턴을 yaml로 표현 가능.

**Cons:** 보안 표면 확장 (parser 정확성·예외 케이스 검증 필요). 현재는 의도적 제한.

**Context:** D14에서 보안 이유로 eval() 폐기. 괄호 지원 시 재귀 파서 또는 외부 라이브러리 (pyparsing 등) 검토.

**Depends on / blocked by:** 6월 운용 중 트리거 표현력 한계 체감 시.

---

## 5. db_gaps_v2.yaml preset (다음 회차)

**What:** 제13회 또는 다음 자산배분 대회용 preset YAML 작성.

**Why:** 본 v1 구현은 db_gaps preset YAML로 분리 (D3 결정). 코드 변경 없이 새 preset 추가만으로 다음 회차 운용 가능. 8월 31일 대회 종료 후 회고를 반영.

**Pros:** 인프라 재활용·다음 회차 시작 시간 단축.

**Cons:** 대회 룰 변경(예: 단일 한도 조정·자산군 카테고리 변경) 시 mandate validator 수정 필요할 수도.

**Context:** 스펙 §4.3 향후 확장. presets 디렉토리에 yaml 파일 추가만.

**Depends on / blocked by:** 다음 회차 대회 룰 발표.
