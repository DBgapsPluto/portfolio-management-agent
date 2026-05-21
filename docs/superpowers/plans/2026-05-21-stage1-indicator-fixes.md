# Stage 1 Indicator 4-Issue Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 직전 grilling 세션 (2026-05-21) 에서 식별된 Stage 1 의 4개 indicator design 결함 (yield_curve / risk_appetite / fx / fed_path) 을 holdout backtest 검증 하에 mega-PR 1개 (6 commit) 로 수정.

**Architecture:** Branch `feat/stage1-indicator-fixes` 에 6 commit (C0~C5) 차곡차곡 쌓는 mega-PR. 각 commit independently revertable. C0 (holdout harness) 가 채택/폐기 기준을 결정 → C1~C4 가 issue 별 fix → C5 가 docs 정합.

**Tech Stack:** Python 3.12, pytest, pydantic v2, pandas, FRED API (`fredapi`), yfinance.

**Spec:** `docs/superpowers/specs/2026-05-21-stage1-indicator-fixes-design.md`

**Execution Protocol:** `docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md` 8 원칙 그대로 적용 (filesystem-as-state).

**Decision Log:** `artifacts/2026-05-21/decisions.md` — D0~D11 누적.

---

## File Structure

### Created
- `scripts/measure_stage1_holdout.py` — 2022-06 ~ 2024-12 false-positive 측정 harness
- `tests/scripts/test_measure_stage1_holdout.py` — harness smoke test
- `tests/unit/skills/test_macro_risk_appetite.py` — C1 composite logic test
- `artifacts/2026-05-21/holdout/README.md` — 측정 protocol
- `artifacts/2026-05-21/holdout/baseline_fp.json` — baseline rule fire 일수
- `artifacts/2026-05-21/holdout/proposed_fp.json` — proposed rule fire 일수
- `artifacts/2026-05-21/holdout/summary.md` — C5 의 최종 비교 표

### Modified
- `tradingagents/dataflows/fred.py` (line ~기존 series 목록) — `BAMLH0A0HYM2`, `DGS1` 추가
- `tradingagents/schemas/macro.py`:
  - line 17-22 `YieldCurveSnapshot` — 4 신규 field
  - line 178-189 `RiskAppetiteSnapshot` — 4 신규 field
  - line 167-175 `FXSnapshot` — Literal 5값, level/Z field 추가
  - line 156-164 `FedPathSnapshot` — 4 신규 field
- `tradingagents/skills/macro/yield_curve.py` — sequential framework
- `tradingagents/skills/macro/risk_appetite.py` — composite + `RiskAppetiteConfig`
- `tradingagents/skills/macro/fx.py` — hybrid + `FXRegimeConfig`
- `tradingagents/skills/macro/fed_path.py` — multi-tenor display
- `tradingagents/agents/analysts/macro_quant_analyst.py` — wire (HY OAS, VIX 1m/3m, DGS1, DGS6MO)
- `prompts/macro-analysis.md` — enum 설명 update
- `tests/unit/skills/test_macro_yield_curve.py` — C2 sequential test
- `tests/unit/skills/test_macro_tier3.py` — C3 structural_weak test
- `tests/unit/skills/test_macro_regime.py` — C3 fixture
- `tests/unit/skills/test_macro_fed_path.py` — C4 multi-tenor test
- `tests/integration/test_eval_regime_classifier.py` — C3 8 fixture 재검토
- `tests/unit/test_schemas_macro.py` — 신규 field default test
- `docs/stage1. macro_quant.md` — C5 모든 section update

---

## Branch Setup

### Task 0: 작업 branch 생성 (이미 완료)

- [x] **Step 0.1: 현재 branch 확인**

```powershell
git status --short
git branch --show-current
```

Expected: branch `feat/stage1-indicator-fixes` (이미 분기 완료, base `origin/feat/db-gaps-redesign` tip `77f70b2`).

- [x] **Step 0.2: artifacts/2026-05-21/ + decisions.md 생성**

`artifacts/2026-05-21/decisions.md` D0~D11 정의 완료.

