# Architecture Review — pluto / tradingagents

- **작성일:** 2026-05-24
- **범위:** stage 1 → 6 전체 파이프라인 (whole-pipeline sweep)
- **방법:** 4개 Explore 에이전트 병렬 탐색 → 코드로 직접 검증 → deepening 후보 distill
- **렌즈:** "shallow module을 deep module로" (improve-codebase-architecture skill)
- **용어:** module / interface / implementation / depth / shallow / **seam** / adapter / leverage / locality.
  도메인 명칭(stage 1–6, factor F1–F9, bucket, cluster)은 `docs/stage*.md` 기준.
  > 이 repo엔 CONTEXT.md / docs/adr/ 가 없음. 아키텍처 용어는 skill glossary, 도메인은 docs/stage*.md.

각 문제는 **interface가 implementation만큼 복잡한가(shallow)**, **무언가가 seam을 가로질러 새는가(leaky)**, 그리고 **deletion test**(이 module을 지우면 복잡도가 사라지는가 vs N개 호출부로 재출현하는가)로 판정.

---

## Index

| # | 문제 | 영역 | 검증 | 강도 | PR2a 중첩 |
|---|---|---|---|---|---|
| AP1 | cluster cap이 4개 stage로 쪼개짐 + optimizer enforcement가 죽은 코드 | stage 3–5 | ✅ 코드 검증 | High | 없음 |
| AP2 | 무타입 `AgentState` blob 위 암묵적 stage seam + partial-return contract 누수 | cross-cutting | ✅ 코드 검증 | High (invasive) | 없음 |
| AP3 | vendor seam의 비대칭 fallback — 공유 interface 없는 2 adapter | dataflows | ✅ 코드 검증 | Medium | 저(soft adjacency) |
| AP4 | factor 정의가 4개 module·9개 함수로 흩어짐 (field-path scatter) | stage 2 | ✅ 코드 검증 | High | **직접 충돌** |
| AP5 | analyst node가 fat orchestrator — report assembly에 module이 없음 | stage 1 | ✅ 코드 검증 | Medium | 없음(개념적 연관) |
| AP6 | skill registry shallow + 등록 모듈 리스트가 2벌(test/prod)로 발산 | cross-cutting | ✅ 코드 검증 | Medium | 없음 |
| AP9 | DEFAULT_CONFIG 무타입 flat dict — 검증 없음, publication_lag 수동 동기화 | cross-cutting | ✅ 코드 검증 | Medium | 없음 |
| AP10 | factor_to_bucket safety/contract 취약 — QP 실패 silent baseline + to_dict↔FACTORS key 미검증 | stage 2 | ✅ 코드 검증 | Medium | **충돌** |
| AP7 | "risk asset" 정의가 set literal + property sum에 이중 하드코딩 | stage 3,5 | ✅ 코드 검증 | Low | 없음 |
| AP8 | optimizer constraint 구성 중복·발산 — pass마다 1차 제약(bond split, cluster cap) 소실 | stage 3–4 | ✅ 코드 검증 | High | 없음 |
| AP11 | orchestration 모듈이 allocation business logic 보유 — 3번째 optimizer + universe-결합 emergency cash | graph, allocator | ✅ 코드 검증 | High | 없음 |
| AP12 | Stage1 스키마 sentinel 모호성 (0.0 vs 부재) → 가짜 signal 주입 | schemas | ✅ 코드 검증 | Med | 저 |

> **AP1 ⊂ AP8 ⊂ AP11:** cluster cap 소실(AP1)은 AP8(2차 pass가 1차 제약을 흘림)의 인스턴스이고, AP8은 다시 AP11의 부분집합 — "mandate-safe 최적화"가 **세** 모듈(allocator 1차, overlay 2차, conditional_logic fallback)에 중복·발산. AP1=cap+멤버십 표현, AP8=pass 간 constraint-builder 중복, AP11=orchestration이 business logic 보유.

---

## AP1 — Cluster cap이 4개 stage로 쪼개짐 + optimizer enforcement가 죽은 코드

**강도:** High · **검증:** 코드 검증 완료 · **PR2a 중첩:** 없음

### Problem

"correlation cluster exposure 제한"이라는 **한 개념**이 4개 stage에 분산되어 있고, 그 과정에서 **cap 숫자와 cluster 멤버십이 분리**된다. 결정적으로 — 유일하게 proactive enforcement가 일어나야 할 지점(Stage 3 2차 optimizer)이 **죽은 코드(`pass`)** 다.

Cluster cap = 한 correlation cluster(함께 움직이는 종목 묶음, 예: AI/Semi)에 속한 ticker들의 weight 합 상한. 단일 종목 cap(20%)만으로는 못 막는 "분산 착시"(NVDA 18%+AMD 12%+TSM 10% = 사실상 한 베팅 40%)를 막는 2차 방어선. baseline = 0.25.

