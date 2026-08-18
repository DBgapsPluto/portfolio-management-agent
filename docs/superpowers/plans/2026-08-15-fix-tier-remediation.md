# Fix-Tier Remediation (F1–F6) Implementation Plan — rev1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **rev1 (2026-08-15):** 적대적 계획 감사 2건(Σ 감사 7 must-fix, 운용 감사 12 must-fix)을 전부 반영. rev0 대비 주요 변경: WP-D를 측정-게이트+다이얼 2단계로 재설계·순서 최후미로, WP-E 속성 경로·선정 헬퍼 교정, WP-C 이중 검사 단일화, WP-B 다운스트림 수선 간섭 방어. **표준 규칙: 이 계획의 모든 심볼·속성·글롭은 grep으로 실재 확인된 것만 기재한다.**

**Goal:** 방법론 감사의 즉시-수정 6건(F1 오버레이 방향, F2 Σ 통화, F3 회전율 측정, F4 비동시성, F5 클러스터 사각지대, F6 모멘텀 패닉 감쇠)을 상호작용을 고려한 최소 재캘리브레이션 경로로 수정한다.

**Architecture:** F2+F4는 동일 Σ 파이프라인이므로 WP-A 하나로 통합(재캘리브레이션 1회). F1/F3/F6은 독립 패키지(WP-B/C/E). F5(WP-D)는 감사 실측에서 "전수 클러스터링이 배분을 마비시킬 수 있음"이 확인되어 **측정 게이트 → 사용자 결정 → 다이얼 가드** 2단계로 진행하며 순서 최후미. 모든 패키지 후 WP-F에서 시스템 검증 1회.

**Tech Stack:** Python 3.12+, pandas 2.3/numpy, pypfopt, pytest. 테스트: `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest <targets> -q`

---

## 0. 전역 설계 결정

| # | 결정 | 근거 |
|---|---|---|
| G1 | **F2+F4 통합 (WP-A)** — KRW 변환 + 주간 리샘플 동시 | 둘 다 Σ 스케일·상관 변경. 재검증 1회화 |
| G2 | 비동시성 해법 = **주간 리샘플** (`min_count=1` 필수 — 감사 A-3) | PSD-safe·문헌 표준. prod() 기본값은 全-NaN 주를 0.0으로 조작함이 실측 확인됨 |
| G3 | **회전율 공식은 룰북 §3와 일치 확인** (`(매수+매도)/평균자산`, docs/DB_GAPS_Investment_Tournament_Rules.md:35) | "2배 모호성" 해소. F3 = 측정 충실화 + **검사 권위 단일화**(감사 MF-5) |
| G4 | F1은 위기 전용 정책 집합 분리 + **다운스트림 수선 간섭 방어**(MF-8) + reassess 경로 포함(MF-9) | 공식 분류 불변, 미래 분류-통일 결정과 절연 |
| G5′ | ~~전수화가 수혜자 버그 자체 해결~~ → **기각됨(MF-1 실측)**: @0.7 전수 클러스터는 66종에서 33종 메가클러스터(77% 편입) 생성 → 35% cap이 사실상 주식 35% 상한화, 수혜 풀 붕괴, daily 경로엔 cluster 수선 자체가 없음 | WP-D는 측정 게이트 후 설계 확정, `cluster_full_universe` 다이얼(기본 False) 가드, daily에 cluster 수선 추가 |
| G6 | F6 감쇠는 선정 교체 — 단 `momentum=None`은 AUM-top-K가 아니라 **core-subcategory 1~2종 집중**을 유발함이 확인됨(MF-3) → 전용 `_aum_top_k` 헬퍼 신설 | 크래시 위험은 "최근 승자 3개 고르기"에 있음 |
| G7′ | MATH-1 불변(합성 Σ 주입, grep 확인) — 단 **trader 레벨 테스트·e2e는 실제 `bucket_covariance`를 경유**하므로(400일 fake ≈ 80주) WP-A 회귀 범위에 포함(감사 A-4/A-7) | `min_obs` 레거시 kwarg는 무시+deprecation 로그, 핀은 `WEEKLY_MIN_OBS=52` 단일 통제 |
| G8 | 재캘리브레이션 WP-F 1회. **구 Σ 산출은 WP-A 랜딩 전 워크트리 실행으로 아티팩트 선확보**(감사 A-6) | dial 변경은 사용자 승인제 |
| G9 | 실행 순서 **A → E → B → C → D(게이트) → F**, 순차 커밋 | D는 행동적 파급(클러스터 출력이 E/C/daily 소비처에 유입)이 커서 최후미(MF-11) |

**모델 배정**: WP-A·D·F = 메인 모델(fable) · WP-B/C/E = sonnet 구현 + opus 검증. 전 WP는 계획-감사→TDD 구현→결과-감사 루프.

---

## WP-A: Σ v2 — KRW 기준화 + 주간 리샘플 (F2+F4)

**Files:**
- Modify: `tradingagents/backtest/bucket_proxies.py`
- Modify: `tradingagents/skills/portfolio/bucket_cov.py`
- Modify: `tradingagents/skills/portfolio/cov_estimator.py` (`frequency` 관통)
- Modify: `tradingagents/agents/trader/trader_allocator.py:357` (`min_obs=252` 인자 제거)
- Modify: `scripts/backtest_bl_calibration.py:207,307` (동일)
- Test: `tests/unit/backtest/test_bucket_proxies_krw.py`(신규), `tests/unit/skills/portfolio/test_bucket_cov.py`(갱신)
- Spec append: `docs/superpowers/specs/2026-06-20-bl-allocator-design.md` §4.2 개정 노트