- [ ] **Step 0.3: Baseline test sweep**

```powershell
pytest tests/unit/ -q --timeout=30 2>&1 | Select-Object -Last 3
```

Expected: 모든 unit test PASS (직전 PR 기준 364). FAIL 있으면 본 PR 작업 전 별도 해결.

---

## C0: Holdout Backtest Harness (~1~2시간)

**해결 이슈:** 채택 기준 인프라.

**Pre-condition:**
- [ ] Task 0 완료
- [ ] FRED/yfinance API key `.env` 에 존재 (직전 PR 에서 set 됨)

### Task C0.1: 측정 protocol 문서

- [ ] **Step C0.1.1:** `artifacts/2026-05-21/holdout/README.md` 작성
  - 측정 window: 2022-06-01 ~ 2024-12-31 (NBER recession 없음)
  - 4 indicator 의 baseline rule 정의 (현재 코드에서 추출)
  - 4 indicator 의 proposed rule 정의 (spec §3)
  - 채택 기준 (D11): 50% FP 감소
  - FN 검증 window: 2008-09, 2020-03 (baseline + proposed 모두 fire 해야 함)

### Task C0.2: Harness 구현

- [ ] **Step C0.2.1:** `scripts/measure_stage1_holdout.py` 작성

구조:
```python
def main():
    fred = FredClient(...)
    spreads_5y = fred.get('T10Y2Y', start='2008-01-01', end='2024-12-31')
    # ... 각 데이터 시리즈 fetch

    holdout_window = pd.date_range('2022-06-01', '2024-12-31', freq='B')
    fn_dates = [pd.Timestamp('2008-09-15'), pd.Timestamp('2020-03-15')]

    results = {}
    for date in holdout_window + fn_dates:
        results[str(date.date())] = {
            'yc_baseline': baseline_yc_rule(spreads_5y, date),
            'yc_proposed': proposed_yc_rule(spreads_5y, two_y, ten_y, date),
            'cuau_baseline': baseline_cuau_rule(cu, au, date),
            'cuau_proposed': proposed_cuau_rule(cu, au, hy_oas, vix_1m, vix_3m, date),
            'fx_baseline': baseline_fx_rule(usd_krw, dxy, date),
            'fx_proposed': proposed_fx_rule(usd_krw, dxy, date),
        }
    json.dump(results, open('artifacts/2026-05-21/holdout/raw_daily.json', 'w'))

    # 집계
    fp_counts = {
        'yc_baseline_holdout_fp': sum(1 for d in holdout_window if results[str(d.date())]['yc_baseline']),
        'yc_proposed_holdout_fp': sum(1 for d in holdout_window if results[str(d.date())]['yc_proposed']),
        # ... 모든 6 카운트
    }
    json.dump(fp_counts, open('artifacts/2026-05-21/holdout/summary_counts.json', 'w'))

    # FN 체크
    for fn_date in fn_dates:
        r = results[str(fn_date.date())]
        print(f"FN {fn_date.date()}: yc_b={r['yc_baseline']}, yc_p={r['yc_proposed']}, ...")
```

**중요:** 본 commit (C0) 에서는 `proposed_*_rule` 들은 모두 **placeholder** (return False). C1~C3 commit 에서 그 indicator 의 proposed rule 만 채워짐. 즉 C0 는 인프라 + baseline 만 측정.

- [ ] **Step C0.2.2:** `tests/scripts/test_measure_stage1_holdout.py` smoke test
  - 10일짜리 짧은 window 로 import + run
  - Output JSON schema 가 expected key 들 포함

- [ ] **Step C0.2.3:** Baseline 측정 실행

```powershell
python scripts/measure_stage1_holdout.py --mode baseline
```

Expected: `artifacts/2026-05-21/holdout/baseline_fp.json` 채워짐. FP 개수가 정상 범위 (e.g., yc_baseline > 0, fx_baseline > 100 — 1380원대 oversensitive 검증).

### Task C0.3: Commit + push

- [ ] **Step C0.3.1:** 