### Evidence (file:line)

- `schemas/technical.py:36` — `Cluster{cluster_id, members: list[str], avg_internal_correlation, category_label}`. 멤버십은 여기 존재.
- `skills/risk/portfolio_metrics.py:74` — `_compute_cluster_exposure(weights, clusters)` → `{cluster_id: 합}`. clusters(멤버십)를 **입력으로 받지만 출력은 id→숫자**만, 멤버십을 하류로 안 넘김.
- `agents/risk_lens/concentration_lens.py:70-77` — level별 strict cap 제안: critical→`{top1_id: 0.18}`, high→`{top1_id: 0.22}`. **cluster_id로 keying.**
- `skills/risk/severity_aggregator.py:27-31` — 여러 lens cap을 최솟값(strictest)으로 머지 → `RiskOverlay.cluster_caps {cluster_id: cap}`.
- `agents/allocator/overlay_apply.py:176-179` — ⚰️ **죽은 코드**:
  ```python
  if overlay.cluster_caps:
      # Phase 1에서는 cluster_caps 적용 skip (Stage 1 cluster id ↔ ticker
      # 매핑이 별도 state 필요). Phase 2에서 wire.
      pass
  ```
  optimizer는 `overlay.cluster_caps`(id→cap)와 `sector_mapper`(ticker→bucket)만 있고 **cluster_id→members를 모름** → group 제약을 못 만듦.
- `skills/mandate/correlation_check.py:8-21` — Stage 5 validator는 `clusters`(멤버십 있음!)를 받아 멤버 합 ≤ **0.25**(고정) 검사. 단 lens의 strict 0.18/0.22는 **무시**, retry는 위반 cluster를 콕 집지 않는 blind retry.
- `agents/allocator/portfolio_allocator.py:243-244` — Stage 3 1차 optimizer는 `weight_bounds=(0,0.20)` + `add_sector_constraints`만, **cluster 제약 없음**.

### Architecture reading

- **leaky seam:** cap(숫자)과 멤버십(ticker들)이 다른 module에 분리. 둘을 잇는 `cluster_id → members` 링크가 enforce가 필요한 optimizer까지 **연결된 적이 없음**.
- **진짜 seam:** "cluster exposure 제한"의 소비자가 **둘** — optimizer(제약으로 enforce) + validator(check). (one adapter = 가짜 seam, two = 진짜 seam.) 그런데 둘이 같은 표현을 공유하지 않음.
- **deletion test:** `concentration_lens`의 cluster_caps를 지워도 production 동작 0 변화 (optimizer가 `pass`로 버리므로). → 현재 그 cap 계산은 **제값을 못 하는 dead module**.
- pypfopt는 이미 `add_sector_constraints`로 group 제약 지원 → **cluster cap은 구조적으로 bucket sum 제약과 동일**. 멤버십만 배선하면 enforce 가능.

### 순효과

- cluster cap을 proactive하게 적용하는 stage가 **없음**. 오직 Stage 5의 사후 0.25 검사뿐.
- Stage 4의 strict cap(0.18/0.22)은 **어디에도 적용 안 되는 죽은 값**.
- Stage 5 위반 → 목표 없는 retry → 종종 emergency fallback.

### Deepening direction (interface 미확정 — grilling 대상)

- **통합 constraint 표현:** cap+멤버십을 자기서술적 객체로 융합 (`ClusterCap{cluster_id, members, cap, label}`). optimizer와 validator가 **같은 표현**을 소비 → 단일 seam.
- **단일 enforce/check module:** clusters+caps → (a) pypfopt group 제약 생성 + (b) weight vector 검증. optimizer와 validator가 동일 module 호출.
- **책임 분리 결정 유지:** `concentration_lens` docstring의 ADR급 결정 — "baseline 0.25는 Stage 5 소유, Stage 4는 strict-only 제안 (옵션 A-1)". deepening은 이걸 뒤집지 않고, baseline·strict cap이 **같은 표현·같은 module**을 통과하게만 함.
- **결정할 분기:** (1) 통합 객체 vs 최소 배선, (2) 1차 pass에도 적용할지, (3) infeasibility half-strength fallback에 cluster cap 포함 (line 100 `half_caps`가 이미 절반 있음).

### Scope / blast radius

stage 3–5 내부로 국한: `risk_overlay.py`(스키마), `concentration_lens.py`, `severity_aggregator.py`, `overlay_apply.py`, `correlation_check.py`, `portfolio_metrics.py`. 외부 stage·schema 무영향.

---

