# Stage 1 코드 감사 + 디버깅 가능성 개선 Plan

**작성일:** 2026-05-26 (대회 제출 마감 5/28 — D-2)
**목적:** Stage 1 네 분석가(macro_news / macro_quant / market_risk / technical) 코드를 (a) 논리 검증, (b) 하드코딩 카탈로그, (c) 데이터 흐름·staleness propagation, (d) blackbox observability 4 차원에서 감사하고, 즉시 수정 가능한 결함은 수정한다.
**범위:** Stage 1 만 (Stage 2-6 별도 plan).
**마감 제약:** 5/28 production 출력에 영향 줄 수 있는 수정만 우선 처리. 광범위 refactor 는 deferred.

---

## 0. Audit Dimensions (4)

| 차원 | 무엇을 본다 | 합격 기준 |
|---|---|---|
| **L (Logic)** | 각 skill/agent 의 핵심 계산 로직 — sign convention, divide-by-zero, off-by-one, fallback 의미 | 잘못된 결과를 산출하지 않음. 의심 케이스 reproduce → 수정 또는 의도 확인. |
| **H (Hardcoding)** | 임계값/윈도우/기본값/매직넘버 | 카탈로그로 정리. critical 한 것만 즉시 const/config 로 분리; 나머지는 향후 후보로 기록. |
| **D (Data flow)** | report schema → downstream consumer (factor model, candidate selector, allocator) 매핑 정합성. staleness_days=99 sentinel 이 어디까지 잘리는지. | downstream 이 sentinel 을 모르고 사용하는 곳 0. 발견 즉시 가드 추가. |
| **O (Observability)** | logger.warning 빈도, attribution dict, blackbox 영역 | 모든 분석가가 자기 산출에 대해 (a) 입력 fetch 성공/실패, (b) sentinel 사용 여부, (c) 핵심 임계값 통과 여부 기록. |

---

## 1. 우선순위 & 순서

대회 제출에 영향 큰 순서:

1. **Task 0 — Cross-cutting: staleness propagation 점검** (모든 분석가 결과가 Stage 2/3 로 가는 길목 검증. D 차원).
2. **Task 1 — technical analyst** (Stage 3 cluster-aware selection 이 직전에 머지됨. 새 panel/cluster 가 잘 채워지는지 + observability 부재 영역 가장 큼. L+H+O).
3. **Task 2 — macro_quant analyst** (regime classifier 결과 → Stage 2 factor model β · Stage 3 regime weights 의 입력. sentinel 정책 영향 큼. L+H+O).
4. **Task 3 — market_risk analyst** (systemic_score → method_picker 입력. sentinel/blackbox 큼. L+H+O).
5. **Task 4 — macro_news analyst** (silent exception 우려. narrative 만 LLM 소비 → 직접 allocator 영향 작음. 우선순위 최저. L+O).
6. **Task 5 — 통합 sanity run** (전체 Stage 1 한 번 돌려보고 report 6 개 출력 확인. 회귀 가드).

---

## 2. 공통 작업 패턴 (각 Task 안에서 반복)

각 분석가 task 는 sub-step:
- **A. 코드 정독 + 논리 점검** — entry, 주요 skill, schema, downstream consumer.
- **B. 하드코딩 카탈로그** — `grep`/Read 로 magic value 수집. 표 정리.
- **C. 즉시 결함 수정** — A/B 에서 발견된 명백한 버그/모순.
- **D. observability 보강** — `attribution: dict | None = None` 인자 + 핵심 분기점 (sentinel 사용, threshold pass/fail, fetch 성공/실패) 기록. 보강만 하고 호출부는 optional.
- **E. 점검 결과 commit** — 분석가별 1 commit. `audit(stage1): <analyst> — findings + observability`.

코드 변경 없는 차원(예: 의심점 없음)은 sub-step 생략하고 진행. 점검 결과만 task 끝의 commit 메시지에 기록.

---

## 3. Task 0 — Cross-cutting: staleness propagation 점검

