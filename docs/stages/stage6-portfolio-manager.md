# Stage 6 — Portfolio Manager (final artifacts production)

> 파이프라인 6 stage 중 마지막 단계. Stage 5 (Mandate Validator)를 통과한 weight_vector + Stage 1-4 산출물 전체를 받아 **운영자/심사자가 보는 3개 산출물**을 생성. 매월 monthly report는 별도 CLI 스크립트로 수동 호출.

> **Stage 6 정리 (Commit 1+2)**: 큰 재설계 없이 *Stage 1-5 산출물을 충분히 활용*하도록 보강. portfolio.json full trace, philosophy.md 섹션별 매핑, trade_plan qty=0 명시 경고, monthly CLI 추가.

---

## 1. 한 줄 요약

> **portfolio.json (Stage 1-5 산출물 통합 trace) + trade_plan.csv (MTS 입력 + qty=0 경고) + philosophy.md (Stage 1-5 정량 정보 섹션별 매핑한 6 sections, deep_llm 1-2회) 3개 산출물을 매일 자동 생성. monthly.md는 매월 1회 별도 CLI로 수동 생성.**

---

## 2. 왜 정리했나

### 2.1 정리 전 발견된 7가지

| # | 문제 | 영향 |
|---|---|---|
| ① | portfolio.json이 Stage 1-5 산출물 대부분 누락 | "왜 이 weight?" 사후 추적 불가 |
| ② | philosophy.md prompt가 Stage 4·5 정보 미활용 | 대회 §4.1 정량 근거 약함 |
| ③ | trade_plan qty=0 silent (logger.warning만) | 운영자가 늦게 발견 |
| ④ | monthly.py 그래프 외부 — wire 안 됨 | 매월 누락 위험 |
| ⑤ | artifacts/ vs runs/ 관계 모호 | 운영 시 혼란 |
| ⑥ | philosophy retry 1회만, section 누락 미검증 | edge case 미대응 |
| ⑦ | portfolio_manager에 archive_wrap 미적용 | 의도된 분리 (변경 X) |

### 2.2 정리 원칙

- ✅ **재설계 X** — 구조 그대로 (3 산출물 + 매월 1회 monthly)
- ✅ **LLM 호출 수 변화 없음** — philosophy 1-2회 그대로 (prompt만 풍부)
- ✅ **artifacts/ vs runs/ 분리 유지** — 운영자/심사자 vs 모델 trace
- ✅ **Stage 1-5 산출물 활용 최대화** — 새 정보 추가 없이 기존 trace 통합

→ Commit 1에서 ①②③ 해결, Commit 2에서 ④ 해결. ⑤는 docs로 정리, ⑥은 logger.warning 추가만, ⑦은 의도된 분리로 유지.

---

## 3. 어떤 데이터를 보는가

### 3.1 Input — state에서 읽는 키 (Stage 1-5 전체)

| Stage | Key | 활용 |
|---|---|---|
| Stage 1 | `macro_summary`, `risk_summary`, `technical_summary`, `news_summary` | philosophy state_summary |
| Stage 2 | `research_decision` | portfolio.json + philosophy 시나리오 확률 |
| Stage 2 | `bucket_target` | portfolio.json |
| Stage 2 | `research_debate_summary` | philosophy state_summary |
| Stage 3 | `method_choice` | portfolio.json + philosophy method reasoning |
| Stage 4 | `risk_overlay` | portfolio.json + philosophy lens 정보 |
| Stage 4 | `portfolio_numerics` | portfolio.json + philosophy HHI/CVaR/cluster |
| Stage 5 | `validation_report` | portfolio.json (어떤 룰 통과/위반) |
| Stage 5 | `rebalance_mode` | portfolio.json + philosophy §6 매매 원칙 |
| Final | `weight_vector` | 모든 산출물 베이스 |
| Final | `capital_krw`, `as_of_date` | 거래금액 계산, 디렉토리 위치 |
| Final | `universe_path` | name/category lookup |
| Cross-run | `previous_portfolio` | (이번 단계 미사용 — Stage 5 turnover만) |

### 3.2 외부 데이터