## AP2 — 무타입 `AgentState` blob 위 암묵적 stage seam + partial-return contract 누수

**강도:** High (invasive) · **검증:** 코드 검증 완료 · **PR2a 중첩:** 없음

### Problem

6개 stage 전부가 하나의 무타입 공유 dict(`AgentState`)를 통해 통신한다. stage 간 seam이 "그 순간 dict에 들어있는 key가 무엇이든"이다 — 어떤 stage도 자신의 입력/출력을 선언하지 않으므로 누락 field가 조용히 degrade된다.

### Evidence (file:line)

- `agents/utils/agent_states.py:19` — `class AgentState(MessagesState)` (LangGraph). **Pydantic 아님** → 런타임 검증 없는 TypedDict 스타일, ~95 field 다수 Optional.
- 소비는 `.get()` + magic default:
  - `agents/managers/risk_judge.py:42` — `risk_report` 없으면 `systemic_score=5.0` 등 마법 기본값 주입.
  - `agents/allocator/portfolio_allocator.py:49-50` — `regime`/`risk_score`를 `.get()` 후 None 분기.
- **partial-return contract 누수** — `risk_judge.py`:
  - 정상 return(`:171`): `{weight_vector, risk_overlay, portfolio_numerics, risk_debate_summary}` 4키.
  - early return(`:82` 입력 부재, `:105` returns 부재): `{risk_overlay, risk_debate_summary}` 2키 — **`weight_vector`/`portfolio_numerics` 생략**.
  - LangGraph는 node 반환 dict를 state에 merge → early return 시 allocator가 설정한 **overlay 적용 전** `weight_vector`가 조용히 잔존, `portfolio_numerics`는 None. hard crash는 아니지만 "overlay skipped" 신호가 없는 **암묵적 contract**.
- `presets/spec.py:25` — `AgentSpec.input_from: dict[str,str]` (stage 입력 매핑)이 선언돼 있으나 **graph builder가 소비하지 않는 dead code** (repo 전체에서 정의·docstring 외 참조 0).

### Architecture reading

- **no locality:** 변경/버그/지식이 한 곳에 모이지 않고 ~95 key dict 전역에 흩어짐. PR1이 고친 17개 field-path 버그가 이 fragile seam의 증거.
- **shallow seam:** stage 간 계약이 "dict에 우연히 있는 key". 누락이 예외가 아니라 silent degradation(magic default)으로 흡수됨.
- **dead seam:** `input_from`은 의도된 stage-입력 seam이었으나 구현되지 않음 → 선언과 실제 동작 불일치.

### Deepening direction

- stage별 **typed input/output contract**를 seam에 부여 — 각 stage가 무엇을 소비/생산하는지 명시, partial-state 케이스를 강제로 처리.
- dead `input_from`을 **되살리거나 삭제** (ambiguity 제거).
- ⚠️ **주의:** LangGraph가 state 형태를 제약 → 공유 store를 *제거*하는 게 아니라 *seam을 깊게* 만드는 것. 6개 중 blast radius 최대.

### Scope / blast radius

cross-cutting, 전체 파이프라인. 가장 invasive — 단계적(stage 하나씩 typed contract) 접근 권장.

---

## AP3 — Vendor seam의 비대칭 fallback (공유 interface 없는 2 adapter)

**강도:** Medium · **검증:** 코드 검증 완료 · **PR2a 중첩:** 저(soft adjacency)

### Problem

데이터 vendor(yfinance / alpha_vantage)가 문자열 dict dispatch로 선택되고 공유 interface가 없다. fallback이 rate-limit 한 종류만 잡아, 플랫폼별 실패(Windows yfinance SSL 등)가 호출부로 바로 샌다.

### Evidence (file:line)

- `dataflows/interface.py:69-110` — `VENDOR_METHODS = {method: {vendor: impl_fn}}`. method마다 2 adapter(yfinance, alpha_vantage), 각자 다른 시그니처·에러 모드, **공유 Protocol/ABC 없음**.
- `dataflows/interface.py:134-162` — `route_to_vendor`: fallback 체인을 만들지만 `try/except` 가 **`AlphaVantageRateLimitError`만** 잡음(`:159`). 그 외 예외(network, parse, Windows SSL)는 즉시 전파 → fallback 안 됨. → **비대칭 robustness** (alpha_vantage rate-limit만 보호).
- 설정은 문자열: `"yfinance,alpha_vantage"`를 콤마 split(`:138`), vendor 이름 검증 없음.

### Architecture reading