**Files (Read only, 필요 시 수정):**
- `tradingagents/schemas/reports.py` (Stage 1 4 Report 스키마)
- `tradingagents/skills/research/factor_estimators.py` (Stage 2 factor 입력)
- `tradingagents/skills/portfolio/method_picker.py` (Stage 3 method picker)
- `tradingagents/agents/allocator/portfolio_allocator.py` (Stage 3 entry)

**Steps:**
- [ ] **0.1** `grep -rn "staleness_days\s*==\s*99\|staleness_days.*99" tradingagents/` — sentinel 마커가 downstream 에서 검사되는 곳 모두 수집.
- [ ] **0.2** Stage 1 → Stage 2 데이터 매핑 정리: factor_estimators 가 어느 Report field 를 어떻게 읽는지 표.
- [ ] **0.3** Stage 1 → Stage 3 데이터 매핑 정리: method_picker / portfolio_allocator 가 어느 Report field 를 어떻게 읽는지.
- [ ] **0.4** Sentinel(staleness=99) 인 값을 downstream 이 "정상 값"으로 오용하는 경로 발견 시 issue list 에 기록 + 즉시 가드 추가.
- [ ] **0.5** Findings 를 `docs/stage1_audit.md` 에 기록.
- [ ] **0.6** commit: `audit(stage1): cross-cutting staleness propagation map + guards`.

**합격 기준:** sentinel 가드 누락 0 (또는 list + 즉시 수정).

---

## 4. Task 1 — technical analyst

**Files:**
- `tradingagents/agents/analysts/technical_analyst.py`
- `tradingagents/skills/technical/{correlation_cluster,extended_indicators,trend_state,trend_quantification,momentum_ranker,sector_rotation,universe_breadth,risk_adjusted}.py`
- `tradingagents/schemas/technical.py`, `tradingagents/schemas/reports.py:109-150` (TechnicalReport)
- 신규 Stage 3 consumer: `tradingagents/skills/portfolio/{factor_scorer,candidate_selector}.py` (방금 머지된 코드가 이 분석가 출력에 의존).

**Steps:**
- [ ] **1.1 — L** correlation_cluster 임계값 ≥0.7 의 실제 동작 확인. 입력 데이터 적을 때(top returns only) 그룹화 실패 모드 reproduce. cluster-aware selection 이 빈 cluster 받았을 때 fallback 동작 확인 (이미 corr fallback 있음).
- [ ] **1.2 — L** factor_panel 이 Stage 3 에 전달되는 ticker 와 universe 의 ticker 가 일치하는지 — late-listed ETF / delisted 케이스 처리.
- [ ] **1.3 — L** extended_indicators(BB %B, MFI, stoch_k) 의 bound 검증 (schema 의 ge/le 와 실제 출력 일치).
- [ ] **1.4 — H** 하드코딩 카탈로그: ADX>25, BB bw<5%, MFI 20/80, %B>1.0, stoch>80, 188 ETF count, 252d/60d window. **즉시 분리**: `_timing_overlay` 의 임계값(80/1.0/20)이 분기 결정에 직접 영향 → `TIMING_OVERBOUGHT_*` 상수로 분리 검토.
- [ ] **1.5 — O** technical_analyst entry 에 `logger.info("technical analyst start: %d ETF universe", ...)`, 각 tier 산출 후 카운트 로그, 빈 panel/cluster 시 `logger.warning`. blackbox 제거.
- [ ] **1.6 — C** 1.1-1.4 에서 발견된 명백한 결함 수정.
- [ ] **1.7 — E** commit: `audit(stage1): technical — findings + observability [Task1]`.

**합격 기준:** Stage 3 cluster-aware 가 의존하는 5 패널(correlation_clusters, risk_adjusted, trend_quant, extended_indicators, individual_etf_states) 의 비정상 입력 reproduce → graceful handling 확인.

---

## 5. Task 2 — macro_quant analyst

**Files:**
- `tradingagents/agents/analysts/macro_quant_analyst.py`
- `tradingagents/skills/macro/{regime_classifier,yield_curve,inflation,employment,kr_*,us_leading,gdp_nowcast,fed_path,fx,risk_appetite,china_leading,foreign_flow,tail_risk,financial_conditions,inflation_expectations,kospi_valuation}.py`
- `tradingagents/dataflows/{fred_fetcher,ecos_fetcher}.py`
- `tradingagents/schemas/reports.py:48-75` (MacroReport)