```powershell
git add scripts/measure_stage1_holdout.py tests/scripts/test_measure_stage1_holdout.py artifacts/2026-05-21/
git status --short
git commit -m "feat(stage1): holdout backtest harness — 2022-06~2024-12 false-positive infrastructure"
```

Commit message 본문:
- baseline FP 수치 quote
- proposed 는 C1~C3 에서 채워질 예정 명시

- [ ] **Step C0.3.2:** `pytest tests/unit/ -q --timeout=30 2>&1 | Select-Object -Last 3` PASS quote

### Task C0.4: VXVCLS 가용성 검증 (D4 결정)

- [ ] **Step C0.4.1:**

```powershell
python -c "from tradingagents.dataflows.fred import get_series; from datetime import date; print(get_series('VXVCLS', date(2025,1,1), date(2025,2,1)).tail())"
```

성공 → `decisions.md` D4 = "available" 갱신
실패 → D4 = "unavailable", D5 = "yfinance ^VIX3M 사용" 갱신

- [ ] **Step C0.4.2:** decisions.md update + commit

```powershell
git add artifacts/2026-05-21/decisions.md
git commit -m "decision(stage1): D4 VXVCLS availability — [available|unavailable, fallback ^VIX3M]"
```

---

## C1: HY OAS Composite (#2 fix, ~2~3시간)

**Pre-condition:**
- [ ] C0 완료, D4 결정 commit
- [ ] decisions.md Read 해서 D4 결과 확인

### Task C1.1: FRED 시리즈 추가

- [ ] **Step C1.1.1:** `tradingagents/dataflows/fred.py` 에 `BAMLH0A0HYM2` 추가
  - 기존 series dict 또는 fetch 함수에 endpoint 등록
  - Test (or REPL): `get_series('BAMLH0A0HYM2', date(2024,1,1), date(2024,12,31)).tail()` 가 빈 series 아님

- [ ] **Step C1.1.2:** VIX 1m / 3m 데이터 소스 결정 (D4 결과 반영)
  - D4=available: FRED `VIXCLS`, `VXVCLS`
  - D4=unavailable: yfinance `^VIX`, `^VIX3M`

### Task C1.2: Schema 확장

- [ ] **Step C1.2.1:** `tradingagents/schemas/macro.py::RiskAppetiteSnapshot` 4 신규 field 추가 (spec §3.2)

```python
hy_oas: float = Field(default=0.0, description="BoA US HY OAS, % spread")
hy_oas_percentile_3y: float = Field(default=0.5, ge=0, le=1)
vix_contango: float = Field(default=1.0, description="VIX 3m / 1m")
composite_score: float = Field(default=0.5, ge=0, le=1, description="0=risk_off, 1=risk_on")
divergence_flag: bool = Field(default=False, description="Cu/Au와 HY가 0.4+ disagreement")
```

### Task C1.3: Composite 로직

- [ ] **Step C1.3.1:** `tradingagents/skills/macro/risk_appetite.py` 에 `RiskAppetiteConfig` dataclass 추가

```python
from dataclasses import dataclass

@dataclass
class RiskAppetiteConfig:
    w_hy: float = 0.55          # spec §3.2 D6 default
    w_cu_au: float = 0.20
    w_vix: float = 0.25
    risk_on_threshold: float = 0.65
    risk_off_threshold: float = 0.35
    divergence_threshold: float = 0.40
```

- [ ] **Step C1.3.2:** `compute_risk_appetite` signature 확장

```python
def compute_risk_appetite(
    copper, gold, as_of,
    hy_oas: pd.Series | None = None,
    vix_1m: pd.Series | None = None,
    vix_3m: pd.Series | None = None,
    config: RiskAppetiteConfig | None = None,
) -> RiskAppetiteSnapshot:
```

- [ ] **Step C1.3.3:** Composite 계산 + sigmoid VIX 변환

