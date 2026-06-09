# Stage 2 시나리오 신호 체계 재설계 — 설계 문서

- 날짜: 2026-06-09
- 상태: 설계 승인됨 (구현 대기)
- 범위: Stage 2(research debate) 출력 + Stage 3(trader allocator) Step A 비중 modifier + 종목 환헤지 선호

## 1. 배경 / 문제

현행 `dominant_scenario`(단일 라벨 5개: kr_boom/kr_stress/global_credit/ai_concentration/neutral)와
`conviction`(high/medium/low)을 실측 검증한 결과 다음 결함이 확인되었다.

- **conviction 死신호**: 산출물 18개 중 17개가 medium(low 0회). 유일 용도인 effective_band 폭
  조절 효과는 low↔high 풀스윙이라도 L1 0.03~0.07로 전체 레버 중 최하위. macro `confidence`와
  역할 중복. → 이미 effective_band에서 제거 완료(2026-06-09, 본 작업 선행 단계).
- **dominant_scenario MECE 위반**: kr 방향성·신용·테마 등 이질적 축을 "하나만 dominant"로 강제해
  복합 상황(예: 방어 + 한국약세 + 환위기 동시)을 표현 불가.
- **ai_concentration 방향 모호**: 실측 최빈(신모델 기준 5/8)인데 modifier가 테크 +0.05(추격)라
  "쏠림 경고"와 "쏠림 추종" 해석이 양립.
- **global_credit 死문자**: 실측 0회 발동.
- **FX 공백**: 한국 거래소 ETF 포트폴리오인데 환위기 시나리오가 없음. 종목 선정에는 환헤지 선호
  로직이 있으나 시나리오 슬롯엔 환이 빠짐.
- **정량/정성 미분리**: fx·credit은 단일 지표의 기계적 분류라 Stage 1에 이미 정량 스냅샷
  (`FXSnapshot.regime`, `FinancialConditionsSnapshot.regime`)으로 존재하는데, 이를 Stage 2 LLM이
  토론으로 재생산 → 중복·왜곡·비결정론.

추가 사실: universe 190 ETF 중 한국주식(b1) 34종이지만 글로벌 주식(b2+b3+b4+b5) 76종으로 2배 이상.
포트폴리오는 글로벌이며, "한국 상대강도"만 별도 축으로 두는 것은 미국·중국·일본 대비 비대칭이다.

## 2. 목표

의미있게 변별되고 비중에 올바른 방향으로 연결되는 신호 체계. 핵심 원칙:

> **단일 지표의 기계적 분류 = Stage 1(정량·결정론). 여러 신호의 종합 판단 = Stage 2(정성·LLM).**

## 3. 설계

### 3.1 신호 체계 — 정량 2 + 정성 1

| 신호 | 소스 | 값 | 단계 |
|---|---|---|---|
| **risk_tilt** | Stage 2 LLM (`ResearchThesis.risk_tilt`, 신규) | strong_offensive / offensive / neutral / defensive / strong_defensive | 정성 |
| **fx_pressure** | Stage 1 `mr.fx.regime` (기존) | krw_strong / krw_weak / usd_risk_off / neutral | 정량 |
| **credit_stress** | Stage 1 `mr.financial_conditions.regime` (기존) | easy / neutral / tight / crisis | 정량 |

- `kr_relative` 축은 **폐기**. 한국 특이성은 fx_pressure(KRW) + regime classifier의 KR 신호(수출/CLI/
  BSI/외국인flow, 이미 quadrant·confidence에 반영) + Step A LLM의 b1 직접 tilt로 커버.
- 기본값 전부 neutral/normal → 평상시 modifier 0 (현 neutral 동작 보존).

### 3.2 스키마 변경

`ResearchThesis` (state['research_decision']):
- **추가**: `risk_tilt: Literal["strong_offensive","offensive","neutral","defensive","strong_defensive"] = "neutral"`
- **삭제**: `dominant_scenario` (및 `ScenarioLabel`/`ScenarioField`/`_coerce_scenario`)
- **삭제**: `conviction` (effective_band에서 이미 미사용 → 필드 제거, risk_tilt가 정성 신호 자리 대체)
- **유지**: `thesis_md`, `key_risks`, `bull_view`, `bear_view`

Stage 1 스냅샷(`FXSnapshot.regime`, `FinancialConditionsSnapshot.regime`)은 **변경 없음** — 이미 산출됨.

### 3.3 비중 매핑 (bucket delta, v1 시드 — 튜닝 대상)

modifier는 baseline에 더해진 뒤 기존 `project_to_band`로 hard band 내 투영된다. 따라서 어떤 modifier도
regime 제약(특히 침체 성장버킷 상단 +0.05)을 넘지 못한다.

**risk_tilt** (5단) — 성장버킷 합 ± → 방어버킷 역방향 재분배(baseline 비중 비례), daily overlay와 동일 원리:
- `strong_offensive` / `offensive`: 성장버킷 합 +0.05 / +0.025
- `neutral`: 0
- `defensive` / `strong_defensive`: 성장버킷 합 −0.025 / −0.05

LLM 숫자 캘리브레이션(제거된 conviction의 死인) 회피 위해 연속 confidence 대신 순서 라벨 5단으로
강도를 표현한다. 실측에서 한 라벨로 수렴하는지 모니터링한다.

**credit_stress** (v1 시드 — 신용 채널 특화; 위험자산 총량 축소는 risk_tilt 가 담당해 중복 회피):
- `tight`: b9_risk_credit −0.02, a3_us_rates +0.02
- `crisis`: b9_risk_credit −0.04, a3_us_rates +0.02, a1_cash +0.02 (flight-to-cash)
- `easy` / `neutral`: 0