- **two adapters = 진짜 seam** — yfinance + alpha_vantage 둘 다 prod에 실재 → seam은 정당. 그러나 adapter들이 공유 interface(uniform error mode)로 묶이지 않아 seam이 얕음.
- **leaky:** 한 adapter의 에러 모드가 호출부로 새어 fallback이 비대칭.
- PR2a 연관: PR2a의 신규 fetcher는 `dataflows.fred.fetch_fred_series` / pykrx를 **직접 wrap**(이 `route_to_vendor` 경로 비경유) → 파일 충돌 없음. 단 Windows yfinance/pykrx 실패(#20/#21)가 PR2a fetch를 막은 동일 뿌리.

### Deepening direction

- 단일 fetcher **interface**(uniform error mode) 정의 → vendor들 + cache/fake가 그 seam의 adapter.
- cache/fake adapter = Linux 전용 fetch를 Windows에서 테스트 가능하게 → PR2a fetch 고통 직접 완화.

### Scope / blast radius

`dataflows/` 국한. 호출부는 `route_to_vendor` 시그니처 유지 시 무영향.

---

## AP4 — Factor 정의가 4개 module·9개 함수로 흩어짐 (field-path scatter)

**강도:** High · **검증:** 코드 검증 완료 · **PR2a 중첩:** ⚠️ **직접 충돌 — 구현은 PR2a와 조율/연기**

> 친구가 맡은 PR2a가 `factor_estimators.py`에 `mode="historical"` + `FACTOR_DEFINITIONS`/`NEWS_DERIVED_COMPONENTS`를 도입 예정. 이 deepening과 같은 파일·같은 개념을 건드림. **분석은 기록하되 구현은 PR2a 머지 후 또는 친구와 조율.**

### Problem

한 factor의 정의 — 스키마 경로, weight, baseline, reliability cap, news-vs-quant 분류 — 가 4개 module과 9개 hand-written 함수에 명령형으로 흩어져 있다. 한 factor를 이해/변경하려면 ≥4곳을 만져야 한다.

### Evidence (file:line)

- `skills/research/factor_estimators.py:236-292` (`compute_growth_surprise`, F1 대표) — ~10개 `_safe_get(stage1, "macro_report", "gdp_nowcast", "nowcast_pct")` 문자열 경로 추출 + inline `components_raw` dict + inline `weights` dict → `_aggregate(...)` 호출. **이 패턴이 9개 factor에 반복.**
- `skills/research/factor_estimators.py:118-139` (`_safe_get`) — 모든 예외를 삼켜 None 반환 → 경로가 틀려도 silent z=0. Stage 1 스키마를 **문자열로** 인코딩.
- `skills/research/factor_baselines.py` — `LONG_RUN_BASELINE[(factor, component)] = (mean, sd)` 별도 테이블.
- `skills/research/factor_reliability_audit.py` — `COMPONENT_RELIABILITY` → weight cap 별도 테이블.
- `skills/research/factor_estimators.py:142-216` (`_aggregate`) — none-drop → z-score → cap → renorm → clip. **deep 엔진**(9 factor 공유).
- PR0/PR1 history: **17개 silent field-path 버그**를 한 commit에서 수정. 테스트는 mock fixture를 쓰므로 fixture와 코드가 같이 틀려 버그가 같이 숨음 → **false testability**.

### Architecture reading

- **concept scatter:** "F1 z가 raw field에서 어떻게 나오나"를 알려면 4 module + 1 dataclass를 오감.
- **shallow leverage:** `_aggregate`는 deep하나, 그 위 9개 compute 함수는 모든 경로·weight를 caller가 학습해야 함 → 인터페이스가 거대.
- **deletion test:** inline weights/paths를 지우면 9개 compute 함수로 복잡도 재출현. declarative 정의가 이를 한 곳으로 응축.
- **테스트 표면:** 선언된 경로 전체를 **실제 Pydantic 스키마**(mock 아님)에 대해 검증하는 단일 테스트가 가능 → 17개 버그類가 구조적으로 불가능해짐.

### Deepening direction

- 각 factor를 **declarative definition**(component마다 path, weight, baseline, reliability, news-derived?)으로 — 데이터 한 곳. `compute_all_factors`는 정의를 순회해 기존 deep `_aggregate`에 투입.
- news-derived 플래그가 정의 field가 되면 PR2a의 `mode="historical"`(news weight 0 + renorm)가 자명해짐 → **이 deepening이 PR2a를 직접 가능하게 함**. 그래서 조율 필요.

### Scope / blast radius

`skills/research/` 국한. **단 PR2a와 동일 파일** → 구현 순서 조율 필수.

---

## AP5 — Analyst node가 fat orchestrator (report assembly에 module이 없음)

**강도:** Medium · **검증:** 코드 검증 완료 · **PR2a 중첩:** 없음(개념적 연관)

### Problem

데이터 기반 analyst(`macro_quant_analyst` 567줄, `market_risk_analyst` 446, `macro_news_analyst` 224)가 다수 skill을 import하고 각각 try/except→sentinel로 감싼 뒤 scalar를 snapshot에 `model_copy`로 fold-in 한다. "stage-1 report를 조립한다"는 개념이 자기 module 없이 node 안에 inline으로 산다.

### Evidence (file:line, 검증됨)

- `agents/analysts/macro_quant_analyst.py` — `from tradingagents.skills` import **24줄**, `_sentinel_*` 생성자 **14개**, `model_copy` fold-in **6개**. node 1개가 24개 skill을 선형 오케스트레이션.
- **summary helper가 analyst마다 재구현:** `technical_analyst.py`에 `_summarize_extended/_summarize_risk_adjusted/_summarize_trend_quant` (3개), `macro_news_analyst.py`에 `_summarize_overnight/_save/_speakers/_sentiment/_surprise` (5개). 같은 "snapshot→markdown 요약" 패턴이 analyst별 별도 구현.
- 오케스트레이션을 단위 테스트하려면 24개 skill mock 필요 — 진짜 버그는 skill이 아니라 wiring(sentinel/fold-in)에 있는데 거기엔 locality가 없음.

### Deepening direction

- "skill로부터 stage-1 report 조립"을 stage별 **deep report-builder module**로 — invoke→sentinel→fold 패턴을 한 곳에 소유. node는 thin LangGraph wrapper, 오케스트레이션은 LLM/graph 없이 단위 테스트.
- ⚠️ 진짜 deep builder여야 함 — 같은 30개 호출을 re-export하는 shallow "registry"가 되면 무의미.
- PR2a 연관: PR2a의 `backtest/historical/stage1_builder.py`(date-parameterized reconstruction)와 **개념적 형제** — 파일 충돌은 없음.

### Scope / blast radius

`agents/analysts/` 국한. 큼 — 진짜 deep builder로 (shallow re-export 금지).

---

## AP6 — Skill registry shallow + 등록 모듈 리스트가 2벌(test/prod)로 발산

**강도:** Medium · **검증:** 코드 검증 완료 · **PR2a 중첩:** 없음

### Problem

`skills/registry.py`가 dict put/get wrapper로 등록 시 시그니처·IO 검증을 안 하는 **shallow** lookup이다. 게다가 "등록할 모듈 목록"이 **두 곳에 따로** 존재하고 **이미 발산**했다 — 새 skill을 한 곳에만 넣으면 조용히 미등록되는 위험이 실제로 발현됨.

### Evidence (file:line, 검증됨)

- `skills/registry.py:44-73` — `@register_skill`/`@register_subagent`는 `_REGISTRY[name] = {...}` dict put만, **시그니처·IO 검증 없음**. `get_skill`은 miss 시 KeyError.
- **모듈 리스트 2벌 + 발산:**
  - `skills/registry.py:5-41` — `_SKILL_MODULES` (test-only `_reregister_all_skills`에서만 사용, `:106`).
  - `skills/_registry_init.py:5-48` — production side-effect import 리스트.
  - **불일치:** `macro.real_activity`, `macro.kr_valuation`, `risk.realized_volatility`, `risk.sector_dispersion` 가 test-only 리스트엔 있으나 **production init엔 없음**. → 해당 skill이 prod에서 미등록이거나 다른 경로로 등록됨 = registry가 신뢰할 single 등록 seam이 아님.

### Architecture reading

- **shallow:** interface(get_skill/register)가 implementation(dict put/get)만큼 단순.
- **no locality:** 등록 대상 목록이 2곳 → 한쪽만 고치면 drift (이미 4개 drift 발생).
- **deletion test:** registry를 지우면 caller가 skill 함수를 직접 import (대부분 이미 그럼) → 복잡도 거의 재출현 안 함 = pass-through에 가까움. 단 위 drift는 실재 위험.

### Deepening direction

등록을 **discovery로 흡수**(import 시 자동 등록 + 단일 import 지점)하거나, preset-time IO 검증이 목표일 때만 깊게. 최소한 두 리스트를 하나로 합쳐 drift 제거.

### Scope / blast radius

`skills/registry.py` + `_registry_init.py` 국한. drift 정리는 작고 즉시 가치 있음.

---

## AP7 — "risk asset" 정의가 set literal + property sum에 이중 하드코딩

**강도:** Low · **검증:** 코드 검증 완료 · **PR2a 중첩:** 없음

### Problem

"어떤 bucket이 위험자산인가(대회 §2.2 70% cap 대상)"라는 정의가 두 곳에 독립적으로 하드코딩돼 있다. 6번째 위험 bucket이 추가되면 두 곳을 따로 고쳐야 한다.

### Evidence (file:line)

- `skills/mandate/concentration_check.py:18` — `RISK_BUCKET_NAMES = {"kr_equity","global_equity","fx_commodity"}` (set literal).
- `schemas/portfolio.py:37-39` — `BucketTarget.risk_asset_weight` property = `kr_equity + global_equity + fx_commodity` (동일 3개를 하드코딩 sum).
- 두 곳이 같은 "위험 3-bucket" 개념을 다른 형태로 인코딩 + 다른 레벨에서 계산 (property는 **bucket target**, RISK_CATEGORIES는 final **ticker weight** via category lookup).

### Architecture reading

- **이미 부분 완화됨 (정직한 평가):** `RISK_CATEGORIES`는 `BUCKET_TO_CATEGORIES`(candidate_selector)에서 **파생** → bucket→category 매핑 자체는 단일 truth source. docstring이 의도 명시.
- **남은 leak:** "위험 3-bucket"이라는 집합이 set literal과 property sum에 중복. 약한 concept scatter. agent의 "이중 truth source/silent divergence" 주장은 **과장** — 실제론 mild.

### Deepening direction

"위험 bucket 집합"을 단일 상수로 두고 property·validator가 그것을 참조. 낮은 우선순위 — 기록용.

### Scope / blast radius

`schemas/portfolio.py` + `skills/mandate/concentration_check.py`. 작음.

---

## AP8 — 두 optimizer pass의 constraint 구성이 중복·발산 (2차가 1차 제약을 흘림)

**강도:** High · **검증:** 코드 검증 완료 · **PR2a 중첩:** 없음 · **AP1을 포함**

### Problem

Stage 3 optimizer가 **두 번** 호출된다 — 1차(allocator)와 overlay 적용 2차(overlay_apply). 두 곳이 "target+overlay → pypfopt 제약"을 **각각 따로** 구성하는데, 2차가 1차의 일부 제약을 **소실**한다. 즉 "optimizer를 어떻게 제약하는가"가 한 deep module이 아니라 두 발산된 복제본이다.

### Evidence (file:line)

- 1차: `agents/allocator/portfolio_allocator.py:143-200` (`_build_sector_mapper_and_bounds`) + `:243-244` —
  - bond를 `bond_tips`/`bond_nominal` sub-sector로 **split** (`bond_tips_share` intent enforce, `:158-188`).
  - `weight_bounds=(0,0.20)` 단일 cap + `add_sector_constraints`.
- 2차: `agents/allocator/overlay_apply.py:114-179` (`_solve_with_overlay`) —
  - `target_map`에 bond를 **단일 "bond"로** (`:137`) → **TIPS/nominal split 소실**. overlay가 발동하면 1차가 빚어낸 bond_tips_share intent가 조용히 사라짐.
  - cluster_caps는 `pass` (`:176-179`) → **cluster 제약 소실** (= AP1).
  - per-ticker ceiling/floor는 새로 lambda constraint로 추가 (1차엔 없는 것).

### Architecture reading

- **locality 실패:** "target+overlay → optimizer 제약"이라는 한 책임이 두 함수에 분산·발산. 1차에 제약을 추가해도 2차에 자동 반영 안 됨(역도 마찬가지) → 표류.
- **leaky/lossy seam:** 2차 pass는 1차의 제약 builder를 재사용하지 않고 부분 재구현 → bond split·cluster cap을 흘림. overlay 경로로 빠지는 순간 mandate intent가 약화됨.
- **deletion test:** 2차의 제약 구성 로직을 1차와 공유 module로 합치면, 두 pass가 동일 제약 집합을 보장 → AP1·bond-split 소실이 동시 해결.

### Deepening direction

- "BucketTarget(+overlay) → pypfopt 제약 집합"을 **단일 deep constraint-builder module**로. 1차는 overlay 없이, 2차는 overlay 포함해 같은 builder 호출. bond split·cluster cap·single cap·sector sum이 한 곳에서 정의.
- AP1(cluster cap 표현)과 함께 해결하면 시너지: builder가 `ClusterCap{members,cap}`를 group 제약으로 변환.

### Scope / blast radius

`agents/allocator/` (portfolio_allocator + overlay_apply) 국한. AP1과 함께 다루면 효율적.

---

## AP9 — `DEFAULT_CONFIG` 무타입 flat dict (검증 없음, 수동 동기화)

**강도:** Medium · **검증:** 코드 검증 완료 · **PR2a 중첩:** 없음

### Problem

전역 설정이 스키마 없는 flat dict 하나(`DEFAULT_CONFIG`)로, 10개 파일이 직접 import한다. key 오타·누락이 런타임까지 silent하고, `publication_lag_days`(~60 entry)는 FRED series와 수동 동기화해야 한다(누락 시 look-ahead bias).

### Evidence (file:line)

- `default_config.py:5` — `DEFAULT_CONFIG = {...}` flat dict. nested: `data_vendors`(`:41`), `tool_vendors`(`:48`), `subagent_model_policy`(`:60`), `publication_lag_days`(`:77`, ~60 entry). **Pydantic/TypedDict 스키마 없음.**
- API key는 `os.getenv(...)` → 미설정 시 `None`이지만 타입 힌트상 optional 표시 없음 (`:67-69`).
- `from tradingagents.default_config import DEFAULT_CONFIG` 직접 import **10개 파일** → 단일 진입점 없음.
- `publication_lag_days`는 새 FRED series 추가 시 수동 등록 필요, 누락 시 lag 0 (point-in-time 위반).

### Architecture reading

- **shallow + no locality:** "설정 계약"이 코드 어디에도 명시 안 됨. 어떤 key가 필수인지, 타입이 무엇인지 caller가 추측. 변경이 한 곳에 모이지 않음.
- **leaky:** `publication_lag_days`처럼 다른 module(FRED series 정의)과 동기화돼야 하는 데이터가 config에 분리 → drift 위험.

### Deepening direction

`DEFAULT_CONFIG`를 typed config(Pydantic Settings 등)로 — 필수 key·타입·기본값을 한 곳에 선언, 단일 접근 module. `publication_lag_days`는 FRED series 정의와 co-locate.

### Scope / blast radius

`default_config.py` + 10개 import 지점. 점진 적용 가능 (typed wrapper 도입 후 호출부 이전).

---

## AP10 — factor_to_bucket safety/contract 취약 (QP 실패 silent baseline + key 미검증)

**강도:** Medium · **검증:** 코드 검증 완료 · **PR2a 중첩:** ⚠️ **충돌 (factor_to_bucket/factor_estimators — PR2a 파일)**

> AP4와 동일하게 PR2a가 건드리는 파일. 분석만 기록, 구현은 조율/연기.

### Problem

(a) QP projection이 실패하면 조용히 `INITIAL_BASELINE`으로 되돌아가는데 caller가 "성공했지만 크게 projection됨"과 "완전 실패→baseline"을 구별할 신호가 없다. (b) `FactorScores.to_dict()` key와 `FACTORS` 튜플이 일치한다는 보장이 없어, 어긋나면 factor가 silent z=0이 된다.

### Evidence (file:line)

- `skills/research/factor_to_bucket.py:245` `project_to_mandate_qp` — optimizer 실패 시 `return dict(INITIAL_BASELINE)` (`:313-314`, `:319`). silent revert.
- `:329` `apply_factor_model_with_safety` — diagnostics에 `projection_intervened`(l2>0.01, `:369`)는 있으나 **QP 완전 실패 여부를 구별하는 별도 flag 없음** → "큰 projection"과 "fallback"이 같은 신호로 보임.
- `:221` `z = float(factor_z.get(f, 0.0))` for f in `FACTORS` — `FactorScores.to_dict()`(factor_estimators.py:83)가 만든 key가 `FACTORS`와 다르면 **silent z=0**. 둘이 일치한다는 검증 없음(둘 다 하드코딩).

### Architecture reading

- **leaky/silent degradation:** safety fallback이 신호 없이 baseline으로 → 모델이 죽었는지 caller가 모름.
- **key-naming contract:** 두 하드코딩 목록(`to_dict` key ↔ `FACTORS`)이 암묵 계약. 검증 부재 = AP4의 field-path 취약성과 동류.

### Deepening direction

- QP 실패를 diagnostics에 명시 flag(`qp_failed`)로 — fallback과 정상 projection 구분.
- `to_dict` key를 `FACTORS`에서 파생하거나 단일 enum으로 — 어긋남을 구조적으로 차단 (AP4 declarative factor definition과 함께 해결).

### Scope / blast radius

`skills/research/factor_to_bucket.py` (+ to_dict는 factor_estimators.py). **PR2a 동일 파일** → 구현 조율 필수.

---

## AP11 — Orchestration 모듈이 allocation business logic 보유 (3번째 optimizer + universe-결합 fallback)

**강도:** High · **검증:** 코드 검증 완료 · **PR2a 중첩:** 없음 · **AP8을 포함**

### Problem

라우팅만 해야 할 graph 모듈(`conditional_logic.py`)이 portfolio allocation business logic을 품고 있다 — 완전한 constrained 재최적화(`fallback_normalizer`)와 universe 구조에 결합된 emergency cash 포트폴리오. 이는 (allocator 1차, overlay 2차에 이은) **3번째** 독립 "20% cap 하 최적화"이며, 셋이 발산해 있다.

### Evidence (file:line)

- `graph/conditional_logic.py:48-50` — `EfficientFrontier(None, S, weight_bounds=(0,0.20)); ef.min_volatility()` → **3번째 constrained optimizer**. returns_matrix·pypfopt·risk_models를 orchestration 모듈이 직접 import(`:41,46`).
- `:131-169` `_emergency_cash_portfolio` — `e.bucket == "안전"` (universe 구조 하드코딩), "5 ETF" 휴리스틱, single-cap 위반 시 경고만. business logic이 router에 inline.
- **mandate 재검증 우회:** `fallback_normalizer`(`:69-72`)와 emergency(`:166-169`) 모두 `validation_passed=True`를 무조건 set. 그런데 `min_volatility`는 **단일 20% cap만** 보장 — bucket 합, 위험자산 70% cap(AP7), cluster cap(AP1)은 보장 안 됨. → fallback 산출물이 이 mandate들을 위반해도 "valid"로 finalize됨.

### Architecture reading

- **no locality:** "mandate-safe 포트폴리오를 만든다"가 allocator·overlay_apply·conditional_logic **세 모듈/세 layer**에 분산. cap 룰·새 제약 추가 시 3곳 수정, 이미 발산(fallback은 sector/bucket/cluster/TIPS 제약 전무).
- **leaky seam:** orchestration이 allocation·universe·data-fetch에 결합 → router를 테스트하려면 optimizer+fetch를 끌고 옴.
- **correctness 위험:** 최종 안전망이 단일 cap만 보장하면서 전체 mandate를 통과한 것처럼 표시.

### Deepening direction

constrained-optimization 책임을 단일 **mandate-safe optimizer module**로 — allocator/overlay/fallback이 모두 동일 module 호출(동일 제약 집합 보장, AP8 해결). emergency cash는 inline이 아니라 정의된 allocator strategy. router는 finalize/retry/fallback 결정만 하는 thin 상태로.

### Scope / blast radius

`graph/conditional_logic.py` + `agents/allocator/`. AP1·AP8과 함께 단일 optimizer module로 통합 시 동시 해결.

---

## AP12 — Stage 1 스키마의 sentinel 모호성 (0.0 vs 부재 → 가짜 signal 주입)

**강도:** Medium · **검증:** 코드 검증 완료 · **PR2a 중첩:** 저(스키마는 무관, factor 소비는 인접)

### Problem

Stage 1 report 스키마가 누락 field를 `default=0.0` / `| None = None`으로 채운다. 소비자가 "실측 0.0"과 "field 부재"를 구별할 수 없고, factor model은 0.0을 **실제 z-input**으로 취급해 가짜 signal을 주입한다.

### Evidence (file:line)

- `schemas/macro.py` — `default=0.0` field **13개** (`pce_yoy`, `core_pce_yoy`, `pce_momentum_3mo`, `spread_30y_5y_bps` 등 `:28,42,45,48,60,…`).
- `factor_estimators.py:118-139` `_safe_get` — None이면 skip(컴포넌트 제외)이지만, **0.0은 살아남아** baseline 대비 z로 계산됨. 예: 누락→`pce_yoy=0.0`이 "PCE 0% YoY"(강한 disinflation 신호)로 둔갑.
- backward-compat: field 추가 시(`pce_yoy` 2026-05) 옛 archive는 0.0으로 deserialize → 과거/replay run에 가짜 0% 주입.

### Architecture reading

- **leaky/silent:** "부재"가 "실측 0"으로 둔갑 → confidence down-weight도 불가. AP4의 field-path 취약성과 결합되면 silent-wrong-signal이 한 부류를 이룸.
- **interface 결함:** 스키마가 "이 field는 unavailable"을 표현할 수단이 없음.

### Deepening direction

부재를 0과 구별 — Optional(None="unavailable", 소비자/`_safe_get`이 skip), 0.0은 실측 전용. 또는 field별 presence/quality flag. 그러면 sentinel-aware confidence가 정확해짐.

### Scope / blast radius

`schemas/macro.py`·`reports.py` + factor_estimators 소비부. 스키마 자체는 PR2a 무관, 소비 해석은 인접 → 조율 권장.

---

## 참조

- HTML 리포트 (before/after 시각화): `%TEMP%/architecture-review-20260524-163923.html` (휘발성)
- 아키텍처 용어집: improve-codebase-architecture skill `LANGUAGE.md`
- 도메인 stage 문서: `docs/stage1.*` ~ `docs/stage6.*`
- PR2a (친구 담당): `docs/superpowers/specs/2026-05-23-stage2a-calibration-design.md`
- 기존 이슈 백로그: `docs/followup_issues.md`