**Steps:**
- [ ] **2.1 — L** regime classifier 의 quadrant 분류 로직 — CFNAI<-0.7, inflation slope sign 등 결정 boundary 의 reproduce. **edge case**: CFNAI 값이 sentinel (staleness=99) 인 상태로 분류기에 들어가면 어떻게 되는지.
- [ ] **2.2 — L** Stage 2 factor_estimators 가 MacroReport 의 어느 필드를 어떻게 합성하는지 (Task 0 와 연계). sentinel 입력 시 factor 값 distortion 확인.
- [ ] **2.3 — L** NARRATIVE_PROMPT 의 prone-to-inversion 의심 (e.g. "CLI down = contraction" 을 LLM이 거꾸로 읽을 가능성). 현재 prompt 의 numeric injection 패턴 검토.
- [ ] **2.4 — H** Sentinel 기본값 카탈로그: BSI=100, CLI=100, CFNAI=0, FX=1300, policy_epu=100. **이 값이 평상시 값과 구별되는가?** (예: BSI 평균이 100 근처면 sentinel 와 정상 값 구별 불가 → 사용 신호로 staleness_days 만 확인 필요).
- [ ] **2.5 — O** silent exception 영역(KR divergence, FCI, fed_path, FX, China, foreign flow) 에 logger.warning + attribution 기록. 단순 try/except pass → try/except + log + attribution.
- [ ] **2.6 — C** 2.1-2.4 에서 발견된 명백한 결함 수정.
- [ ] **2.7 — E** commit: `audit(stage1): macro_quant — findings + observability [Task2]`.

**합격 기준:** regime quadrant 분류가 sentinel 입력에서 안전(잘못된 regime 으로 미끄러지지 않음 또는 명시적 "unknown" 반환).

---

## 6. Task 3 — market_risk analyst

**Files:**
- `tradingagents/agents/analysts/market_risk_analyst.py`
- `tradingagents/skills/risk/{volatility,vix_term_structure,skew,vxn,realized_volatility,credit_spread,credit_quality,fear_greed,breadth,correlation_pca,systemic_score,kr_yield_curve,kr_corp_spread,kr_margin_debt,kr_market_tier,equity_bond_corr,real_yields,funding_stress}.py`
- `tradingagents/schemas/reports.py:78-106` (RiskReport)

**Steps:**
- [ ] **3.1 — L** systemic_score 의 LLM 호출 / 결정적 분기 — 입력이 sentinel 일 때 어떻게 동작하는지. score / regime → method_picker 입력으로 전달되는 경로 (Task 0 와 연계).
- [ ] **3.2 — L** correlation_pca 의 stub data fallback (synthetic 5-asset, 250 points) 이 production 에서 활성화되는 경로 점검. **위험 신호**: production 출력이 stub 으로 silently fallback 되면 안 됨.
- [ ] **3.3 — L** breadth 의 equal-weight proxy fallback 의미 — 실제 weights 가 사용 불가일 때 결과의 신뢰성.
- [ ] **3.4 — H** 카탈로그: VIX_default=1.0, SKEW=118, VKOSPI_zscore=0, credit_quality=calm, real_yields=0. Sentinel 과 정상값 구별 가능성 검토 (예: VIX term ratio 1.0 = 정상 정상장과 같은 값 → staleness 필수).
- [ ] **3.5 — O** silent exception 영역 (breadth, correlation_pca, systemic) 에 logger + attribution 보강.
- [ ] **3.6 — C** 3.1-3.4 에서 발견된 명백한 결함 수정 — 특히 stub fallback 가 prod 에 노출되면 **즉시 raise 또는 sentinel 화** 필요.
- [ ] **3.7 — E** commit: `audit(stage1): market_risk — findings + observability [Task3]`.

**합격 기준:** stub data fallback 이 prod 에 도달하지 못함 (raise 또는 sentinel). systemic_score sentinel 입력 시 method_picker 가 안전한 default 선택.

---

## 7. Task 4 — macro_news analyst