| 함수 | 데이터 | 캐시 |
|---|---|---|
| `_fetch_current_prices(as_of)` | pykrx ETF snapshot — `{ticker: close}` | ParquetCache 사용 X (snapshot은 단일 날짜) |

→ Stage 6의 외부 fetch는 단 1회 (pykrx 현재 가격). 실패 시 모든 qty=0 + 명시 경고.

---

## 4. 어떻게 가공하는가 (3 산출물 + monthly)

```
Stage 5 통과 (validation_passed)
        ↓
portfolio_manager 노드
   │
   ├─→ 1. _build_full_trace_portfolio → portfolio.json (Stage 1-5 통합 trace)
   ├─→ 2. write_trade_plan → trade_plan.csv + (qty=0 경고 라인 + state warnings)
   └─→ 3. write_philosophy → philosophy.md (deep_llm 1-2회, 6 sections)

(매월 별도)
운영자 → scripts/generate_monthly_report.py → runs/{date}/monthly.md
   └→ archive에서 state 복원 + pnl_csv 입력 + deep_llm
```

### 4.1 portfolio.json — full trace (Commit 1 ①)

`_build_full_trace_portfolio(state)`:

```python
{
    "as_of_date", "capital_krw",                    # 기본
    "method", "bucket_target",
    "weights", "rationale",
    "expected_volatility", "expected_sharpe",

    # Stage 2 — Research Decision
    "research_decision": {
        "dominant_scenario": "broad_recession",
        "dominant_probability": 0.42,
        "conviction": "medium",
        "scenario_probabilities": { ... 7 시나리오 ... },
    },
    # Stage 3 — Method choice
    "method_choice": {"method": "hrp", "reasoning": "...", "params": {}},
    # Stage 4 — Risk Overlay
    "risk_overlay": {
        "strength_applied": 0.5,
        "severity_decision": "high consensus",
        "risk_asset_multiplier": 0.85,
        "weight_ceilings": { ... },
        "tail_hedge_floor": { ... },
        "lens_concerns": [ ... 3 LensConcern ... ],
    },
    # Stage 4 — Portfolio Numerics
    "portfolio_numerics": {
        "hhi": 0.14, "top1_weight": 0.30, "top3_weight_sum": 0.65,
        "cluster_exposure": { ... }, "max_cluster_exposure": 0.40,
        "var_95_1d": 0.020, "cvar_95_1d": 0.025,
        "realized_vol_60d": 0.012, "n_assets": 8,
    },
    # Stage 5 — Validation
    "validation_report": {
        "passed": true, "violations": [],
        "suggestions": [],
    },
    "rebalance_mode": "initial",
}
```

**의도**: portfolio.json **단독으로** "왜 이 weight가 나왔는가" 완전 추적. 심사자/운영자가 추가 파일 참조 없이 의사결정 trace 가능.

**Helper**: `_serialize_for_json` — Pydantic / dict / list / primitive 안전 직렬화. Pydantic `model_dump(mode="json")` 우선, 실패 시 일반 `model_dump()`. 재귀 처리.

### 4.2 trade_plan.csv — MTS 입력 + qty=0 경고 (Commit 1 ③)

`write_trade_plan(weights, capital_krw, universe_lookup, current_prices, out_path)`:

CSV 형식 (UTF-8 BOM):
```csv
티커,ETF명,자산군,가중치,매수금액(KRW),수량(주)
A069500,KODEX 200,국내주식_지수,0.2000,200000000,4000
A360750,TIGER 미국S&P500,해외주식_지수,0.1500,150000000,12000
...
```

**qty=0 발생 시** (price=0 또는 pykrx fetch 실패):

```csv
# WARNING: 3 ticker(s) have qty=0 (current_prices fetch failed or price=0)
# Affected: A069500, A360750, A114260
# Manual fix: re-fetch pykrx snapshot for as_of_date, or override prices in artifacts/{date}/portfolio.json
```

→ MTS는 `#` 주석 라인 무시. 사람이 보면 명확히 경고 인지.

