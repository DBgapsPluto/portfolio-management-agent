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