### Task A0: 구 Σ 기준선 아티팩트 선확보 (WP-F-3 전제)

- [ ] **A0-1**: 현재 HEAD에서 최근 영업일 2개에 대해 `bl_allocate` 버킷 비중 + Σ 대각·상관을 `artifacts/sigma_v2_baseline.json`으로 저장하는 20줄 스크립트 실행 (`scripts/backtest_bl_gate2.py`의 `_fetch_sigma` 재사용). 커밋: `chore(sigma): pre-WP-A baseline artifact for F-3 diff`

### Task A1: KRW 변환 + 헤지-지분 규칙

- [ ] **A1-1: 실패 테스트** — `tests/unit/backtest/test_bucket_proxies_krw.py`

```python
import pandas as pd, numpy as np
from pathlib import Path
from tradingagents.backtest import bucket_proxies as bp

def _series(vals, start="2026-01-05"):
    return pd.Series(vals, index=pd.bdate_range(start, periods=len(vals)), dtype=float)

def test_krw_composite_exact():
    r_usd = _series([0.01, -0.02, 0.005]); r_fx = _series([0.002, 0.03, -0.001])
    out = bp._to_krw(r_usd, r_fx)
    pd.testing.assert_series_equal(out, ((1+r_usd)*(1+r_fx)-1).dropna(), check_names=False)

def test_hedged_share_from_name_convention():
    # is_hedged 필드는 universe에 없음(감사 A-1/MF-12 확인) — 이름 규약으로 유도.
    # 기존 헬퍼 candidate_selector.is_hedged(name) 재사용 (candidate_selector.py:38-43).
    class E:
        def __init__(self, b, aum, name):
            self.gaps_bucket, self.aum_krw, self.name = b, aum, name
    etfs = [E("a3_us_rates", 700, "KODEX 미국채10년(H)"),
            E("a3_us_rates", 300, "TIGER 미국채10년"),
            E("b3_global_tech", 300, "TIGER 미국나스닥100")]
    s = bp._hedged_share_by_bucket(etfs)
    assert s["a3_us_rates"] == 0.7 and s["b3_global_tech"] == 0.0

def test_hedged_share_wiring_real_universe():
    # 스텁-그린/라이브-데드 방지: 실제 data/universe.json 대상 배선 단언 (감사 A-1)
    from tradingagents.dataflows.universe import load_universe
    uni = load_universe(Path("data/universe.json"))
    s = bp._hedged_share_by_bucket(uni.etfs)
    assert s["a3_us_rates"] >= 0.5      # 실측 0.835 — local(헤지 근사) 유지 대상
    assert s["b3_global_tech"] < 0.5    # composite 대상

def test_a4_proxy_is_usdkrw_not_dxy():
    assert bp.BUCKET_PROXY["a4_safe_fx"][0] == ("fred", "usd_krw")
```

- [ ] **A1-2: 실패 확인** → `_to_krw`/`_hedged_share_by_bucket` 부재 4 FAIL
- [ ] **A1-3: 구현** — `bucket_proxies.py`:

```python
from tradingagents.skills.portfolio.candidate_selector import is_hedged  # (H)/환헤지/합성H 규약

def _to_krw(r_local: pd.Series, r_fx: pd.Series) -> pd.Series:
    """언헤지 KRW 수익 합성: (1+r_local)(1+r_fx)-1. inner-join, ffill 금지."""
    j = pd.concat({"l": r_local, "f": r_fx}, axis=1, join="inner").dropna()
    return ((1 + j["l"]) * (1 + j["f"]) - 1)

def _hedged_share_by_bucket(etfs) -> dict[str, float]:
    """버킷별 AUM 가중 환헤지 지분 — ETF *이름 규약*으로 유도 (universe에 필드 없음).
    ≥0.5 → 프록시 local 유지(헤지 근사), <0.5 → KRW composite."""
    num, den = {}, {}
    for e in etfs:
        b = getattr(e, "gaps_bucket", None)
        if not b:
            continue
        a = float(getattr(e, "aum_krw", 0) or 0)
        den[b] = den.get(b, 0.0) + a
        if is_hedged(getattr(e, "name", "")):
            num[b] = num.get(b, 0.0) + a
    return {b: (num.get(b, 0.0) / den[b] if den[b] > 0 else 0.0) for b in den}
```

`BUCKET_PROXY["a4_safe_fx"] = [("fred", "usd_krw"), ("yf", "KRW=X")]`. `fetch_bucket_proxy_returns` 내: universe 로드는 **`load_universe(Path(DEFAULT_CONFIG.get("universe_path", "./data/universe.json")))`** (감사 A-2 — no-arg 호출은 TypeError; `rebalance/daily_full.py:145` 패턴 준용). universe 로드 실패 시 명시적 실패 모드 = **convert-all**(가장 보수적: KRW 노출 가정) + `logger.warning`. FX 시리즈는 함수 내 지역 캐시(모듈 전역 금지 — 테스트 오염 방지, 감사 노트). USD-소스 시리즈만 hedged_share<0.5일 때 `_to_krw` 적용, pykrx·cash·a4는 제외. 버킷별 적용 여부 `logger.info` 기록.
- [ ] **A1-4: 통과 확인** (기존 `test_bucket_proxies.py`는 universe 디스크 IO가 새로 생기므로 `_hedged_share_by_bucket` monkeypatch 추가)
- [ ] **A1-5: 커밋** — `fix(sigma): KRW-numeraire proxies — name-derived hedged-share rule, a4=USDKRW (F2)`