**Returns**: `(out_path, zero_qty_tickers)`. portfolio_manager가 zero_qty를 state["warnings"]에 기록 + `logger.warning`.

**AgentState 신규 필드** `warnings: list[str]` — Stage 6에서 추가.

### 4.3 philosophy.md — 6 sections, Stage 1-5 섹션별 매핑 (Commit 1 ②)

`generate_philosophy(state, deep_llm)` → `write_philosophy(... out_path)`:

#### Prompt 구조

```
6 mandatory sections (Korean only, each ≥600 chars, total ≥4000):
1. 매크로 환경 진단 — Stage 1 macro_quant 인용
2. 시장 리스크 평가 — Stage 1 market_risk + Stage 4 portfolio_numerics (CVaR/HHI)
3. 자산군 비중 결정 논리 — Stage 2 시나리오 확률 + 5-bucket
4. 단일 리스크 통제 전략 — Stage 4 concentration lens + Stage 5 cluster cap
5. 시장 충격 시나리오 — Stage 2 7 시나리오 보수형 + Stage 4 tail_risk lens
6. 매매 원칙 — Stage 5 rebalance_mode + turnover floor

CRITICAL RULES:
- Korean only, ≥4000 chars
- 섹션별로 명시된 Stage 출력을 *구체 수치로* 인용
- ETF 안내서/뉴스 그대로 복사 X
```

#### `_build_state_summary` 5개 helper

| Helper | Stage | 출력 예시 |
|---|---|---|
| `_format_scenario_probs(rd)` | Stage 2 | `"goldilocks 42%, ai_concentration 18%, ..."` |
| `_format_overlay(overlay)` | Stage 4 | `"strength=0.50, multiplier=0.85, ceilings=0, floors=0 | tail_risk=high; concentration=medium"` |
| `_format_numerics(n)` | Stage 4 | `"HHI=0.133, top1=14.5%, max_cluster=32.5%, CVaR_95=2.50%"` |
| `_format_validation(report)` | Stage 5 | `"passed=true, hard_violations=0, soft=0"` |
| `_build_state_summary(state)` | 전체 | Stage 1-5 통합 markdown |

#### Retry 룰

```python
if len(text) < 4000:
    retry = deep_llm.invoke(f"only {len} chars. Expand each ...")
    text = retry.content
if len(text) < 4000:
    logger.warning("philosophy.md only %d chars after retry — manual review required", len(text))
```

→ retry 1회만. 두 번째도 <4000자면 *그대로 저장 + logger.warning*. 대회 §4.1 4000자 미만은 자동 감점이므로 강제 실패시키지 않고 경고만.

### 4.4 monthly.md — 매월 별도 CLI (Commit 2)

`scripts/generate_monthly_report.py`:

```bash
python scripts/generate_monthly_report.py \
    --month 6 \
    --pnl-csv data/pnl/2026-06.csv \
    --as-of-date 2026-06-30 \
    --out artifacts/2026-06/monthly.md
```

흐름:
1. `--as-of-date` / `--pnl-csv` 검증
2. `resolve_run_dir(as_of_date)` → `runs/{date}/`
3. `_restore_state_from_archive`: macro_summary.json + risk_summary.json 복원 (Phase 3 archive 활용)
4. `create_llm_client` (provider/model 인자 또는 `DEFAULT_CONFIG`)
5. `write_monthly(state, pnl_csv, month, llm, out_path)` → `runs/{date}/monthly.md` (default)

**대회 §4.2 요구**: ≥A4 2 pages (~2500자), 3 mandatory sections:
- 수익률 자체 평가
- 포트폴리오 변경 사유
- 향후 시장 전망 및 전략

---

## 5. 출력 구조

### 5.1 산출물 디렉토리

```
artifacts/
└── {as_of_date}/                  ← Stage 6 매일 자동
    ├── portfolio.json             ← full trace (Stage 1-5 통합)
    ├── trade_plan.csv             ← MTS 입력 (qty=0 시 # 경고 라인 포함)
    └── philosophy.md              ← 6 sections, ≥4000자

runs/
└── {as_of_date}/                  ← Phase 3 archive (Stage 1-4 trace)
    ├── macro_report.json
    ├── macro_summary.json
    ├── risk_report.json
    ├── ...
    ├── research_decision.json
    ├── candidate_set.json
    ├── weight_vector.json
    ├── method_choice.json
    ├── risk_overlay.json
    ├── monthly.md                 ← monthly CLI 수동 생성 (선택)
    └── metadata.json
```