```python
config = config or RiskAppetiteConfig()
hy_pct = (hy_oas_3y < hy_oas.iloc[-1]).mean() if hy_oas is not None else 0.5
vix_contango = vix_3m.iloc[-1] / vix_1m.iloc[-1] if vix_1m and vix_3m else 1.0
vix_component = max(0.0, min(1.0, (vix_contango - 0.90) / 0.20))

composite = (
    (1 - hy_pct) * config.w_hy
    + cu_au_pct  * config.w_cu_au
    + vix_component * config.w_vix
)
divergence = abs(cu_au_pct - (1 - hy_pct)) > config.divergence_threshold

signal = (
    "risk_on" if composite > config.risk_on_threshold
    else "risk_off" if composite < config.risk_off_threshold
    else "neutral"
)
```

### Task C1.4: Analyst wire

- [ ] **Step C1.4.1:** `tradingagents/agents/analysts/macro_quant_analyst.py` 에 HY OAS / VIX 1m / VIX 3m fetch + risk_appetite 호출 시 전달

### Task C1.5: Test

- [ ] **Step C1.5.1:** `tests/unit/skills/test_macro_risk_appetite.py` 신규 (또는 `test_macro_tier3.py` 에 추가)
  - HY OAS low + Cu/Au high → risk_on
  - HY OAS high → risk_off (Cu/Au 무관)
  - HY OAS low + Cu/Au low → divergence_flag=True
  - VIX backwardation (contango < 1.0) → vix_component=0

- [ ] **Step C1.5.2:** `pytest tests/unit/skills/test_macro_risk_appetite.py -v 2>&1 | Select-Object -Last 10` PASS quote

### Task C1.6: Holdout 갱신 (`proposed_cuau` 채움)

- [ ] **Step C1.6.1:** `scripts/measure_stage1_holdout.py` 의 `proposed_cuau_rule` 채우기 (placeholder → 실제 composite)

- [ ] **Step C1.6.2:** Re-run

```powershell
python scripts/measure_stage1_holdout.py --mode proposed --indicator cuau
```

- [ ] **Step C1.6.3:** Compare to baseline
  - 결과 `artifacts/2026-05-21/holdout/proposed_fp.json` 의 `cuau_proposed_holdout_fp` vs `cuau_baseline_holdout_fp`
  - 채택 기준 (D11): proposed ≤ baseline × 0.50

### Task C1.7: Commit

- [ ] **Step C1.7.1:**

```powershell
git add tradingagents/dataflows/fred.py tradingagents/schemas/macro.py tradingagents/skills/macro/risk_appetite.py tradingagents/agents/analysts/macro_quant_analyst.py tests/unit/skills/test_macro_risk_appetite.py scripts/measure_stage1_holdout.py artifacts/2026-05-21/holdout/proposed_fp.json
git commit -m "feat(stage1): HY OAS + risk_appetite composite (#2 fix)"
```

Body:
- Holdout FP: baseline X일 → proposed Y일 (-Z%)
- Acceptance D11 [pass|fail]
- D6 weights: 0.55/0.20/0.25 default, RiskAppetiteConfig dataclass 외부화

---

## C2: YC Sequential Framework (#1 fix, ~2~3시간)

**Pre-condition:**
- [ ] C0 완료
- [ ] D7 결정: percentile-based 변환 — 5pct = "deeply inverted" 기준 사용 vs 절대 -25bps hybrid

### Task C2.1: Schema 확장

- [ ] **Step C2.1.1:** `YieldCurveSnapshot` 에 4 신규 field 추가 (spec §3.1)

```python
recession_trigger: bool = Field(default=False)
min_spread_5y_bps: float = Field(default=0.0)
recovery_pct: float = Field(default=0.0, ge=-1.0, le=2.0)
steepener_type: Literal["none", "bull", "bear"] = Field(default="none")
```

### Task C2.2: yield_curve.py 로직

- [ ] **Step C2.2.1:** `_compute_recession_trigger(spread_5y, two_y, ten_y)` 함수 추가 (spec §3.1)

- [ ] **Step C2.2.2:** `compute_yield_curve` signature 에 `two_y_series`, `ten_y_series` 인자 추가 (기존 spread 외에 개별 시리즈도 필요)