### Task A2: 주간 리샘플 + 핀 단일 통제 + frequency 관통

- [ ] **A2-1: 실패 테스트** — `test_bucket_cov.py` 추가분 (rev1: min_count 반영)

```python
def test_weekly_resample_compounding_and_nan_weeks():
    idx = pd.bdate_range("2026-01-05", periods=10)
    r = pd.DataFrame({"a": [0.01]*10, "b": [np.nan]*5 + [0.0]*5}, index=idx)
    wk = bucket_cov._to_weekly(r)
    assert abs(wk["a"].iloc[0] - (1.01**5 - 1)) < 1e-12
    assert np.isnan(wk["b"].iloc[0])         # 全-NaN 주는 NaN 유지 (min_count=1)

def test_legacy_min_obs_kwarg_ignored():
    idx = pd.bdate_range("2024-01-01", periods=800)   # ≈167주 ≥ WEEKLY_MIN_OBS
    r = pd.DataFrame(np.random.default_rng(0).normal(0, .01, (800, 3)),
                     index=idx, columns=list("abc"))
    cov, meta = bucket_cov.bucket_covariance(r, min_obs=252)   # 레거시 인자
    assert not cov.empty and meta["pinned"] == []              # 무시되어야 함

def test_annualization_is_52():
    idx = pd.bdate_range("2022-01-03", periods=800)
    r = pd.DataFrame(np.random.default_rng(1).normal(0, .01, (800, 3)),
                     index=idx, columns=list("abc"))
    cov, _ = bucket_cov.bucket_covariance(r)
    approx = bucket_cov._to_weekly(r).var().mean() * 52
    assert 0.6 * approx < np.diag(cov.values).mean() < 1.4 * approx

def test_short_history_bucket_pinned_weekly():
    idx = pd.bdate_range("2024-01-01", periods=800)
    rng = np.random.default_rng(2)
    r = pd.DataFrame({"a": rng.normal(0, .01, 800), "c": rng.normal(0, .01, 800)},
                     index=idx)
    late = pd.Series(np.nan, index=idx); late.iloc[-100:] = 0.001   # ≈20주 < 52
    r["late"] = late
    cov, meta = bucket_cov.bucket_covariance(r)
    assert "late" in meta["pinned"] and "late" not in cov.columns

def test_window_truncated_to_104w():
    idx = pd.bdate_range("2020-01-06", periods=1600)
    r = pd.DataFrame(np.random.default_rng(3).normal(0, .01, (1600, 2)),
                     index=idx, columns=["a", "b"])
    _, meta = bucket_cov.bucket_covariance(r)
    assert meta["n_obs"] <= 104
```

- [ ] **A2-2: 실패 확인** → 5 FAIL
- [ ] **A2-3: 구현** — `bucket_cov.py`:

```python
WEEKLY_MIN_OBS: int = 52
WEEKLY_WINDOW: int = 104
TRADING_WEEKS: int = 52

def _to_weekly(returns: pd.DataFrame) -> pd.DataFrame:
    """일별→W-FRI 주간 복리. min_count=1 필수: 기본 prod()는 全-NaN 주를 1.0(=수익 0)
    으로 조작해 상장 전 구간을 '데이터 있음'으로 둔갑시킨다 (계획감사 A-3 실측)."""
    return (1 + returns).resample("W-FRI").prod(min_count=1).sub(1).dropna(how="all")
```

`bucket_covariance(returns, min_obs=None)`: ① `min_obs`가 명시 전달되면 `logger.warning("min_obs deprecated — WEEKLY_MIN_OBS governs")` 후 **무시**(감사 A-4: 존중하면 주간 프레임에서 전-핀 → 라이브 BL 영구 baseline), ② 주간 변환 후 `valid_counts` 주간 기준 `WEEKLY_MIN_OBS`, ③ inner-join 후 `tail(WEEKLY_WINDOW)`, ④ `compute_robust_cov(joined_weekly, method=..., frequency=TRADING_WEEKS)`.
`cov_estimator.compute_robust_cov(..., frequency: int = 252)`: `CovarianceShrinkage(..., frequency=frequency)` **및 `risk_models.sample_cov(..., frequency=frequency)` 폴백(cov_estimator.py:64)** 양쪽에 관통(감사 A-5 — 폴백 미관통 시 LW 실패가 4.85× 과대 Σ를 조용히 반환). **QIS 경로는 불변**(연율화 자체를 안 함 — docstring에 "frequency는 qis에서 무시" 명시; `graph/conditional_logic.py:49`의 qis 소비자 바이트 동일 보존).
호출부 정리: `trader_allocator.py:357`·`backtest_bl_calibration.py:207,307`에서 `min_obs=252` 인자 제거. `backtest_bl_gate2.py:184`는 기본 호출이라 무변경 — 단 WP-F-2에서 "DATA UNAVAILABLE exit 0" 경로를 **명시적 FAIL로 승격**(F-2 수정).
- [ ] **A2-4: 통과 확인** — 신규 5 + 기존 bucket_cov 갱신분
- [ ] **A2-5: 스펙 개정 노트** — §4.2에 "2026-08-15: KRW numeraire + W-FRI 주간(창 104주, min 52주) — 감사 F2/F4" 추가
- [ ] **A2-6: 회귀 스위트 (범위 확대 — 감사 A-7)** — `pytest tests/unit/skills/portfolio/ tests/unit/backtest/ tests/unit/agents/trader/ tests/integration/test_confidence_scaled_prior_e2e.py -q` 전부 PASS
- [ ] **A2-7: 커밋** — `fix(sigma): weekly W-FRI resample (min_count=1), 104w window, WEEKLY_MIN_OBS single control (F4)`