### 5.2 State wire (3 키 + warnings)

```python
return {
    "final_portfolio_path":  "artifacts/{date}/portfolio.json",
    "philosophy_doc_path":   "artifacts/{date}/philosophy.md",
    "trade_plan_csv_path":   "artifacts/{date}/trade_plan.csv",
    "warnings":              [...]   # AgentState 신규 필드
}
```

`warnings`는 non-blocking. trade_plan qty=0 같은 경고 기록.

---

## 6. Downstream — Stage 6는 final

Stage 6 다음은 운영자 / 심사자가 보는 **외부 영역**.

| 소비자 | 활용 |
|---|---|
| 운영자 (매일) | `artifacts/{date}/trade_plan.csv` → MTS에 직접 입력 |
| 심사자 (5/27 제출 시점) | `artifacts/{date}/portfolio.json` + `philosophy.md` |
| backtest 분석가 | `runs/{date}/` 전체 + `artifacts/{date}/portfolio.json` full trace |
| 매월 1회 보고 | `runs/{date}/monthly.md` (CLI 수동) |

### artifacts/ vs runs/ 분리 의도

| 경로 | 대상 | 내용 |
|---|---|---|
| `artifacts/` | **운영자 / 심사자** | 최종 산출 — portfolio.json, trade_plan.csv, philosophy.md |
| `runs/` | **개발자 / backtest** | 모델 trace — analyst reports, scenario probs, lens concerns, etc. |

→ portfolio.json에 full trace 포함되어 있으므로 *artifacts만 보고도 사후 추적 가능*. runs는 *세부 backtest용 raw data*.

---

## 7. Graceful Degradation

| 실패 | Fallback |
|---|---|
| `weight_vector` 없음 | Stage 5에서 이미 차단 (validator router) — 정상 path에선 불가 |
| `_fetch_current_prices` pykrx 실패 | empty dict → 모든 qty=0 → trade_plan에 # WARNING 라인 + state warnings |
| `universe_lookup` 부재 ticker | name/category 빈 문자열로 row 생성 (silent) |
| Stage 1-5 산출물 부재 (research_decision 등 None) | portfolio.json에 `null`로 저장, philosophy state_summary는 "(none)" 텍스트 |
| philosophy.md retry 후도 <4000자 | logger.warning + 그대로 저장 (대회 자동 감점 감수) |
| deep_llm 호출 자체 실패 | exception propagate → 파이프라인 fail (Stage 6에서 fallback 없음) |

→ Stage 6는 가능한 한 **모든 산출물을 만들어두는** 정신 (Mandate Validator처럼 차단보단 produce). 단 deep_llm 실패는 hard fail.

---

## 8. 비용

| 항목 | Before | After |
|---|---|---|
| **LLM 호출** | deep 1-2회 (philosophy) | **동일** — 1-2회 |
| **외부 fetch** | pykrx snapshot 1회 | 동일 |
| **코드량 (portfolio_manager.py)** | ~91 LOC | ~140 LOC (full trace helper) |
| **코드량 (philosophy.py)** | ~55 LOC | ~150 LOC (5 format helper + retry warning) |
| **신규 CLI** | 0 | `scripts/generate_monthly_report.py` (~120 LOC) |

→ Stage 6 정리에서 **LLM 비용 증가 0**. 코드만 보강.

---

## 9. 검증 결과

| 항목 | 결과 |
|---|---|
| 단위 테스트 | **584 passing** (회귀 0건) |
| Stage 6 신규 unit test | **+12** (full trace 7 + monthly CLI 5) |
| 기존 test 수정 | 2 (csv data row 필터: test_portfolio_manager, test_5_28_dry_run) |
| Integration | 7 passing |