**fx_pressure** (비중은 작게, 주로 종목으로):
- `usd_risk_off`: a4_safe_fx +0.03, 성장버킷 소폭 −0.03 (외국인 이탈 방어)
- `krw_weak` / `krw_strong`: 비중 0 — 종목 환헤지 선호로만 작동 (3.4)
- `neutral`: 0

### 3.4 종목 연결 (fx_pressure → 환헤지 선호)

`candidate_selector`의 현 `_UNHEDGED_SCENARIOS = {kr_stress, global_credit}`를 `mr.fx.regime` 기반으로 교체:
- `krw_weak` / `usd_risk_off` → 환노출(UH) 선호 (원화 약세 → 달러표시 자산 환차익)
- `krw_strong` → 환헤지(H) 선호 (원화 강세 → 환차손 방어)
- `neutral` → 선호 없음 (기존 AUM 정렬)

환 신호와 종목 선택을 논리적으로 직결시킨다(현재는 자의적 시나리오 라벨에 묶여 있음).

### 3.5 합성 메커니즘

현 `apply_scenario_modifier(baseline, scenario, hmin, hmax)`를
`apply_macro_modifiers(baseline, risk_tilt, credit_regime, fx_regime, hmin, hmax)`로 일반화.
세 신호의 bucket delta를 **모두 합산**한 뒤 기존 `project_to_band`로 hard band 내 투영(sum=1 보장,
불가 시 baseline fallback). 합성·투영 코드는 검증된 기존 로직 재사용.

### 3.6 Stage 2 출력 / Stage 3 입력 요약

Stage 2 출력(`ResearchThesis`): `risk_tilt`(비중 연결) + `thesis_md`·`key_risks`(Step A 프롬프트) +
`bull_view`·`bear_view`(리포팅).

Stage 3 입력:
- Stage 1 `macro_report`: `regime.quadrant`(baseline 선택), `regime.confidence`(effective_band 폭),
  `fx.regime`(fx modifier + 종목), `financial_conditions.regime`(credit modifier)
- Stage 2 `research_decision`: `risk_tilt`(위험 ± modifier), `thesis_md`·`key_risks`(프롬프트)
- 기존: 요약 텍스트, `technical_report.factor_panel`(vol_haircut), universe_path, capital_krw,
  allocation_feedback

### 3.7 카테고리 cap 충족 보장 (기존 유지 — 명시)

세부자산 category cap(`CATEGORY_CAPS` 10종)은 **이미** 다음 3겹으로 강제·검증되며, 본 재설계로 변경되지
않는다. Step A modifier가 어떤 버킷을 키워도 종목 배분 후단에서 보장된다.

- 강제: `repair_category_caps` → `_repair_all`(category↔risk 3회 교대) + drop_negligible 후 재적용
- 검증: Stage 5 `validate_concentration` (category 초과 시 hard violation)
- 실측(2026-06-09): 전 category cap 이내, "FX 및 원자재" 20.0%/20%로 repair 작동 확인

본 작업은 **중복 로직을 추가하지 않는다.** 대신 "Stage 3 종료 시 모든 category cap 충족(_repair_all +
Stage 5)"을 파이프라인의 명시적 사후 보장 단계로 문서화한다. 새 modifier 도입 후에도 이 단계가 유지됨을
회귀 테스트로 확인한다.

## 4. 영향 범위 (파일별)

| 파일 | 변경 |
|---|---|
| `tradingagents/schemas/research.py` | dominant_scenario·ScenarioLabel·conviction 제거, risk_tilt 추가 |
| `tradingagents/agents/researchers/research_cluster.py` | 매니저 프롬프트 → risk_tilt만 산출 |
| `tradingagents/skills/portfolio/scenario_anchor.py` | SCENARIO_MODIFIER → RISK_TILT/CREDIT/FX modifier; apply_scenario_modifier → apply_macro_modifiers |
| `tradingagents/agents/trader/trader_allocator.py` | mr.fx.regime·mr.financial_conditions.regime 읽어 전달; conviction 추출/attribution → risk_tilt |
| `tradingagents/skills/portfolio/candidate_selector.py` | _UNHEDGED_SCENARIOS → mr.fx.regime 기반 prefer_unhedged/prefer_hedged |
| `tradingagents/reports/philosophy.py` | 리포팅 3신호(risk_tilt/fx/credit) 표시 |
| 테스트 | test_scenario_anchor / test_trader_allocator / test_research_cluster 갱신 |

**비범위**: `bl_views.py`(legacy, force_method=black_litterman 전용, 구 라벨 체계 — 별도 정리 대상),
daily 경로 `validate_rebalance`의 category 검사 여부 점검(별도 실질 개선 항목).

## 5. 마이그레이션

- 구 artifacts/archive의 `dominant_scenario`(단일 라벨, goldilocks 등 legacy 포함)는 deserialize 시
  무시(extra=ignore) 또는 risk_tilt 기본 neutral로 처리. 비중 재현은 백테스트 재생성으로 확보.
- 백테스트 산출물은 재생성(scenario 라벨 혼재 데이터 위생 문제도 함께 해소).

## 6. 테스트 전략

- 단위: `apply_macro_modifiers`가 세 신호 합성 후 sum=1·hard band 이내 보장, 불가 시 baseline fallback.
- 방향 검증: risk_tilt(off/neutral/def), credit(tight/crisis), fx(usd_risk_off) 각각이 의도한 버킷을
  의도한 방향으로 움직이는지.
- 종목: fx.regime별 prefer_unhedged/prefer_hedged 분기.
- 회귀: 기존 unit 1036 통과 유지(특히 neutral/normal 입력 시 현 동작과 동일).
- 사후 보장: 재생성 산출물에서 전 category cap·risk cap 충족(실측 검증 스크립트).