---

## WP-E: 모멘텀 패닉 감쇠 (F6) — *A 다음, 순서 2번*

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py` (감쇠 조건 + `_aum_top_k` + InfeasibleBucket 경로 포함)
- Create: `tradingagents/skills/portfolio/panic_thresholds.py` (명명 상수 + YAML 패리티)
- Test: `tests/unit/agents/trader/test_momentum_damper.py`(신규 — 기존 5개 파일과 충돌 없음 확인됨)

### Task E1: 임계 상수 모듈 (MF-4)

- [ ] **E1-1: 실패 테스트** — `tests/unit/agents/trader/test_momentum_damper.py`:

```python
def test_panic_thresholds_match_trigger_yaml():
    # daily_triggers는 정규식 파서 — 상수는 YAML 문자열에만 존재(감사 MF-4).
    # 단일 소스 상수 + YAML 패리티 테스트로 드리프트 차단.
    import yaml
    from tradingagents.skills.portfolio.panic_thresholds import VIX_PANIC, VKOSPI_PANIC
    cfg = yaml.safe_load(open("presets/triggers_default.yaml", encoding="utf-8"))
    conds = " ".join(t["condition"] for t in cfg["triggers"])
    assert f"vix > {VIX_PANIC:g}" in conds and f"vkospi > {VKOSPI_PANIC:g}" in conds
```

- [ ] **E1-2 → E1-4**: FAIL 확인 → `panic_thresholds.py`(`VIX_PANIC: float = 30.0`, `VKOSPI_PANIC: float = 25.0`, YAML 상호참조 주석) → PASS → 커밋 `feat(selection): panic threshold constants with trigger-YAML parity (F6)`

### Task E2: 감쇠 조건 + AUM-top-K 선정 후퇴

- [ ] **E2-1: 실패 테스트** (실제 속성 경로 — 감사 MF-2로 확정: `RiskReport.vkospi: VolatilitySnapshot`(schemas/reports.py:98)·`.current_value`(schemas/risk.py:8-16), `RiskReport.vix`(reports.py:97)):

```python
def test_damper_on_quadrant_change():
    state = _mk_state(quadrant="recession_disinflation",
                      prev_attr_quadrant="growth_disinflation", vkospi=15.0, vix=12.0)
    out = _run_allocator(state)
    assert out["allocation_attribution"]["step_b"]["momentum_damped"] == "quadrant_transition"
    # 감쇠 시 het 버킷 선정 = _aum_top_k 결과 (모멘텀 상위와 다른 집합)
    assert set(out["candidate_set"].bucket_to_tickers["b3_global_tech"]) == AUM_TOP3_B3

def test_damper_on_panic_vkospi():
    state = _mk_state(quadrant="growth_disinflation",
                      prev_attr_quadrant="growth_disinflation", vkospi=27.0, vix=12.0)
    assert _run_allocator(state)["allocation_attribution"]["step_b"]["momentum_damped"] == "panic"

def test_no_damper_normal_and_no_prev():
    state = _mk_state(quadrant="growth_disinflation",
                      prev_attr_quadrant=None, vkospi=15.0, vix=12.0)
    assert _run_allocator(state)["allocation_attribution"]["step_b"]["momentum_damped"] is None

def test_damper_survives_infeasible_bucket_fallback():
    # InfeasibleBucket 재-_allocate 경로(trader_allocator.py:565)에서도 모멘텀 가중이
    # 복귀하지 않아야 함 (감사 MF-3)
    ...
```

- [ ] **E2-2: 실패 확인** → KeyError/AssertionError 4건
- [ ] **E2-3: 구현** — trader node 선정 루프 직전:

```python
# F6 모멘텀 크래시 방어 (Daniel-Moskowitz 2016; Barroso-Santa-Clara 2015).
# 선정 자체를 후퇴시킨다 — momentum=None 은 core-subcategory 1~2종 집중을 유발하므로
# (candidate_selector.py:167→175 _select_core_by_aum, 감사 MF-3) 전용 헬퍼 사용.
_prev_q = ((state.get("previous_portfolio") or {}).get("allocation_attribution", {})
           .get("step_a", {}).get("quadrant"))
_rr = state.get("risk_report")
_vkospi = getattr(getattr(_rr, "vkospi", None), "current_value", None)
_vix = getattr(getattr(_rr, "vix", None), "current_value", None)
if _prev_q and _prev_q != quadrant:
    momentum_damped = "quadrant_transition"
elif (_vkospi is not None and _vkospi > VKOSPI_PANIC) or (_vix is not None and _vix > VIX_PANIC):
    momentum_damped = "panic"