### 핵심 invariant 검증
- portfolio.json에 Stage 1-5 trace 6개 키 포함
- `_serialize_for_json`이 Pydantic/dict/list/primitive 안전 처리
- qty=0 시 CSV에 `# WARNING` 라인 + state["warnings"]에 기록
- qty>0 (정상 path)에서는 # 라인 없음
- philosophy state_summary가 Stage 2 시나리오 확률 분포 포함
- monthly CLI: date format / pnl-csv 존재 검증 + archive 복원 + LLM 호출

---

## 10. Stage 1 / 2 / 3 / 4 / 5 / 6 디자인 일관성

| 항목 | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 | Stage 6 |
|---|---|---|---|---|---|---|
| LLM 사용 (매일) | quick + subagents | deep 1회 | 0회 | 0회 | 0회 | **deep 1-2회 (philosophy 생성)** |
| 결정 방식 | LLM + 결정적 mix | 시나리오 확률 → 결정적 매핑 | 결정적 함수 | 결정적 룰 | 순수 결정적 룰 | **결정적 helper + LLM 생성** |
| 외부 fetch | 다수 | 0 | 1회 (returns) | 1회 (returns) | 0 | 1회 (pykrx price) |
| Archive | runs/{date}/ | runs/ | runs/ | runs/ | (validation_report만) | **artifacts/{date}/ (별도 경로)** |
| 역할 | 정량/정성 분석 | 시나리오 합성 | weight 산출 | runtime risk | mandate 강제 | **산출 + narrative** |

→ Stage 6는 *production artifacts*의 유일한 LLM 소비자. philosophy 생성은 본질적으로 *narrative 생성*이라 LLM이 자연스럽게 가치 제공. Stage 1-5는 결정 단계, Stage 6는 *문서화 단계*.

---

## 11. Commit 누적 결과

| Commit | 작업 | 효과 |
|---|---|---|
| Baseline | 3 artifacts + 매월 dead-end monthly.py | 기본 산출 |
| **Commit 1** `f69c54f` | ① portfolio.json full trace / ② philosophy.md 섹션 매핑 / ③ trade_plan qty=0 경고 | portfolio.json 단독 추적성, philosophy 정량 근거 ↑, qty=0 안전성 |
| **Commit 2** `282d4e4` | ④ scripts/generate_monthly_report.py CLI | 매월 monthly.md 수동 호출 흐름 명시 |

**총 변화**:
- LLM 호출: 변화 없음 (philosophy 1-2회 그대로)
- 새 룰 추가: 0 (대회 §에 없는 것 X)
- 신규 코드: ~400 LOC + 12 신규 test
- 회귀: 0건

---

## 12. 운영 절차

### 12.1 매일 자동 (portfolio_manager 노드)

```
LangGraph 실행 → ... Stage 5 통과 → Stage 6 portfolio_manager
    └─→ artifacts/{date}/portfolio.json
    └─→ artifacts/{date}/trade_plan.csv
    └─→ artifacts/{date}/philosophy.md
```

운영자 액션:
1. `trade_plan.csv` 열어 # WARNING 라인 확인 (qty=0 ticker 있는지)
2. WARNING 있으면 수동으로 가격 보정 또는 다음날 재시도
3. MTS에 trade_plan.csv 업로드

### 12.2 매월 1회 수동 (monthly CLI)

```bash
# 월말 (예: 2026-06-30 데이터)
python scripts/generate_monthly_report.py \
    --month 6 \
    --pnl-csv data/pnl/2026-06.csv \
    --as-of-date 2026-06-30

# 출력: runs/2026-06-30/monthly.md
```

운영자 액션:
1. PnL CSV 준비 (broker 데이터에서 일별 equity 시계열 export)
2. 위 명령 실행
3. 생성된 `monthly.md` 검토 후 대회 제출

### 12.3 5/27 제출 시점

심사자 제공 파일:
- `artifacts/2026-05-27/portfolio.json` (full trace — 의사결정 추적 가능)
- `artifacts/2026-05-27/philosophy.md` (4000자 한국어 6 sections)
- `artifacts/2026-05-27/trade_plan.csv` (MTS 입력 형식)