- [ ] **Step C2.2.3:** Steepener type 분류
  - bull: `two_y_chg_3m < -0.30 AND two_y_chg_3m < ten_y_chg_3m`
  - bear: `ten_y_chg_3m > +0.30 AND ten_y_chg_3m > two_y_chg_3m`

### Task C2.3: Test

- [ ] **Step C2.3.1:** `tests/unit/skills/test_macro_yield_curve.py` 에 sequential test 추가
  - 1990 disinversion (synthetic series) → trigger=True
  - 2022 ongoing inversion (no recovery) → trigger=False, defensive_lean (inverted_days>0)
  - 2024-末 disinversion + bear steepener (synthetic) → trigger=False, steepener_type=bear

- [ ] **Step C2.3.2:** PASS quote

### Task C2.4: Holdout 갱신

- [ ] **Step C2.4.1:** `proposed_yc_rule` 채우기

- [ ] **Step C2.4.2:** Re-run + compare

### Task C2.5: Commit

- [ ] **Step C2.5.1:**

```powershell
git add tradingagents/schemas/macro.py tradingagents/skills/macro/yield_curve.py tests/unit/skills/test_macro_yield_curve.py scripts/measure_stage1_holdout.py artifacts/2026-05-21/holdout/proposed_fp.json
git commit -m "feat(stage1): YC sequential framework — disinversion + bull steepener (#1 fix)"
```

Body:
- Holdout FP: baseline X일 → proposed Y일 (-Z%)
- FN 검증: 1990/2001/2008/2020 disinversion 시점 fire 확인

---

## C3: FX Hybrid + Schema Migration (#3 fix, ~3~4시간)

**Pre-condition:**
- [ ] C0 완료, D8 결정 (5y vs 10y window)

### Task C3.0: D8 결정

- [ ] **Step C3.0.1:**

```powershell
python -c "import yfinance as yf; df = yf.Ticker('KRW=X').history(period='10y'); print(len(df), df.index.min(), df.index.max())"
```

Full 10y → D8 = 10y / partial → D8 = 5y

- [ ] **Step C3.0.2:** decisions.md update + commit

### Task C3.1: Schema 확장 + Migration

- [ ] **Step C3.1.1:** `tradingagents/schemas/macro.py::FXSnapshot` Literal 5값 + 신규 field

```python
regime: Literal["krw_strong", "krw_weak", "krw_structural_weak", "usd_risk_off", "neutral"]
krw_z_score: float = Field(default=0.0, description="1m return Z-score vs 1y")
dxy_z_score: float = Field(default=0.0)
krw_level_percentile: float = Field(default=0.5, ge=0, le=1, description="USD/KRW position in 5y/10y history")
```

- [ ] **Step C3.1.2:** **Schema migration 영향 9 파일 전수 점검 (spec §4.3 Read 의무):**
  - 한 줄씩 체크 — phantom edit 방지

### Task C3.2: fx.py hybrid 로직

- [ ] **Step C3.2.1:** `FXRegimeConfig` dataclass 추가

- [ ] **Step C3.2.2:** `compute_fx_overlay` 재작성 (spec §3.3)
  - Z-score 1y window
  - level percentile 5y or 10y (D8 결과)
  - Hybrid 분류

### Task C3.3: Downstream update

- [ ] **Step C3.3.1:** `tradingagents/agents/analysts/macro_quant_analyst.py` — narrative builder 가 `krw_structural_weak` 인지 (grep 필요)

- [ ] **Step C3.3.2:** `prompts/macro-analysis.md` line 28, 75 — 새 enum 설명 추가

### Task C3.4: Test 갱신

- [ ] **Step C3.4.1:** `tests/unit/skills/test_macro_tier3.py` — 새 test `test_fx_krw_structural_weak`

- [ ] **Step C3.4.2:** `tests/unit/skills/test_macro_regime.py` — fixture 1개 추가