else:
    momentum_damped = None

def _aum_top_k(bucket_key: str, eligible: list[str], k: int) -> list[str]:
    """감쇠 모드 het 선정: AUM 내림차순, underlying_index 중복 제거, top-k.
    het 정상 경로와 동일한 폭(k=top_k)을 유지 — 집중을 늘리지 않는다."""
    seen_idx, out = set(), []
    for t in sorted(eligible, key=lambda t: -aum.get(t, 0.0)):
        ix = idx_of.get(t)
        if ix and ix in seen_idx:
            continue
        seen_idx.add(ix); out.append(t)
        if len(out) >= k:
            break
    return out
```

감쇠 시: het 버킷 selections를 `_aum_top_k(bkey, eligible, top_k)`로 대체하고 배분은 `aum_weighted_allocation` 사용(`_allocate` 내 het/hom 파티션에서 damped면 het_bw를 hom 쪽으로 병합 — **InfeasibleBucket 재호출 경로에도 동일 적용**). `allocation_attribution["step_b"] = {"momentum_damped": momentum_damped}` (step_a만 교체되는 BL 브랜치 특성상 sibling 키 안전 — 감사 확인). 이전-quadrant 소스는 C3 커밋(72d44d1)의 `bl_step_a["quadrant"]`(trader_allocator.py:669) — 감사로 실재 확인.
- [ ] **E2-4: 통과 확인** — 신규 4 + `tests/unit/agents/trader/ -q` (기존 het 테스트는 damper 미발동 픽스처 유지)
- [ ] **E2-5: 문서화 한 줄** — `scripts/run_backtest.py`는 `allocation_attribution`을 체이닝하지 않아(190행 — `{"weights": ...}`만 반환) **quadrant-transition 감쇠는 백테스트에서 비활성** — F-4 보고서에 명시 (감사 MF-2 관련)
- [ ] **E2-6: 커밋** — `fix(selection): momentum panic/transition damper via _aum_top_k — incl. InfeasibleBucket path (F6)`

---

## WP-B: 위기 오버레이 정책 분리 (F1) — *순서 3번*

**Files:**
- Create: `tradingagents/rebalance/crisis_policy.py`
- Modify: `tradingagents/rebalance/overlay.py`, `tradingagents/rebalance/reassess.py:20-27`, `tradingagents/rebalance/daily_full.py`
- Test: `tests/unit/rebalance/test_crisis_policy.py`(신규), `test_overlay.py`(갱신), `tests/unit/rebalance/test_daily_full_policy.py`(신규 — 통합 레벨)

### Task B1: 정책 모듈 (rev0 유지 + CASH·미분류 명시)

- [ ] **B1-1~B1-5**: rev0 B1과 동일하되 구현에 두 가지 추가 — ① 미분류(gaps_bucket=None)는 **fail-open**(매도 가능·목적지 가능)이며 이는 의도임을 주석 명시(감사 N3), ② 스텁 픽스처는 `.bucket` 문자열 비교가 아니라 production과 동일한 `bucket_for_etf` 경유로 구성(감사 확인 노트). 커밋 동일.

### Task B2: 오버레이 — CASH 최후 목적지 + 2단계 컷

- [ ] **B2-1: 실패 테스트** — rev0 2건 + 추가:

```python
def test_cash_is_last_resort_destination():
    # 목적지 ETF들이 single-cap(0.20)·category-cap에 포화되면 잔여는 CASH로 (감사 MF-10).
    w = {"EQ1": 0.60, "KTB1": 0.19, "TIPS1": 0.19, "CASH": 0.02}
    out = defensive_overlay(w, is_risk, 0.40, sell_ok=sell_ok, dest_ok=dest_ok)
    assert out["CASH"] > 0.02 + 1e-9          # 포화 초과분이 현금으로
    assert max(out["KTB1"], out["TIPS1"]) <= 0.20 + 1e-9