`runs/2026-05-27/`는 *개발자 reference*이므로 제출 X (선택).

---

## 13. 파일 매니페스트

| 위치 | 파일 |
|---|---|
| 노드 | `tradingagents/agents/managers/portfolio_manager.py` |
| 산출 helper | `tradingagents/reports/{philosophy,trade_plan,monthly}.py` |
| 스키마 (AgentState `warnings`) | `tradingagents/agents/utils/agent_states.py` |
| Monthly CLI | `scripts/generate_monthly_report.py` |
| Universe 메타 | `tradingagents/dataflows/universe.py` |
| pykrx snapshot | `tradingagents/dataflows/pykrx_data.py:fetch_etf_snapshot_by_date` |
| 단위 테스트 | `tests/unit/agents/test_portfolio_manager.py`, `test_portfolio_manager_full_trace.py`, `tests/unit/scripts/test_generate_monthly_report.py` |
| Integration | `tests/integration/test_5_28_dry_run.py` (end-to-end + artifacts 생성) |

---

## 14. 디자인 의사결정 기록

### 왜 portfolio.json full trace?

심사자/운영자가 단일 파일로 *왜 이 weight?* 추적해야 함. runs/ 별도 디렉토리는 *개발자 reference*. portfolio.json 단독 narrative source가 깔끔.

### 왜 LLM 호출 수 유지 (Stage 6 정리에서 추가 안 함)?

philosophy 1-2회로 충분. *prompt만 풍부*하게 하면 LLM이 자연스럽게 정량 정보 인용. 추가 LLM 호출은 비용 vs 가치 불일치.

### 왜 trade_plan qty=0 강제 fail 안 함?

qty=0 발생은 *pykrx fetch 실패 같은 일시적 원인*이 대부분. CSV는 만들고 # 경고로 표시 → 운영자가 보완. 강제 fail은 Stage 5 mandate 영역 (validator)이라 책임 분리.

### 왜 monthly.py 그래프에 wire 안 함?

매월 1회 호출이라 매일 그래프 노드로 두면 *31번 중 30번 no-op*. PnL CSV 의존성 (외부 broker 데이터)도 있어 인자 처리 복잡. CLI 스크립트가 자연스러움.

### 왜 archive_wrap 적용 안 함?

Stage 1-4는 `runs/{date}/` archive로 모델 trace 보존. Stage 6는 `artifacts/{date}/` 별도 경로로 운영자/심사자 산출. *두 경로 분리가 의도된 디자인*. archive_wrap을 또 적용하면 중복.

### 왜 philosophy.md retry 후도 <4000자 시 hard fail 안 함?

대회 §4.1 4000자 미만은 자동 감점. 강제 fail시키면 *모든 산출물 무산*. 경고만 띄우고 *불완전한 결과라도 보존*하는 게 안전.

### 왜 `_serialize_for_json` 직접 구현?

Pydantic v2의 `model_dump(mode="json")`은 대부분 처리하지만:
- 일부 Pydantic v1 호환 모델
- dict/list 안에 mixed type
- `date`/`datetime` 객체

→ helper로 안전한 재귀 직렬화. fallback `default=str`로 json.dumps도 안전.

---

## 15. 향후 로드맵 (선택적)

### 우선순위 낮음 (운영 시작 후)

- **A. trade_plan price override 옵션**
  - portfolio.json에 manual price override field 추가
  - qty=0 ticker만 수동 price 입력 → trade_plan re-generate

- **B. philosophy.md section validator**
  - LLM 출력에서 6 sections 모두 포함됐는지 keyword check
  - 누락 시 retry (현재는 길이만 검증)

- **C. monthly.py 자동 trigger**
  - 매월 말일 자동 호출 (cron 또는 분기 처리)
  - PnL CSV는 brokerage API 자동 fetch (의존성 큼)

- **D. ValidationReport archive**
  - Stage 5 산출도 runs/{date}/validation_report.json에 저장
  - philosophy state_summary에 *어떤 룰 위반했는지* 인용 가능

각 항목은 baseline에 대한 **선택적 확장**. 현재 Stage 6는 production 충분.
