# Stage 1 Audit — 2026-05-26

Plan: [docs/superpowers/plans/2026-05-26-stage1-audit.md](superpowers/plans/2026-05-26-stage1-audit.md)

각 Task 진행 중 발견·결정·수정 사항을 누적 기록.

---

## Task 0 — Cross-cutting: staleness propagation

### 발견

#### F0.1 — `is_stale` / `is_very_stale` property가 **사용처 0**

[tradingagents/schemas/_base.py:21-29](../tradingagents/schemas/_base.py#L21-L29)에 `StalenessAware` base class가 `is_stale` (`> 1d`), `is_very_stale` (`> 7d`) property 를 노출하지만, 전체 코드베이스에서 호출되는 곳 0.

→ 모든 sentinel snapshot 의 staleness 정보가 사실상 무시되는 상태.

#### F0.2 — sentinel `staleness_days=99` 설정 사이트 50+ vs. 검사 사이트 1

```
설정 사이트: macro_quant_analyst (15), market_risk_analyst (12), skills/macro/* (3),
             skills/risk/* (15), correlation_pca, breadth, vxn, real_yields,
             equity_bond_corr, credit_quality, kr_corp_spread, skew_index,
             kr_yield_curve, kr_margin_debt, kr_market_tier, volatility.
검사 사이트: 단 1곳 — market_risk_analyst.py:346 (`kr_yield_curve.staleness_days >= 99`).
```

→ Stage 2 factor_estimators / Stage 3 method_picker / Stage 3 portfolio_allocator 가 `staleness_days` 를 검사하지 않고 snapshot 의 field 값을 그대로 소비.

#### F0.3 — `_safe_get` (factor_estimators.py:153) 가 sentinel-blind

Stage 2 factor model 의 entrypoint helper `_safe_get(obj, *path)` 는 attribute chain walk 만 한다.

```python
def _safe_get(obj, *path, default=None):
    cur = obj
    for key in path:
        if cur is None:
            return default
        try:
            cur = getattr(cur, key)
        ...
    return cur
```

`_safe_get(stage1, "macro_report", "gdp_nowcast", "nowcast_pct")` 호출 시 `gdp_nowcast` 가 `staleness_days=99` sentinel 인 경우에도 `.nowcast_pct` 의 default 값(예: 0.0)이 그대로 raw 로 들어가 z_score 산출됨.

**구체적 위험**:
- BSI snapshot sentinel = `bsi=100, staleness_days=99` → factor F1 가 BSI=100 (정상 평균) 으로 흡수.
- VIX term snapshot sentinel = `ratio=1.0, staleness_days=99` → factor F7 가 정상 contango 로 해석.
- FX snapshot sentinel = `usd_krw=1300, staleness_days=99` → factor F6 가 정상 환율로 해석.

결과: **fetch 실패가 factor z 에 silent distortion** 으로 흡수. blackbox.

#### F0.4 — Stage 3 method_picker / portfolio_allocator 도 직접 검사 없음

[method_picker.py:87](../tradingagents/skills/portfolio/method_picker.py#L87): `if systemic_score >= 8.0` 분기.
[portfolio_allocator.py:50-51](../tradingagents/agents/allocator/portfolio_allocator.py#L50-L51): `regime = state["macro_report"].regime`, `risk_score = state["risk_report"].systemic_score`.

`regime` 객체와 `systemic_score` 객체 자체에 `staleness_days` 가 있지만 검사 없음. **단**, 이 두 값은 macro_quant / market_risk analyst 내부에서 다른 snapshot 들의 합성으로 산출되며, 합성 로직이 sentinel 입력을 받아 "neutral/unknown" 으로 흡수한다면 외부 검사 불필요. 이 부분은 Task 2 / Task 3 에서 검증.

### 결정

**D0.1** — Task 0 의 surgical 픽스: `_safe_get` walk 중에 만나는 `StalenessAware` 객체가 `staleness_days >= STALENESS_SENTINEL_DAYS` (=99) 이면 `default` 반환. component drop 효과.

**근거**:
- 호출부 변경 없음 (in-place).
- sentinel 의미 (99 = fetch 실패) 와 일치.
- 정상 stale (1~7d) 데이터는 통과 → 가용한 정보 활용 유지.
- factor_estimators 의 `_aggregate` 가 이미 `None` component 를 drop + weight renormalize 하므로 깔끔히 흡수.

**D0.2** — `is_stale` / `is_very_stale` 미사용 property 는 그대로 유지 (Stage 2/3 에서 추후 활용 후보). 본 audit 범위 밖.

**D0.3** — method_picker / portfolio_allocator 의 직접 staleness 검사 추가는 Task 2 / Task 3 에서 regime classifier 와 systemic_score 산출 로직 검증 후 결정.

### 수정

`_safe_get` 의 sentinel guard 추가 + `STALENESS_SENTINEL_DAYS` 상수 분리 + unit test.

### 합격 기준

- [x] 설정/검사 사이트 매핑 정리.
- [x] _safe_get 의 silent distortion 위험 명시.
- [x] _safe_get 픽스 적용 + 테스트 통과 (research 모듈 83 pass, 회귀 0).
- [x] commit.

---

## Stage 1 → Stage 2/3 데이터 매핑 (참고)

### Stage 1 → Stage 2 factor_estimators

| Factor | Stage 1 dependency (path) | _safe_get 적용 | sentinel 위험 |
|---|---|---|---|
| F1 growth | macro_report.gdp_nowcast.nowcast_pct, .financial_conditions.nfci/cfnai/cfnai_3m_avg, .employment.sahm_rule_triggered, .yield_curve.spread_10y_2y_bps + news_report.release_surprise, .global_overnight.* | ✓ | sentinel 입력 시 정상 평균 해석 |
| F2 inflation | macro_report.inflation.* , .inflation_expectations.*, .fed_path.*, + risk_report.real_yields.tips_10y + news_report.* | ✓ | 동일 |
| F3 real_rate | risk_report.real_yields.* + macro_report.fed_path | ✓ | 동일 |
| F4 term_premium | macro_report.yield_curve.* | ✓ | 동일 |
| F5 credit_cycle | risk_report.credit_quality.*, .funding_stress.* | ✓ | 동일 |
| F6 krw_regime | macro_report.fx.usd_krw + external fetch fallback | ✓ | external fallback 있으므로 위험 작음 |
| F7 equity_vol_regime | risk_report.vol_term.*, .real_vol.*, .skew.*, .vxn.* | ✓ | sentinel 위험 큼 (1.0 ratio = 정상값) |
| F8 valuation | macro_report.kr_valuation.*, .tail_risk.move (+external SP P/E) | ✓ | 동일 |
| F9 liquidity_regime | risk_report.real_vol.vrp_60d, breadth_kr.advancing_pct + sector_dispersion | ✓ | 동일 |

→ 모든 factor 가 `_safe_get` 픽스의 혜택을 받음.

### Stage 1 → Stage 3 portfolio_allocator

| 소비 위치 | Stage 1 dependency | sentinel 위험 |
|---|---|---|
| portfolio_allocator.py:50 | macro_report.regime (.quadrant, .confidence) | regime 객체는 macro_quant 내부에서 합성. Task 2 에서 검증 필요. |
| portfolio_allocator.py:51 | risk_report.systemic_score (.score, .regime) | 동일. Task 3 에서 검증. |
| method_picker (via allocator) | 위 두 값 + research_decision (Stage 2) | 직접 staleness 검사 없음 — 합성 로직이 sentinel-safe 인지 의존. |

→ Task 2/3 에서 합성 로직 검증.

---

## Task 1 — technical analyst

### 발견

#### F1.1 — 8곳 `except: continue` silent

`technical_analyst.py` 의 6 tier 산출 루프 모두 silent except. 어떤 ETF 가 어느 tier 에서 실패했는지 trace 불가.

→ 188 ETF 중 일부가 누락된 채 Stage 3 cluster-aware selection 으로 전달돼도 알 수 없음 (blackbox).

#### F1.2 — `_benchmark_for_category` 가 모든 "국내_*" 를 KOSPI200으로 매핑

[line 51-53]:
```python
return "KOSPI200" if category.startswith("국내") else "SPY"
```

채권/현금성 카테고리 (국내채권_*, 금리연계형/초단기채권) 도 KOSPI200 dual-momentum 계산 → `momentum_*_rel` 값 noise. trend_quantification 의 relative momentum 신뢰성 하락.

#### F1.3 — trend_state substring 비교

[line 282]: `sum(1 for v in trend_states.values() if "uptrend" in v.value)`

`TrendState.STRONG_UPTREND`, `UPTREND` 둘 다 "uptrend" 포함 → 의도대로 동작은 하지만 enum 비교가 substring 매칭은 fragile.

#### F1.4 — 매직넘버 산재

- correlation cluster threshold **0.7** (Stage 3 cluster-aware 의존)
- MA200 필요 최소 history **200**
- 1y window **252**
- top_rank threshold **5**
- price lookback **365*3+30**

분석가 entry 에 흩어져 있어 향후 튜닝 어렵고 의도 불명확.

#### F1.5 — observability 부재

`logger` 호출 0번. 188 ETF scan 결과, 누락 카운트, exception 카운트 모두 invisible.

### 결정

**D1.1** — silent except → `failures: dict[str, int]` counter + `logger.debug/warning`. summary 에 failure dict 노출.
**D1.2** — `_benchmark_for_category` 채권/현금성 카테고리 → "none". 명시적 분기.
**D1.3** — `"uptrend" in v.value` → `v in {TrendState.STRONG_UPTREND, TrendState.UPTREND}`.
**D1.4** — 매직넘버 5개 → 모듈 상단 named const 분리 (CORRELATION_CLUSTER_THRESHOLD, MIN_HISTORY_DAYS_TA, MIN_HISTORY_DAYS_LONG, PRICE_LOOKBACK_DAYS, TOP_RANK_THRESHOLD).
**D1.5** — entry 와 cluster 산출 직후 progress log.

### 수정

- [x] 6 except 절 → counter + logger 추가
- [x] _benchmark_for_category 명시적 분기
- [x] trend_state enum 비교
- [x] named const 분리
- [x] entry/clusters 진척 로그

### 회귀

`pytest tests/unit/agents/test_technical_analyst.py tests/unit/skills/test_portfolio_candidate.py tests/unit/skills/test_portfolio_factor_scorer.py` → **60 pass, 1 pre-existing fail** (test_technical_analyst_returns_report — main 에서도 동일하게 실패. 내 변경과 무관).

### 합격 기준

- [x] silent except 0 (모두 counter + logger).
- [x] cluster threshold named const.
- [x] 채권/현금성 카테고리 dual-momentum 분기 명시.
- [x] failure summary 가 narrative 에 노출.

---

## Task 2 — macro_quant analyst

### 발견

#### F2.1 — 13 silent except → sentinel without logger

KR exports/leading/BSI, US leading/GDPNow, FCI, inflation_exp, fed_path, FX, risk_appetite, china_leading, foreign_flow, tail_risk. fetch 실패 → sentinel 으로 변환만 되고 어디서 실패했는지 trace 없음.

#### F2.2 — Sentinel 값과 정상 평균치 구별 불가 (LLM leak)

대표 sentinel:
- `kr_bsi.mfg_bsi = 100.0` → BSI 100 은 평균/중립 수준이라 LLM 이 "정상 경제"로 해석.
- `kr_leading.cli_value = 100.0` → 동일.
- `us_leading.cfnai_ma3 = 0.0` → "neutral activity" 로 해석.
- `fx.usd_krw = 1300` → 정상 환율로 해석.
- `tail_risk.vvix = 90.0` → 평균 변동성으로 해석.

`classify_regime` LLM prompt 가 `staleness_days` 를 전달받지 않아 (line 439-491 의 input 들이 모두 raw value) — fetch 실패가 "정상 경제" 시그널로 흡수.

**근본 해결**: prompt 에 staleness 인디케이터 추가 + LLM 이 sentinel signal 무시하도록 지침. Stage 1 audit scope 밖 (별도 작업).

#### F2.3 — 매직 lookback 윈도우 산재

- `365 * 5` (macro lookback)
- `90` (GDPNow)
- `120` (USDCNH)
- `200` (iron ore)
- `60` (foreign flow)
- `400` (commodities × 2)

### 결정

**D2.1** — 13 silent except → `logger.warning("<name> fetch failed → sentinel: %s", e)`. sub-fetch (china_cli_series 등) 도 동일.
**D2.2** — sentinel inventory dict 산출 + `n_sentinels` 카운트. `n_sentinels > 0` 시 `logger.warning` 및 narrative summary 상단에 "Sentinels: N/17 (names)" 노출.
**D2.3** — magic lookback 7개 → named const 모듈 상단 분리 (MACRO_LOOKBACK_DAYS=365*5, COMMODITY_LOOKBACK_DAYS=400, GDPNOW_LOOKBACK_DAYS=90, USDCNH_LOOKBACK_DAYS=120, IRON_ORE_LOOKBACK_DAYS=200, FOREIGN_FLOW_LOOKBACK_DAYS=60, CALENDAR_LOOKAHEAD_DAYS=90).
**D2.4** — entry log `logger.info("macro_quant start: as_of=%s, lookback=%dd")`.
**D2.5** — classify_regime LLM prompt staleness 보강은 본 PR 밖 (followup_issues 로 이관).

### 수정

- [x] 13 except 절 → logger.warning
- [x] sentinel inventory + summary 노출
- [x] named lookback const 분리
- [x] entry log

### 회귀

`pytest tests/unit/agents/test_macro_quant_analyst.py tests/unit/skills/research/test_factor_estimators_individual.py` → **27 pass, 0 fail**.

### 합격 기준

- [x] silent except 0 (모두 logger.warning).
- [x] sentinel inventory 가 summary 에 가시화.
- [x] lookback 윈도우 named const.
- [ ] [Deferred] LLM prompt staleness 보강 — Stage 2 prompt 재설계 시 처리 (followup).

---

## Task 3 — market_risk analyst

### 발견

#### F3.1 — **(CRITICAL) Synthetic data fallback in production path**

[line 212-220, market_risk_analyst.py]:
```python
except Exception:
    # Fallback: 기존 synthetic (degraded mode)
    synthetic = pd.DataFrame({
        "spy": [0.002, -0.001, 0.002, 0.0, 0.001] * 50,
        ...
    })
    pca = compute_correlation_concentration(synthetic, as_of)
    pca = pca.model_copy(update={"staleness_days": 99})
```

`fetch_cross_asset_returns` 실패 시 **하드코딩된 5일 패턴 × 50일 = 250개 가짜 return** 으로 PCA 계산. staleness=99 마크되긴 했지만 `pca.first_eigenvalue_share`, `pca.is_concentrated` 값이 **fabricated correlation structure** 에서 산출 → snapshot 자체가 의미 없는 값을 담음.

Task 0 의 `_safe_get` sentinel guard 가 factor_estimators 의 downstream 흡수는 막아주지만, market_risk_analyst 의 systemic_score 가 같은 PCA 객체의 `.first_eigenvalue_share` 를 직접 LLM 으로 넘김 → systemic_score 계산이 fabricated 값으로 영향받음.

#### F3.2 — 12 silent except → sentinel without logger

vix_term, skew, vxn, real_yields, funding_stress, credit_quality, kr_yield_curve, kr_corp_spread, kr_margin, kr_market_tier, eq_bd_corr (2곳). 모두 trace 없음.

#### F3.3 — 매직 lookback 산재

`400` (vol, commodity), `365*5+30` (5y), `365` (PCA), `60` (market tier), `"120d"` (realized vol period), `"65d"` (sector dispersion), `"400d"` (mega cap).

### 결정

**D3.1** — synthetic fallback 제거. fetch 실패 시 명시적 `PCASnapshot(first_eigenvalue_share=0.0, n_assets_analyzed=2, is_concentrated=False, staleness_days=99)` 생성. fabricated correlation 차단.
**D3.2** — 12 silent except → `logger.warning("<name> fetch failed → sentinel: %s", e)`.
**D3.3** — magic lookback → 함수 내부 named const (function-local; 모듈 const 와 달리 함수 진입 시점에만 결정).
**D3.4** — sentinel inventory (13 snapshots) + summary 노출.

### 수정

- [x] PCA synthetic fallback → explicit sentinel (CRITICAL F3.1 차단)
- [x] 12 silent except → logger.warning
- [x] magic lookback → named const
- [x] sentinel inventory + summary line

### 회귀

`pytest tests/unit/agents/test_market_risk_analyst.py tests/unit/skills/test_risk_correlation_pca.py tests/unit/skills/research/` → **85 pass, 0 fail**.

### 합격 기준

- [x] F3.1 stub fallback 차단 — 명시적 sentinel.
- [x] silent except 0.
- [x] sentinel inventory 가 summary 에 가시화.
- [x] 매직 lookback 분리.

---

## Task 4 — macro_news analyst

### 발견

#### F4.1 — 6 silent except + SAVE brief silent fallback

- impact_classifier loop: `try/except/continue` 한 항목 실패 시 다음으로 (cost 보호 OK, but no log).
- overnight, save_brief, surprise, sentiment, speaker — 모두 `try/except: x = None` silent.
- SAVE brief 가 없을 때 `state["release_surprises_30d"]` fallback — 이 fallback 발동도 silent.

#### F4.2 — 매직 상수

- `days=90` (calendar lookahead)
- `window_days=7` (news fetch)
- `[:30]` (impact classify cap, cost 보호)
- `top_n=10` (ranked news)
- `[:500]` (narrative)
- `[:2000]` (summary)

### 결정

**D4.1** — 6 silent except → logger 추가. impact_classifier 는 per-item debug + final warning count.
**D4.2** — SAVE brief 없을 때 fallback 발동 시 명시적 logger.info (release_surprises_30d 개수 표시).
**D4.3** — 6 매직 상수 → 모듈 상단 named const.
**D4.4** — missing-tier inventory dict (5 항목) + n_missing 카운터. summary 상단에 노출.
**D4.5** — entry + fetch counts log.

### 수정

- [x] 6 except 절 → logger
- [x] SAVE brief fallback 명시 로그
- [x] named const 6개
- [x] missing-tier inventory + summary 노출
- [x] entry/fetch progress log

### 회귀

`pytest tests/unit/agents/test_macro_news_analyst.py` → **1 pass, 0 fail**.

### 합격 기준

- [x] silent except 0.
- [x] SAVE brief 미스 시 명시 fallback 로그.
- [x] missing-tier inventory summary 노출.
- [x] 매직 상수 분리.