```

- [ ] **B2-2 → B2-4**: 구현 — 1단계 sell_ok 위험만 비례 축소, freed는 dest_ok 자산에 **headroom-인지 물채움**(`risk_repair.py:44-58` 패턴 미러: single-cap 0.20 잔여 한도 내 비례, 포화 시 잔여 전액 `CASH` 키 적립); 2단계 보호자산 컷 + warning(라이브 도달 희박 — `CATEGORY_CAPS["FX 및 원자재"]=0.20`가 선행 제한, 가드로만 유지). 커밋 동일 메시지.

### Task B3: reassess 경로 정책 적용 (MF-9)

- [ ] **B3-1: 실패 테스트** — `reassess_target`이 risk 축소 시 보호 버킷을 스케일하지 않음을 단언
- [ ] **B3-2 → B3-4**: `reassess.py:20-27`의 `rf` 스케일 대상에서 `sell_ok=False` 티커 제외(스케일 팩터는 sell-eligible 위험만으로 재계산). TDD 사이클 + 커밋 `fix(rebalance): reassess de-risk respects crisis protection (F1)`

### Task B4: 다운스트림 수선 간섭 방어 (MF-8) — 통합 레벨

- [ ] **B4-1: 실패 테스트** — `test_daily_full_policy.py`: defensive 트리거 발동 시나리오에서 **daily_full 전체 경로**(overlay → `daily_full.py:180-182` 수선 3회) 실행 후 ① `risk ≤ defensive_target + tol` ② 보호 버킷 가중치 미감소 단언 (현행 코드로는 category 수선의 risk-blind 물채움 때문에 FAIL 예상 — 감사 MF-8 실증)
- [ ] **B4-2: 구현** — `repair_category_caps(..., recipient_ok: Callable | None = None)` 옵션 인자(기본 None=현행): defensive 경로에서 `dest_ok` 전달 → 물채움 수혜를 정책 목적지로 한정. 수선 루프 후 `risk > target + tol`이면 overlay 1회 재적용(상한 2회 — 수렴 가드). 보호 컷 방지는 category 수선의 초과-컷 대상에서 보호 티커를 마지막 순위로(비례 컷 유지하되 보호 우선순위 주석).
- [ ] **B4-3 → B4-4**: PASS 확인(신규 + 기존 daily_full·overlay·repair 스위트) + 커밋 `fix(rebalance): policy-aware repair water-fill — defensive target survives downstream repairs (F1)`

---

## WP-C: 회전율 측정 충실화 (F3) — *순서 4번*

**Files:**
- Modify: `tradingagents/skills/mandate/turnover_check.py`, `tradingagents/rebalance/engine.py`, `tradingagents/agents/validator/mandate_validator.py`, `tradingagents/reports/rebalance_plan.py`
- Test: `tests/unit/rebalance/test_engine_turnover.py`(신규), `tests/unit/agents/test_mandate_validator.py`(갱신)

### Task C1: 체결 기반 메트릭 + 검사 권위 단일화 (MF-5/MF-6)

- [ ] **C1-1: 실패 테스트**

```python
def test_monthly_floor_authority_is_engine_trade_notional():
    # 거래 0 + 가격 드리프트 12% → floor 미충족이어야 함 (드리프트 착시 제거)
    validation = _run_monthly_engine(trades=[], drift_pct=0.12, floor=0.10)
    assert any(v.rule == "turnover_floor" for v in validation.violations)

def test_graph_validator_monthly_turnover_is_advisory():
    # 그래프 validator의 월간 회전율 검사는 informational(soft)로 강등 (MF-5:
    # 엔진이 체결 명목을 보는 유일한 곳 — 컷오프 지표의 권위는 한 곳이어야 함)
    report = _run_graph_validator(mode="monthly", prev_weights=PREV, weights=W_SAME)
    tv = [v for v in report.violations if v.rule == "turnover_floor"]
    assert all(v.severity == "soft" for v in tv)
    assert report.passed                       # soft는 통과를 막지 않음

def test_cash_phantom_excluded_in_validate_rebalance():
    # 실제 팬텀 지점(감사 MF-6): full_wv는 CASH 포함, previous_weights는 미포함
    # → validate 경로에서 CASH 를 delta 집계에서 제외해야 함
    v = _run_validate_rebalance(realized={"A": 0.5, "CASH": 0.5},
                                previous={"A": 0.5}, floor=0.10)
    assert not any(x.rule == "turnover_floor" and "phantom" not in x.description
                   for x in v.violations if x.severity == "hard")