- [ ] **Step C3.4.3:** `tests/integration/test_eval_regime_classifier.py` 8 fixture 재검토
  - line 30 (neutral 1300/0%): 변경 무
  - line 68 (1450/+15%): structural? — krw_level_5y 거의 100pct → structural_weak 가능 / 하지만 +15% = shock → usd_risk_off 유지가 맞을 듯
  - line 92 (1300/+3%): historical low/0pct + krw_z 보통 — neutral 또는 krw_weak? 케이스별 검토
  - line 115 (1280/+8%): shock 패턴 → usd_risk_off
  - line 138 (1130/-2%): krw_strong 유지
  - line 178 (930/-1%): neutral 유지
  - line 201 (1100/+2%): 기존 neutral → Z 변환 후 neutral 유지 또는 krw_weak
  - line 224 (1380/+2.5%): 1380 level pct 0.85~0.95 + Z 0.5~ → structural_weak 가능
  - 각 fixture 별 결정 → decisions.md 에 D12, D13, ... 로 기록

- [ ] **Step C3.4.4:** `pytest tests/unit/ tests/integration/test_eval_regime_classifier.py -v 2>&1 | Select-Object -Last 20` PASS quote

### Task C3.5: Holdout 갱신

- [ ] **Step C3.5.1:** `proposed_fx_rule` 채움 + re-run

- [ ] **Step C3.5.2:** 결과 compare. **추가 보고**: `krw_structural_weak` 일수 분포 (2022-2024 동안 합리적 분포인지)

### Task C3.6: Commit

- [ ] **Step C3.6.1:**

```powershell
git add tradingagents/schemas/macro.py tradingagents/skills/macro/fx.py tradingagents/agents/analysts/macro_quant_analyst.py prompts/macro-analysis.md tests/unit/skills/test_macro_tier3.py tests/unit/skills/test_macro_regime.py tests/integration/test_eval_regime_classifier.py scripts/measure_stage1_holdout.py artifacts/2026-05-21/holdout/proposed_fp.json artifacts/2026-05-21/decisions.md
git commit -m "feat(stage1): FX hybrid Z+level + krw_structural_weak (#3 fix)"
```

Body:
- Holdout FP usd_risk_off: baseline X일 → proposed Y일 (-Z%)
- krw_structural_weak: 2022-06~2024-12 동안 W일 fire (분포 합리성 평가)
- Schema migration 9 파일 update 완료

---

## C4: Fed Path Multi-tenor Display (#4 fix, ~1시간)

**Pre-condition:** C0 완료.

### Task C4.1: FRED 시리즈 추가

- [ ] **Step C4.1.1:** `DGS1` 등록

### Task C4.2: Schema + Logic

- [ ] **Step C4.2.1:** `FedPathSnapshot` 4 신규 field (spec §3.4)

- [ ] **Step C4.2.2:** `compute_fed_path` 인자 `dgs6m`, `dgs1y` 추가 + 신규 field 계산

- [ ] **Step C4.2.3:** **`_classify_view` 로직 변경 절대 X** — 현재 adaptive band 유지

### Task C4.3: Analyst wire

- [ ] **Step C4.3.1:** macro_quant_analyst 가 DGS1/DGS6MO 전달

### Task C4.4: Test

- [ ] **Step C4.4.1:** `tests/unit/skills/test_macro_fed_path.py` 에 multi-tenor test 추가
  - DGS6MO=5.0, DFF=5.25, DGS1=4.75, DGS2=4.5 → path_6m=-25, path_12m=-50, path_24m=-75, implied_moves_12m=-2

- [ ] **Step C4.4.2:** Adaptive band classification 회귀 확인 — `market_view` 가 기존 logic 으로 동작

### Task C4.5: Holdout

Fed 는 classification 변경 없음 → fp 변화 0 예상. 측정 생략 가능. (spec §2 의 C4 holdout 갱신 참조 — baseline=proposed 동일).

### Task C4.6: Commit

- [ ] **Step C4.6.1:**

```powershell
git add tradingagents/dataflows/fred.py tradingagents/schemas/macro.py tradingagents/skills/macro/fed_path.py tradingagents/agents/analysts/macro_quant_analyst.py tests/unit/skills/test_macro_fed_path.py
git commit -m "feat(stage1): Fed path multi-tenor display fields (#4 fix)"
```