**Files:**
- `tradingagents/agents/analysts/macro_news_analyst.py`
- `tradingagents/skills/news/{event_calendar,news_fetcher,impact_classifier,news_ranker,news_categorizer,news_sentiment,global_overnight,cb_speaker,save_ingestor,release_surprise}.py`
- `tradingagents/schemas/reports.py:153-182` (NewsReport)

**Steps:**
- [ ] **4.1 — L** SAVE brief fallback (line 153) — release_surprises_30d state 가 없을 때 silent N/A 반환. Stage 2 가 이 필드를 어떻게 사용하는지.
- [ ] **4.2 — L** top_n=30 cap 이 (a) cost 보호인지 (b) signal-noise 인지 결정한 후 명시. 30 미만일 때 dilute 여부 확인.
- [ ] **4.3 — H** 카탈로그: top_n=30, sentinel "n/a" 문자열, narrative 500 chars.
- [ ] **4.4 — O** silent exception 영역에 logger + attribution.
- [ ] **4.5 — C** 명백한 결함 수정.
- [ ] **4.6 — E** commit: `audit(stage1): macro_news — findings + observability [Task4]`.

**합격 기준:** SAVE brief 미스 시 prod 가 silent N/A 가 아닌 명시적 "missing — using release_surprises_30d fallback" 로그.

---

## 8. Task 5 — Stage 1 통합 sanity run

**Files (read/run only):**
- `scripts/run_stage1.py` 또는 `gaps stage1 ...` CLI (있다면)
- 없으면 신규 `scripts/audit_stage1_smoke.py` 작성 (4 analyst 한 번 실행 + Report 6 필드 dump).

**Steps:**
- [ ] **5.1** Stage 1 한 번 실행. 4 Report 모두 nominal 생성 확인.
- [ ] **5.2** attribution dict 가 채워졌는지 점검 — 각 analyst 가 자기 영역 로그·sentinel 사용 여부 기록 했는지.
- [ ] **5.3** Task 0 의 sentinel guard 가 작동하는지 — sentinel 강제 injection 후 downstream 에서 fail-fast 또는 안전 처리 확인.
- [ ] **5.4** 회귀: `uv run pytest tests/unit/agents tests/unit/skills -q` 로 전체 테스트 통과 (현재 pre-existing 2 fail 제외).
- [ ] **5.5** Findings 와 audit 요약을 `docs/stage1_audit.md` 마무리 정리.
- [ ] **5.6** commit: `audit(stage1): integration sanity + summary [Task5]`.

**합격 기준:** Stage 1 6 Report 산출물 정상. attribution dict 6 개 모두 채워짐. 회귀 0.

---

## 9. Sign-off Checklist

- [ ] Task 0 — staleness propagation map + guard 추가
- [ ] Task 1 — technical 감사 + observability
- [ ] Task 2 — macro_quant 감사 + observability
- [ ] Task 3 — market_risk 감사 + observability (특히 stub fallback 차단)
- [ ] Task 4 — macro_news 감사 + observability
- [ ] Task 5 — Stage 1 통합 sanity + 회귀 0
- [ ] `docs/stage1_audit.md` 작성: dimension × analyst 매트릭스 + 미해결 사항 list
- [ ] 즉시 수정 못 한 항목은 Stage 2-6 plan / followup_issues 로 이관

---

## 10. 범위 밖

- Stage 2-6 분석가/skill 감사 → 별도 plan
- LLM prompt 재설계 → 별도 작업
- 광범위 test 커버리지 증대 → deadline 후
- 외부 API 의존성 교체 (FRED → 다른 source 등) → 별도 작업

---

## 11. Risk

| Risk | Mitigation |
|---|---|
| 감사 도중 발견된 결함이 회귀 유발 | 분석가별 1 commit · 회귀 테스트 매번 실행 |
| 5/28 마감 시점에 분석가 거동 변경 | Logic-fix 만 적용, refactor 는 deferred |
| stub fallback 차단이 prod 데이터 가용성에 의존 | 차단 PR 전 prod data path 확인 — KRX/FRED creds 있는 환경(친구 Linux)에서 검증 |