```

- [ ] **C1-2: 실패 확인**
- [ ] **C1-3: 구현** —
  - `turnover_check.py`: 룰북 §3 인용 주석(rev0 그대로) + `compute_trade_turnover(*, buy_krw, sell_krw, begin_value, end_value)` 헬퍼(§C2의 월누적용 — **per-plan 분모 개선 주장은 철회**: `denom = invested + cash_residual == current_value`가 항등임이 감사 MF-6로 증명됨). initial 경로(weight-기반, previous=None)는 유지 + docstring에 "all-buys라 체결 기반과 동치, 사실상 항진(tautological)" 명시.
  - `engine.py`: `validate_rebalance(..., trade_turnover: float | None = None)` — monthly floor는 `trade_turnover`(= `plan_out["turnover"]`, engine.py:152 기존 계산)로만 검사. weight-delta 재유도 제거. CASH는 delta 집계에서 제외.
  - `mandate_validator.py:210-220`: monthly 모드의 turnover Violation `severity`를 `"soft"`로 강등 + description에 "advisory — 권위는 rebalance engine 체결 기반 검사" 명시. (initial 모드는 hard 유지 — all-buys 동치.)
- [ ] **C1-4: 통과 확인** — 신규 3 + `tests/unit/agents/test_mandate_validator.py` 갱신분 + `tests/unit/rebalance/`
- [ ] **C1-5: 커밋** — `fix(turnover): engine trade-notional is the single monthly-floor authority; graph check advisory (F3)`

### Task C2: 월누적 추적 (MF-7 반영)

- [ ] **C2-1: 선행 — 필드 영속화**: `reports/rebalance_plan.py`의 JSON writer에 `buy_krw`/`sell_krw`/`begin_value`/`end_value` 추가(현재 turnover만 저장 — 감사 확인). 실패 테스트 → 구현 → PASS
- [ ] **C2-2: MTD 집계**: 글롭은 실제 파일명 규약 **`artifacts/<YYYY-MM>-*/*(rebalancing).json`**(괄호 — engine.py:233-235 확인). 당월 파일들의 `buy_krw+sell_krw` 합 ÷ 당월 관측 `begin_value` 평균 → `turnover_month_to_date` + `projected_shortfall`. **주의 명시: MTD는 필드 영속화 이후 아티팩트부터 완전** — 이전 달 소급 불가. Slack notify 경고 1줄.
- [ ] **C2-3: 커밋** — `feat(turnover): month-to-date cumulative tracking from persisted trade notionals (F3)`

---

## WP-D: 클러스터 사각지대 (F5) — *순서 5번, 측정 게이트 방식*

> **rev1 재설계 (MF-1).** 감사 실측: 66종 캐시에서 avg-linkage @0.7 전수 클러스터링 → 33종 메가클러스터, 77% 편입, 수혜 풀 15종. 190종에선 악화 확실(주식 3버킷 82종이 동일 시장 팩터). 이 상태로 35% cap을 물리면 ① cap이 사실상 주식 35% 상한(자체 규율이 mandate 0.70보다 훨씬 엄격해져 BL 리스크 예산을 무단 정복), ② `cluster_repair.py:53-76`의 수혜 포화 → 전체 재정규화로 위반 복원, ③ hard 위반 → 2회 재시도 → min-var 폴백, ④ daily 경로(daily_full.py:180-182)엔 cluster 수선이 아예 없어 매일 hard 위반 아티팩트. **따라서 전수화는 측정으로 설계를 확정한 뒤 다이얼 가드로 도입한다.**

### Task D0: 측정 게이트 (구현 전, 결정 산출물)

- [x] **D0-1**: 스크립트 `scripts/measure_cluster_universe.py` — 전수(190종, 252d, min_periods=126) 상관으로 {avg-linkage 0.7 / avg 0.8 / **complete-linkage 0.7**} 3안의 클러스터 분포 산출 + 최근 아티팩트 2개의 실보유에 각 안을 적용해 **"보유-멤버 합 기준 최대 클러스터 가중"**과 35% cap 위반 여부를 표로 출력 → `artifacts/cluster_universe_measurement.json`

  > **D0-1 측정 결과 (2026-08-18 실행 — 전수 190종, 최근 252거래일, 전 종목 ≥126d 충족):**
  > - avg@0.7: 23군집 · 최대 32종(b1 한국주식 23 + b3 글로벌테크 8, 내부상관 0.873) · 전수의 78.9% 편입 — 감사 예상("주식 82종 메가클러스터")보다 온건
  > - avg@0.8: 25군집 · 최대 26종 · 67.4% 편입 / complete@0.7: 31군집 · 최대 26종 · 78.4% 편입
  > - 보유-멤버 합 최대 클러스터 가중: avg 양안 06-08 **0.203** / 06-05 **0.249**(최대 클러스터가 아니라 USD-연동 10종·US테크 18종 군집이 최대 보유), complete@0.7은 0.135 — **3안 × 2포트폴리오 전부 cap 0.35 위반 0건 (non-binding)**
  > - 함의: "그래프는 전수, 집행은 보유-멤버 합" semantics면 현 보유 기준 어느 안도 배분 마비 없음 — D0-2 사용자 결정 대기 (상세: `artifacts/cluster_universe_measurement.json`)
- [x] **D0-2**: **사용자 결정 게이트** — 3안 + "cap을 보유-멤버 합에만 적용(그래프는 전수, 집행은 보유)" 조합 중 선택. 선택 기준: F5의 원목적(보유 집중의 사각지대 제거)을 달성하되 최대 보유-클러스터 가중이 BL 리스크 예산과 양립(≈ cap 0.35가 정상 장에서 non-binding)할 것
- [x] **D0-3**: 결정 기록 커밋 — `docs(cluster): universe-clustering measurement + decision (F5)`

  > **D0-2 사용자 결정 (2026-08-18): complete-linkage @ threshold 0.7** — 그래프는 전수(최근 252d 중 ≥126d 반환 이력 전 종목, `min_periods=126`), 집행(cap 0.35)은 현행대로 보유-멤버 합.
  > - **근거**: ① 단일-테마 의미론이 가장 엄격 — complete linkage 는 군집 내 *모든 쌍* 상관 ≥0.7 을 보장해 average 식 메가클러스터 병합(연쇄 편입)이 없음. ② 실보유 2개 포트폴리오(06-05/06-08)에서 보유-멤버 합 최대 클러스터 가중 **0.135** 로 3안 중 최저(avg 양안은 0.203/0.249) — cap 0.35 대비 여유 최대. ③ 3안 × 2포트폴리오 전부 **cap 위반 0건**(정상 장에서 non-binding 확인) — F5 원목적(사각지대 제거)과 BL 리스크 예산 양립. 상세: `artifacts/cluster_universe_measurement.json`.
  > - **채택 파라미터**: `linkage_method="complete"`, threshold 0.7(불변), `min_periods=126`, 풀 자격 `MIN_CLUSTER_HISTORY_DAYS=126`. `cluster_full_universe` 다이얼(기본 **False**) 가드 — 기본 ON 전환은 WP-F 후 사용자 승인 별도 커밋.

### Task D1: 결정안 구현 (다이얼 가드)

- [ ] **D1-1**: `default_config.py`에 `cluster_full_universe: bool = False` 다이얼(use_bl 패턴 미러). ON일 때: `technical_analyst.py:206-213`의 클러스터 입력을 `returns.loc[:, returns.notna().sum() >= 126]`(명명 상수 `MIN_CLUSTER_HISTORY_DAYS=126`)로, `correlation_cluster.py`에 `min_periods` kwarg + D0 결정 linkage 적용, 로그 라인(`:214-217`)의 `returns_top` 참조 갱신
- [ ] **D1-2**: **집행 의미 확정**: `validate_correlation_concentration`·`repair_cluster_cap`이 클러스터의 **보유-멤버 합**에 cap 적용(현행과 동일 — 이미 held 교집합, 감사 확인: `cluster_repair.py:25` `members = [t for t in cluster.members if t in out]`) — 단 수혜 풀은 "위반 클러스터 비멤버" 전체(현행 `all_cluster_members` 제외에서 **위반-클러스터-멤버 제외로 완화**: 전수 그래프에선 비위반 클러스터 멤버도 정당한 수혜자) + 포화 시 전체 재정규화 대신 **CASH 적립 폴백**(위반 복원 방지 — MF-1 체인 ②)
- [ ] **D1-3**: `daily_full.py:180-182` 수선 루프에 `repair_cluster_cap` 추가 (다이얼 ON일 때 유효한 신 클러스터가 daily 검증(engine.py:189)에 유입되므로 — MF-1 체인 ④)
- [ ] **D1-4**: TDD — D0 결정안 기준 클러스터 산출 테스트 + 수혜 완화·CASH 폴백 테스트 + daily 수선 테스트. 라이브 스모크로 다이얼 ON 1회 실행해 cap 발동·클러스터 크기 로그 캡처
- [ ] **D1-5**: 커밋 — `feat(cluster): full-universe clustering behind cluster_full_universe dial — <D0 결정안> (F5)`

> 다이얼 기본 ON 전환은 WP-F diff 검토 후 사용자 승인으로 별도 커밋.

---

## WP-F: 시스템 검증·재캘리브레이션 (전 WP 후)

- [ ] **F-1: 전체 스위트** — `pytest tests/ -q -m "not eval and not network"` → 기지 환경실패 1건 외 전부 PASS
- [ ] **F-2: gate-2 ⓐ–ⓕ** — 신 Σ 실행. **개정: `_fetch_sigma` 빈 반환 시 "DATA UNAVAILABLE" exit 0이 아니라 exit 1로 승격**(감사 A-4 — 게이트가 우연히 스킵되는 것 방지). 6건 전부 PASS 필수
- [ ] **F-3: 신구 Σ diff** — A0의 사전 아티팩트(`sigma_v2_baseline.json`) vs 신 Σ 동일 날짜 산출 비교 → `artifacts/sigma_v2_diff.json` + 버킷별 Δ·핀 목록 변화·위험합 변화 표. **사용자 검토 게이트**
- [ ] **F-4: 캘리브레이션 재실행** — `backtest_bl_calibration.py` 신 Σ 기준 turnover_cap {0.35/0.50/0.65} 스윕. **보고서에 명시(감사 노트)**: 결과 이동은 ①KRW 실현수익 ②KRW+주간 Σ ③모멘텀 랭킹 변화 3원인이 합성된 것이며, F6 quadrant-transition 감쇠는 백테스트에서 비활성(E2-5). dial 변경은 승인제
- [ ] **F-5: 라이브 스모크** — `smoke_signal_confidence.py` + mock E2E(`-m slow`) PASS
- [ ] **F-6: 종합 보고** — 수정 요약 + diff 해석 + dial 권고 + 잔여 리스크

---

## 리스크 레지스터 (rev1)

| 리스크 | 완화 |
|---|---|
| 주간화 Σ 스케일 변화 → dial 부적합 | F-4 재캘리브레이션 게이트, 승인제 |
| `min_obs` 레거시 호출부 잔존 → 전-핀/우회 | A2 kwarg-무시 + deprecation 로그 + 호출부 2곳 제거 + A2-6 확대 회귀 |
| 전수 클러스터 메가클러스터 → 배분 마비 | **D0 측정 게이트 + 다이얼 기본 OFF + CASH 폴백** (rev1 재설계) |
| category 수선이 방어 목표·보호를 되돌림 | B4 통합 테스트 + recipient_ok + overlay 재적용 가드 |
| 그래프/엔진 이중 floor 검사 불일치 | C1 권위 단일화(엔진 hard, 그래프 soft) |
| KRW 합성 날짜 정렬 | `_to_krw` inner-join·ffill 금지 + min_count=1 |
| E 이전-quadrant 부재 | None → 감쇠 없음(회귀 0), 백테스트 비활성은 문서화 |
| 대회 잔여 2주 | 커밋만·푸시 수동, F-3 게이트 후 사용자 반영 결정 |

## Self-Review (rev1)

- 감사 must-fix 매핑: Σ감사 1→A1(이름 유도+실배선 테스트), 2→A1(load_universe 경로), 3→A2(min_count), 4→A2(kwarg 무시+호출부), 5→A2(frequency 폴백 관통·QIS 불변), 6→A0(사전 아티팩트), 7→A2-6 / 운용감사 MF-1→D0-D1, 2→E2(실경로)+E2-5, 3→E2(_aum_top_k+Infeasible), 4→E1, 5→C1(권위 단일화), 6→C1(주장 철회+CASH 테스트 재규정), 7→C2(글롭·필드), 8→B4, 9→B3, 10→B2(CASH), 11→G9(D 최후미+다이얼), 12→A1(=Σ감사1)
- 심볼 실재 규칙 준수: 본 rev1의 모든 파일:라인·속성·글롭은 두 감사가 grep/실행으로 확인한 것만 사용