Body:
- classification 로직 변경 없음, display field 만 추가
- Holdout: market_view fp 동일 (예상)

---

## C5: Docs + Regression Sweep (~1시간)

### Task C5.1: docs/stage1. macro_quant.md update

- [ ] **Step C5.1.1:**
  - § yield_curve: sequential framework + recession_trigger 의미 추가
  - § fx: hybrid Z+level + krw_structural_weak 의미
  - § risk_appetite: composite (HY OAS dominant) + divergence_flag
  - § fed_path: multi-tenor display
  - § 6.5 hardcoded caveat table 갱신: 해소된 항목 ✅ 표시

### Task C5.2: Final regression

- [ ] **Step C5.2.1:**

```powershell
pytest tests/unit/ -q --timeout=30 2>&1 | Select-Object -Last 5
pytest tests/integration/ -q --timeout=60 2>&1 | Select-Object -Last 5
```

PASS quote.

### Task C5.3: Holdout summary

- [ ] **Step C5.3.1:** `artifacts/2026-05-21/holdout/summary.md` 작성

| Issue | Baseline FP (2022-06~2024-12) | Proposed FP | 감소율 | D11 채택 |
|---|---|---|---|---|
| #1 YC | X일 | Y일 | -Z% | pass/fail |
| #2 Cu/Au | X일 | Y일 | -Z% | pass/fail |
| #3 FX | X일 | Y일 | -Z% | pass/fail |
| #4 Fed | (no class change) | - | - | n/a |

| Indicator | FN window | Baseline fire | Proposed fire |
|---|---|---|---|
| YC | 2008-09 | True | True |
| YC | 2020-03 | True | True |

### Task C5.4: Commit

- [ ] **Step C5.4.1:**

```powershell
git add docs/stage1.* artifacts/2026-05-21/holdout/summary.md
git commit -m "docs(stage1): updated indicator specs + final regression + holdout summary"
```

---

## PR Creation

### Task PR.1: Push

- [ ] **Step PR.1.1:**

```powershell
git push -u origin feat/stage1-indicator-fixes
```

### Task PR.2: gh pr create

- [ ] **Step PR.2.1:**

```powershell
gh pr create --draft --base feat/db-gaps-redesign --title "feat(stage1): 4-issue indicator design fixes" --body "(holdout summary + per-issue acceptance from artifacts/2026-05-21/holdout/summary.md)"
```

Body 구조:
```markdown
## Summary
- Stage 1 의 4개 indicator design 결함 (YC sequential / Cu/Au composite / FX hybrid / Fed display) 을 holdout backtest 검증 하에 수정.
- Cold analysis 기반 — direct grilling 결과 반영.

## Spec & Plan
- Spec: docs/superpowers/specs/2026-05-21-stage1-indicator-fixes-design.md
- Plan: docs/superpowers/plans/2026-05-21-stage1-indicator-fixes.md
- Decisions: artifacts/2026-05-21/decisions.md

## Holdout summary
(summary.md 표 복사)

## Test plan
- [x] unit: pytest tests/unit/ -q
- [x] integration: pytest tests/integration/test_eval_regime_classifier.py
- [x] holdout: scripts/measure_stage1_holdout.py 결과 검증

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## Verification Checklist (PR open 직전)

- [ ] 모든 unit test PASS — quote 마지막 줄
- [ ] integration test_eval_regime_classifier PASS
- [ ] Holdout summary.md 채워짐, D11 각 issue 채택/폐기 명확
- [ ] decisions.md D0~D11 (또는 D13까지) 모두 채워짐, commit hash 기록
- [ ] Schema migration 9 파일 한 줄씩 verify — grep 으로 `krw_structural_weak` 가 모든 expected 위치에 있는지
- [ ] Spec §5 non-goals 가 PR 에 포함 안 되었음을 확인 (CME FedWatch 등)
- [ ] Cold analysis 의 각 결함이 spec/code 에 답변되어 있음 — spec §3 의 각 sub-section 이 cold analysis 결함 #1~#5 명시 답
