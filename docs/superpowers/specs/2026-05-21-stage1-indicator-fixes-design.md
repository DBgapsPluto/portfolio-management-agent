# Stage 1 Indicator 4-Issue Design Fixes — 설계 (Spec)

- **작성일:** 2026-05-21
- **branch:** `feat/stage1-indicator-fixes` (base: `origin/feat/db-gaps-redesign` tip `77f70b2`)
- **PR 단위:** Mega-PR 1개 (commit 6개 — C0 인프라 + C1~C4 issue fix + C5 docs/regression)
- **대상 코드베이스:** `tradingagents/skills/macro/{yield_curve,risk_appetite,fx,fed_path}.py`, `tradingagents/schemas/macro.py`, `tradingagents/dataflows/fred.py`
- **목표:** 직전 grilling 세션에서 식별된 4개 indicator 의 design 결함을 holdout backtest 검증 하에 수정. Anchor 박탈/추가 hardcode/schema migration 비용을 의식적으로 관리.

---

## 1. 배경

### 1.1 식별된 4 결함 (cold analysis 2026-05-21)

| # | indicator | 결함 | Severity |
|---|---|---|---|
| 1 | `yield_curve.py` | `inverted_days_count ≥ 60` 단독 anchor 는 Cam Harvey framework 의 일부만 사용. NBER recession 은 disinversion 직후 시작 (1990/2001/2008/2020 모두) | High |
| 2 | `risk_appetite.py` (Cu/Au) | AI 전력망(Cu), 중앙은행 매집(Au) 등 비순환 수요가 가격 dominance → risk-on/off 신호력 상실 | High |
| 3 | `fx.py` | Absolute threshold (`krw_change > +2%`) 가 slow drift (KRW 1300→1450 over 2y) 를 잡지 못함. 1380원대에서 거의 매일 `usd_risk_off` 오발 | High |
| 4 | `fed_path.py` | `hike/cut/hold` 거친 라벨링. 시장이 가격한 "몇 번의 25bps 인하" 정보 손실. 재가격 속도(repricing speed) 미반영 | Medium |

### 1.2 작업 원칙 (cold analysis 후 합의)

1. **No new hardcoded magic numbers without holdout backtest justification.** 직전 #2~#7 caveat 작업과 일관성. 임계값은 percentile 기반 또는 config dataclass 외부화.
2. **Sequential framework 보존.** Cam Harvey 의 inversion → disinversion → recession 단계를 모두 본다. 기존 anchor 박탈 X, 추가만.
3. **Holdout backtest as precondition.** 2022-06 ~ 2024-12 false positive 카운트로 룰 채택/폐기 결정. C0 가 reject 하면 해당 issue 는 폐기.
4. **Schema migration plan upfront.** 새 enum 값 (`krw_structural_weak`) 추가 시 영향 파일 전수 리스팅 (§4.3).

### 1.3 직전 PR (이미 merged on `origin/feat/db-gaps-redesign`)

`77f70b2 docs(stage1): hardcode caveat + indicator change docs + audit/backtest artifacts` 까지의 작업은 hardcode 를 **명시화** (caveat). 본 PR 은 그 중 indicator design 결함이 있는 4개를 **실질적으로 수정**. caveat ≠ fix.

### 1.4 Stage 2 작업 (`feat/stage2-bottleneck-fixes`) 와의 file overlap

| 파일 | stage1 본 PR | stage2 | overlap? |
|---|---|---|---|
| `skills/macro/yield_curve.py` | yes | no | no |
| `skills/macro/risk_appetite.py` | yes | no | no |
| `skills/macro/fx.py` | yes | no | no |
| `skills/macro/fed_path.py` | yes | no | no |
| `schemas/macro.py` | yes (`FXSnapshot.regime` Literal 확장) | no | no |
| `schemas/research.py` | no | yes | no |
| `skills/research/scenario_mapper.py` | no | yes | no |
| `skills/risk/conditional_stress.py` | no | yes | no |
| `skills/risk/kr_residual_signals.py` | no | yes | no |

→ Conflict 0. 두 branch 가 어느 순서로 merge 되어도 영향 없음.

---

## 2. PR / Commit 구조

### C0 `feat(stage1): holdout backtest harness — 2022-06 ~ 2024-12 false-positive infrastructure`

**목적:** 4개 issue 의 신규 룰 채택/폐기 결정을 holdout 측정에 기반시킨다. **사전 magic number 추가 금지.**

**Created:**
- `scripts/measure_stage1_holdout.py` — 2022-06-01 ~ 2024-12-31 일별로 4개 indicator 의 baseline rule + proposed rule 의 fire 횟수 측정
- `tests/scripts/test_measure_stage1_holdout.py` — smoke test (10일 짧은 window 로 import + run)
- `artifacts/2026-05-21/holdout/README.md` — 측정 protocol + 채택 기준 명시
- `artifacts/2026-05-21/decisions.md` — 결정 log (이미 생성, D0~D11)

**측정 대상 (baseline vs proposed):**
| indicator | baseline | proposed |
|---|---|---|
| YC `recession_anchor` | `inverted_days >= 60` | `was_inverted_recently AND is_re_steepening AND is_bull_steepener` (percentile-based, §3.1) |
| Cu/Au `signal` | `ratio_percentile_1y < 0.3` → risk_off | composite (HY OAS 0.55 + Cu/Au 0.20 + VIX term 0.25) (§3.2) |
| FX `regime` | `krw_change > +2 AND dxy_change > +1` → usd_risk_off | hybrid Z-score + level percentile (§3.3) |
| Fed `market_view` | adaptive band (현재 fixed band 가 아님, 변경 불요) | (display 만 추가, classification 동일) (§3.4) |

**채택 기준 (D11):**
- 2022-06 ~ 2024-12 (NBER 침체 없음) 동안:
  - YC: proposed 의 `recession_anchor=True` 일수 ≤ baseline 의 50%
  - Cu/Au: proposed 의 `signal=risk_off` 일수 ≤ baseline 의 50%
  - FX: proposed 의 `regime=usd_risk_off` 일수 ≤ baseline 의 50%
- FN 검증: 2008-09, 2020-03 (실제 침체 진입) 에서 baseline + proposed 모두 fire 해야 함 (NBER + 실제 drawdown 시점). FN 보존이 우선.

**Test (이 commit 단독으로 pass 해야 함):**
- harness 가 `KeyError` / `IndexError` 없이 2022-06 ~ 2024-12 끝까지 도는지
- 출력 JSON schema 가 `tests/scripts/test_measure_stage1_holdout.py` 의 fixture 와 일치

**Output (이 commit 에는 아직 빈 placeholder):**
- `artifacts/2026-05-21/holdout/baseline_fp.json` — empty `{}`
- `artifacts/2026-05-21/holdout/proposed_fp.json` — empty `{}`

이 산출물은 C1~C3 의 각 commit 끝에서 부분적으로 채워진다. 매 commit 끝의 `pytest tests/scripts/test_measure_stage1_holdout.py` PASS 가 합격선.

---

### C1 `feat(stage1): HY OAS 추가 + risk_appetite composite (#2 fix)`

**해결 이슈:** #2 Cu/Au

**Pre-condition (이 commit 시작 시 의무):**
- D4: VXVCLS FRED 가용성 검증
  - `python -c "from tradingagents.dataflows.fred import get_series; print(get_series('VXVCLS', '2025-01-01', '2025-02-01').tail())"`
  - 성공: D4 = available, VXVCLS 사용
  - 실패: D4 = unavailable, D5 발동 → yfinance `^VIX3M` 으로 데이터 소스 교체
  - 결정 → `artifacts/2026-05-21/decisions.md` 갱신 + commit (이 commit 의 첫 hunk)

**Modified:**
- `tradingagents/dataflows/fred.py` — `BAMLH0A0HYM2` (HY OAS) 추가
- `tradingagents/schemas/macro.py::RiskAppetiteSnapshot` — 신규 필드:
  - `hy_oas_pct: float` — 3y percentile (HY OAS 낮을수록 risk-on)
  - `vix_contango: float` — VIX 3m / 1m
  - `composite_score: float` — 0~1, 1 = risk-on
  - `divergence_flag: bool` — Cu/Au 와 HY 가 ≥0.4 어긋남
  - `signal` Literal 은 그대로 (downstream 호환), 단 결정은 `composite_score` 로
- `tradingagents/skills/macro/risk_appetite.py` — composite 계산 로직:
  - HY OAS 3y percentile (낮을수록 risk-on)
  - Cu/Au 5y percentile (직전 PR 에서 5y 로 확장한 거 그대로)
  - VIX 1m / 3m (contango = 3m/1m > 1.0 = calm)
  - **Step function 금지**: VIX contango 는 `clamp((contango - 0.9) / 0.2, 0, 1) * w` sigmoid 변환
- `tradingagents/skills/macro/risk_appetite.py::RiskAppetiteConfig` — 신규 dataclass, weights 외부화:
  ```python
  @dataclass
  class RiskAppetiteConfig:
      w_hy: float = 0.55
      w_cu_au: float = 0.20
      w_vix: float = 0.25
      risk_on_threshold: float = 0.65
      risk_off_threshold: float = 0.35
      divergence_threshold: float = 0.40
  ```
  Default 는 cold analysis 의 0.55/0.20/0.25. **C0 holdout 결과로 D6 갱신 후 재조정**.
- `tradingagents/agents/analysts/macro_quant_analyst.py` — wire 추가 (HY OAS, VIX 1m/3m 데이터를 risk_appetite 로 전달)

**Test:**
- `tests/unit/skills/test_macro_risk_appetite.py` 신규 (또는 기존 추가):
  - HY OAS 낮음 + Cu/Au 높음 → risk_on
  - HY OAS 높음 → risk_off (Cu/Au 와 무관)
  - HY OAS 낮음 + Cu/Au 낮음 → divergence_flag=True
  - VIX backwardation → vix component=0
- `tests/unit/test_schemas_macro.py` — RiskAppetiteSnapshot 새 필드 default

**Holdout output 갱신:**
- `artifacts/2026-05-21/holdout/baseline_fp.json` ← Cu/Au 단독 룰 결과
- `artifacts/2026-05-21/holdout/proposed_fp.json` ← composite 룰 결과
- commit message 에 비교 quote (예: `baseline FP 187일 → proposed 91일, -51%`)

**Acceptance:** D11 50% 감소 기준 만족 → 채택. 미달 → 본 commit 폐기, 다른 weight 조합 explore 또는 issue close 처리.

---

### C2 `feat(stage1): YC sequential framework — disinversion + bull steepener 추가 (#1 fix)`

**해결 이슈:** #1 yield curve

**핵심 design (cold analysis §1 의 결함 보완):**
- **`inverted_days_count` anchor 박탈 X**, `defensive_lean` 신호로 의미 명확화.
- `recession_trigger` field 신규 추가 — disinversion + bull steepener AND 패턴.
- Bear steepener 별도 flag (term premium 충격, 1994/2013 같은 다른 종류 위험).
- 임계값은 percentile 기반 (절대값 -25bps 등 금지).

**Modified:**
- `tradingagents/schemas/macro.py::YieldCurveSnapshot`:
  - 신규: `recession_trigger: bool`
  - 신규: `min_spread_5y_bps: float` — 최근 5y 최저 spread (역전 깊이 절대치 대신 historical 위치 표시용)
  - 신규: `recovery_pct: float` — 최저점 대비 회복도 (0=여전히 최저, 1=완전 회복)
  - 신규: `steepener_type: Literal["none", "bull", "bear"]` — 어떤 종류의 steepening인지
  - 기존 `inverted_days_count` 유지 (의미: `defensive_lean` proxy)
- `tradingagents/skills/macro/yield_curve.py`:
  - `_detect_disinversion`: 최근 18m 내 spread 가 5y 5pct 이하로 떨어진 적 있고, 현재는 회복 중
  - `_classify_steepener`: 2y 와 10y 3m 변화 비교
    - bull: 2y 가 10y 보다 더 많이 떨어짐 (rate cut 가격)
    - bear: 10y 가 2y 보다 더 많이 오름 (term premium 충격)
    - none: 둘 다 아님
  - `recession_trigger = was_inverted_recently AND is_recovering AND steepener_type == "bull"`
  - **18m window 는 5y percentile 위치 기반으로 정당화** (cold analysis 의 "18m 어디서 왔는가" 비판 답): "최근 5y rolling 의 5pct 이하" 가 1 회라도 발생한 시점부터 현재까지의 기간이 18m 이내인지로 변환

**Test:**
- `tests/unit/skills/test_macro_yield_curve.py`:
  - 1990 (역전 + 종료 직후 fire) — recession_trigger=True
  - 2022 (역전 중 + 회복 안 함) — recession_trigger=False (defensive_lean 만 True)
  - 2024 (역전 종료 + bear steepener) — recession_trigger=False, steepener_type="bear"

**Holdout 갱신:** 2022-06~2024-12 동안 baseline (`inverted_days>=60`) 의 fire 일수 vs proposed 의 fire 일수 비교.

---

### C3 `feat(stage1): FX hybrid regime — Z-score + level percentile + structural label (#3 fix)`

**해결 이슈:** #3 FX

**Pre-condition:**
- D8: yfinance USD/KRW 10y data 가용성
  - `python -c "import yfinance as yf; print(yf.Ticker('KRW=X').history(period='10y').head())"`
  - Full 10y 가용 → D8 = 10y / partial → D8 = 5y
  - decisions.md 갱신 + commit (이 commit 의 첫 hunk)

**Schema migration plan (D9):**

`FXSnapshot.regime` Literal 확장: **4 → 5 값**
```python
# 기존
regime: Literal["krw_strong", "krw_weak", "usd_risk_off", "neutral"]
# 신규
regime: Literal["krw_strong", "krw_weak", "krw_structural_weak", "usd_risk_off", "neutral"]
```

**영향 파일 전수 리스팅 (§4.3 참조 — phantom edit 방지용 명시):**

| 파일 | line | 변경 |
|---|---|---|
| `tradingagents/schemas/macro.py` | 173 | Literal 5값으로 확장 |
| `tradingagents/skills/macro/fx.py` | 16-30 | `_classify_regime` 재작성 (hybrid logic) |
| `tradingagents/skills/macro/fx.py` | 신규 | `FXRegimeConfig` dataclass — Z 임계, level percentile 임계 외부화 |
| `tradingagents/agents/analysts/macro_quant_analyst.py` | (grep 후) | narrative builder 가 enum 값을 인지 |
| `prompts/macro-analysis.md` | 28, 75 | `krw_structural_weak` 추가 설명 |
| `tests/unit/skills/test_macro_tier3.py` | 22-45 | `test_fx_krw_structural_weak` 추가 |
| `tests/unit/skills/test_macro_regime.py` | 34 | structural_weak case fixture 1개 추가 |
| `tests/integration/test_eval_regime_classifier.py` | 30/68/92/115/138/178/201/224 | 8 fixture 의 `fx_regime` 값 재검토. structural_weak 로 가야 할 case 가 있는지 (예: 224의 1380/+2.5%는 shock 아니라 structural?) |
| `docs/stage1. macro_quant.md` | 227-232, 363, 433-438 | hybrid logic 설명 + 새 enum 의미 추가 |

비대칭 설계 (cold analysis §3 결함 5 답): `krw_structural_strong` 은 추가 안 함. 정당화: 한국 외환시장은 비대칭적으로 약세 방향에 외국인 자금 이탈 압력이 누적되며, 강세 방향은 단일 카테고리 (`krw_strong`) 로 충분. spec 에 explicit 기록.

**Modified (요지):**
- `tradingagents/skills/macro/fx.py`:
  ```python
  @dataclass
  class FXRegimeConfig:
      z_shock_threshold: float = 1.5
      dxy_z_shock_threshold: float = 1.0
      level_structural_pct: float = 0.90
      z_structural_min: float = 0.5
      level_window_days: int = 252 * 5  # D8 결과에 따라 5y or 10y
  ```
  - Z-score 컴포넌트: 1m 수익률의 1y 분포 대비 표준편차
  - Level 컴포넌트: 5y (또는 10y) percentile
  - Hybrid:
    - shock: `krw_z > Z_SHOCK AND dxy_z > DXY_Z_SHOCK` → `usd_risk_off`
    - structural: `level_pct > 0.90 AND krw_z > 0.5` → `krw_structural_weak`
    - 단순 약세: `krw_z > 1.5` → `krw_weak`
    - 단순 강세: `krw_z < -1.5` → `krw_strong`
    - 그 외: `neutral`

**Test:**
- `tests/unit/skills/test_macro_tier3.py`:
  - 새 `test_fx_krw_structural_weak`: KRW 5y 95pct level + krw_z=0.6 → structural_weak
  - 기존 `test_fx_usd_risk_off_regime`: Z 변환 후에도 통과해야 함 (KRW +5% 1m + DXY +2% 1m → shock)

**Holdout 갱신:** 2022-06~2024-12 동안 baseline 의 `usd_risk_off` 일수 vs proposed 의 일수 비교. 추가로 `krw_structural_weak` 일수 분포 확인 (구조적 약세기 정확히 잡는지).

---

### C4 `feat(stage1): Fed path multi-tenor display fields (#4 fix)`

**해결 이슈:** #4 Fed path

**핵심 design (cold analysis §4 의 결함 보완):**
- **Classification 로직 변경 X.** 현재 adaptive band (5y rolling std) 가 이미 합리적.
- Display 용 field 만 추가 — LLM 이 narrative 만들기 쉬워짐.
- Fixed threshold (`+15/-15`, `+25/-25`) 추가 금지 (cold analysis §4 결함 4 답).

**Modified:**
- `tradingagents/dataflows/fred.py` — `DGS1` (1y Treasury) 추가
- `tradingagents/schemas/macro.py::FedPathSnapshot`:
  - 신규: `implied_2y_rate_pct` 는 유지, 신규로 `implied_1y_rate_pct`, `implied_6m_rate_pct`
  - 신규: `path_6m_bps`, `path_12m_bps`, `path_24m_bps` (각 만기 - DFF, × 100)
  - 신규: `implied_moves_12m: int` — `round(path_12m_bps / 25)` (양수=인상 횟수)
  - **`market_view` Literal 그대로** (`hike/hold/cut`). classification 로직 변경 없음.
- `tradingagents/skills/macro/fed_path.py`:
  - `compute_fed_path` signature 에 `dgs6m`, `dgs1y` 인자 추가 (optional, default None)
  - 위 신규 field 계산
- `tradingagents/agents/analysts/macro_quant_analyst.py` — DGS1/DGS6MO 시리즈 전달

**의도적 비포함 (cold analysis §4 결함 6 답):**
- `repricing_speed`: 가능하나 hardcoded threshold (`±15bps`) 가 따라옴 → 보류.
- `curve_shape`: 같은 이유 보류.
- ZQ futures fetch: yfinance 안정성 낮음, cold analysis 가 본인 인정.

**Test:**
- `tests/unit/skills/test_macro_fed_path.py`:
  - DGS6MO=5.0, DFF=5.25, DGS1=4.75, DGS2=4.5 → path_6m=-25, path_12m=-50, path_24m=-75, implied_moves_12m=-2 (2 cuts)
  - `market_view` 가 기존 adaptive band 로 그대로 동작 확인

**Holdout 갱신:** Fed 는 classification 로직 변경 없음 → fp 변화 0 예상. baseline=proposed 동일.

---

### C5 `docs(stage1): updated indicator specs + regression test sweep`

**Modified docs:**
- `docs/stage1. macro_quant.md`:
  - § yield_curve: sequential framework 설명 추가, `recession_trigger` 의미
  - § fx: hybrid Z+level 설명, `krw_structural_weak` 의미
  - § risk_appetite: composite 설명, HY OAS 우위, divergence_flag 활용
  - § fed_path: multi-tenor display field 사용법
  - § 6.5 hardcoded 임계값 caveat: 본 PR 로 해소된 항목은 ✅ 표시, 외부화된 dataclass 표시

**Regression sweep:**
- `pytest tests/unit/ -q --timeout=30 2>&1 | tail -5` — 100% PASS 의무 (직전 baseline 364)
- `pytest tests/integration/test_eval_regime_classifier.py -v 2>&1 | tail -20` — 8 fixture 의 fx_regime 갱신 후 전부 PASS
- 결과 commit message 에 quote.

**Final holdout report:**
- `artifacts/2026-05-21/holdout/summary.md` — 4 issue 각각의 baseline vs proposed 비교 표 + 결정 (채택/폐기)

---

## 3. Per-issue Design Detail

### 3.1 #1 YC Sequential Framework

**기존 (yield_curve.py:39):**
```python
inverted_days = int((last_365["spread"] < 0).sum())
# → downstream 에서 "inverted_days >= 60 → recession_anchor=True"
```

**문제 (cold analysis §1):**
- Cam Harvey: recession 은 *역전 중* 시작 거의 X. *disinversion* 시작. 1990/2001/2008/2020 모두.
- `inverted_days >= 60` 단독은 too early — 2022~2024 내내 계속 fire 했을 것.

**제안 (sequential):**
```
phase 1: 역전 중           → defensive_lean (기존 inverted_days 신호)
phase 2: 역전 종료 + bull   → recession_trigger (신규)
phase 3: NBER recession    → backdated, 본 시스템 비대상
```

**구현:**
```python
def _compute_recession_trigger(spread_series_5y, two_y, ten_y):
    # 5y percentile-based "deeply inverted recently"
    pct_5y = (spread_series_5y < spread_series_5y.iloc[-1]).mean()
    min_5y_pct = (spread_series_5y < spread_series_5y.tail(378).min()).mean()
    was_inverted_recently = min_5y_pct <= 0.05  # 5pct 이하까지 갔던 적 (절대 -25bps 아님)

    # Recovery
    min_18m_bps = spread_series_5y.tail(378).min() * 100
    current_bps = spread_series_5y.iloc[-1] * 100
    recovery_pct = (current_bps - min_18m_bps) / abs(min_18m_bps) if min_18m_bps < 0 else 0
    is_recovering = recovery_pct > 0.6  # 최저점 대비 60%+ 회복

    # Steepener type
    two_y_chg_3m = two_y.iloc[-1] - two_y.iloc[-64]
    ten_y_chg_3m = ten_y.iloc[-1] - ten_y.iloc[-64]
    if two_y_chg_3m < -0.30 and two_y_chg_3m < ten_y_chg_3m:
        steepener = "bull"
    elif ten_y_chg_3m > +0.30 and ten_y_chg_3m > two_y_chg_3m:
        steepener = "bear"
    else:
        steepener = "none"

    trigger = was_inverted_recently and is_recovering and steepener == "bull"
    return trigger, steepener, recovery_pct
```

**임계값 정당화:**
- `5pct` percentile: hardcode 이지만 **percentile 기반** — 절대 bps 보다 훨씬 robust. config 외부화하여 sensitivity test 가능.
- `60% recovery`: hardcode. C0 holdout 에서 sensitivity 확인 후 dataclass 외부화 검토.
- `0.30` (2y 3m 변화): 30bps. 1990/2001/2008 disinversion 시 2y 가 평균 80~120bps 떨어졌으므로 30bps 는 conservative cutoff. 단, 이것도 percentile-based 변환 가능 → C2 시작 시 D7 결정.

### 3.2 #2 HY OAS Composite

**기존 (risk_appetite.py:35-44):**
```python
ratio = cu / au * 100
percentile = (last_5y < ratio).mean()
signal = "risk_on" if percentile > 0.7 else "risk_off" if percentile < 0.3 else "neutral"
```

**문제 (cold analysis §2):**
- Cu: AI 전력망/EV → 비순환 수요 dominance
- Au: 중앙은행 매집 (2022~ 1500톤/년) → 비순환 수요 dominance
- 두 fundamental 노이즈가 ratio 의 risk signal 압도

**제안 (composite):**
```
risk_score = (1 - hy_oas_pct_3y) * 0.55      # HY가 dominant (가장 신뢰)
           + cu_au_pct_5y         * 0.20      # 보조 (잡음 多, weight 낮춤)
           + vix_term_component   * 0.25      # backwardation = stress
                                                  # contango = calm
                                                  # sigmoid 변환 (no step)

signal = "risk_on"  if score > 0.65
       | "risk_off" if score < 0.35
       | "neutral"  otherwise

divergence_flag = abs(cu_au_pct - (1 - hy_oas_pct)) > 0.40
```

**Why HY OAS:**
- `BAMLH0A0HYM2` BoA 공식, FRED free daily.
- 신용 투자자 실제 거래 가격 → 노이즈 적음.
- 1990 이후 모든 recession 진입에서 spike (300bps → 700bps+).
- Institutional standard.

**Why VIX term (1m/3m):**
- Calm: 3m > 1m (contango). VIX1M < VIX3M.
- Stress: 1m > 3m (backwardation). 단기 panic.
- **Sigmoid 변환** (cold analysis §2 결함 3 답):
  ```python
  vix_component = clamp((contango - 0.90) / 0.20, 0, 1) * w_vix
  ```
  → 0.99에서 0.45, 1.01에서 0.55 — smooth.

**Weights (D6):**
- Default 0.55/0.20/0.25 (cold analysis 권고).
- `RiskAppetiteConfig` dataclass 외부화 → C0 holdout 결과로 재조정.

### 3.3 #3 FX Hybrid

**기존 (fx.py:24-30):**
```python
if krw_change > 2.0 and dxy_change > 1.0: return "usd_risk_off"
if krw_change > 2.0: return "krw_weak"
if krw_change < -2.0: return "krw_strong"
return "neutral"
```

**문제 (cold analysis §3):**
- Absolute threshold `> 2.0` 가 slow drift (2022~2024 KRW 1300→1450) 를 놓침.
- 1380원대에서 거의 매일 oversensitive trigger.

**제안 (hybrid Z + level):**
```python
# Z-score: 단기 충격
krw_z = (krw_1m_return - mean_1y) / std_1y
dxy_z = (dxy_1m_return - mean_1y) / std_1y

# Level percentile: 구조적 위치
krw_level_pct = (usd_krw_history < usd_krw_now).mean()  # 5y or 10y window

# 분류
shock = (krw_z > 1.5) AND (dxy_z > 1.0)
structural_weak = (krw_level_pct > 0.90) AND (krw_z > 0.5)

if shock: regime = "usd_risk_off"
elif structural_weak: regime = "krw_structural_weak"
elif krw_z > 1.5: regime = "krw_weak"
elif krw_z < -1.5: regime = "krw_strong"
else: regime = "neutral"
```

**Asymmetry (cold analysis §3 결함 5 답):**
- `krw_structural_strong` 추가 X.
- 정당화: KR 외환은 비대칭적 — 약세 방향은 외국인 자금 이탈 압력 누적 (slow drift 패턴), 강세 방향은 단발적 회복 (slow drift 거의 없음). 단일 카테고리로 충분.
- Spec 의 본 줄이 명시적 근거.

### 3.4 #4 Fed Path Display

**기존 (fed_path.py:43-65):**
- `path_bps = (DGS2 - DFF) × 100`
- 5y rolling std 기반 adaptive band → hike/hold/cut

**문제 (cold analysis §4):**
- 정보 손실. "3 cuts priced" 표현 불가.
- 단일 tenor (2y) 만 봄. 6m/12m/24m term structure 무시.

**제안 (display only):**
```
path_6m_bps  = (DGS6MO - DFF) × 100
path_12m_bps = (DGS1 - DFF) × 100
path_24m_bps = (DGS2 - DFF) × 100    # 기존 path_bps와 동일
implied_moves_12m = round(path_12m_bps / 25)

market_view: 기존 adaptive band 로직 그대로 (변경 없음).
```

**의도적 비포함 (cold analysis §4 결함 4, 5 답):**
- repricing_speed (fixed `±15bps`): hardcoded threshold 부담 > 효용.
- curve_shape: 같은 이유.
- ZQ futures: yfinance 안정성 낮음. cold analysis 가 본인 인정.

LLM narrative 가 `implied_moves_12m=-3, path_6m=-50, path_24m=-75` 을 보고 "front_loaded" 같은 표현을 _스스로_ 생성하면 됨 (rule 박힐 필요 없음).

---

## 4. File Structure

### 4.1 Created
- `scripts/measure_stage1_holdout.py` (C0)
- `tests/scripts/test_measure_stage1_holdout.py` (C0)
- `artifacts/2026-05-21/decisions.md` (이미 생성, spec commit 에 포함)
- `artifacts/2026-05-21/holdout/README.md` (C0)
- `artifacts/2026-05-21/holdout/baseline_fp.json` (C0 → C4 누적)
- `artifacts/2026-05-21/holdout/proposed_fp.json` (C0 → C4 누적)
- `artifacts/2026-05-21/holdout/summary.md` (C5)
- `tests/unit/skills/test_macro_risk_appetite.py` (C1) — 또는 기존 test 에 추가

### 4.2 Modified
- `tradingagents/dataflows/fred.py` (C1: BAMLH0A0HYM2; C4: DGS1)
- `tradingagents/schemas/macro.py`:
  - `YieldCurveSnapshot` (+ 4 field, C2)
  - `RiskAppetiteSnapshot` (+ 4 field, C1)
  - `FXSnapshot.regime` Literal 확장 + level/Z field 추가 (C3)
  - `FedPathSnapshot` (+ 4 field, C4)
- `tradingagents/skills/macro/yield_curve.py` (C2)
- `tradingagents/skills/macro/risk_appetite.py` (C1)
- `tradingagents/skills/macro/fx.py` (C3)
- `tradingagents/skills/macro/fed_path.py` (C4)
- `tradingagents/agents/analysts/macro_quant_analyst.py` (C1, C4 — wire HY/VIX/DGS1)
- `prompts/macro-analysis.md` (C3 — krw_structural_weak 설명, C5 — 전반 update)
- `tests/unit/skills/test_macro_tier3.py` (C3)
- `tests/unit/skills/test_macro_regime.py` (C3)
- `tests/unit/skills/test_macro_yield_curve.py` (C2)
- `tests/unit/skills/test_macro_fed_path.py` (C4)
- `tests/integration/test_eval_regime_classifier.py` (C3 — 8 fixture fx_regime 재검토)
- `tests/unit/test_schemas_macro.py` (C1, C2, C3, C4 — 새 필드 default)
- `docs/stage1. macro_quant.md` (C5)

### 4.3 Schema Migration — `FXSnapshot.regime` (C3) 영향 전수

| 파일 | line | 변경 종류 |
|---|---|---|
| `tradingagents/schemas/macro.py` | 173 | Literal 5값 |
| `tradingagents/skills/macro/fx.py` | 16-30 | logic rewrite + dataclass 추가 |
| `tradingagents/agents/analysts/macro_quant_analyst.py` | (grep 필요, C3 시작 시) | narrative builder enum 인지 |
| `tradingagents/schemas/reports.py` | 9 | re-export 만 (변경 불요) |
| `tests/unit/skills/test_macro_tier3.py` | 22-45 | 새 test 추가 |
| `tests/unit/skills/test_macro_regime.py` | 34 | 새 fixture |
| `tests/integration/test_eval_regime_classifier.py` | 30/68/92/115/138/178/201/224 | 8 fixture 의 fx_regime 재검토 |
| `prompts/macro-analysis.md` | 28, 75 | 설명 추가 |
| `docs/stage1. macro_quant.md` | 227-232, 363, 433-438 | hybrid 설명 + 새 enum |

→ 총 9 파일. Phantom edit 방지 위해 C3 시작 시 이 표를 Read 하고 한 줄씩 체크.

---

## 5. Non-goals (본 PR 에서 의식적 제외)

1. **CME FedWatch 직접 통합** — cold analysis §4 가 본인 인정한 유지보수 부담 vs 효용 trade-off. 후속 issue 로.
2. **Cu/Au 완전 폐기** — 0.20 weight 로 유지. 부분적으로 정보 있음 (divergence flag 의 한 축).
3. **NFCI / VIX9D / SKEW 등 추가 risk indicator 통합** — 본 PR 은 4 issue 한정. 후속 PR.
4. **Stage 1 → Stage 2 데이터 전달 schema 변경** — `regime` 의 새 enum 값이 Stage 2 에서 어떻게 매핑될지 (24-cell quadrant 영향) 는 본 PR 범위 외. Stage 2 PR 에서 후속 처리.
5. **`krw_structural_strong` 대칭 enum** — §3.3 정당화로 명시 제외.
6. **`repricing_speed`, `curve_shape` Fed path fields** — §3.4 정당화로 명시 제외.

---

## 6. Risk Register

| Risk | 발생 시 신호 | 대응 |
|---|---|---|
| C0 holdout 이 baseline 의 fire 일수를 측정 못함 (데이터 gap) | `baseline_fp.json` empty / partial | C1~C3 의 채택 기준을 정성적 검토로 대체. 의사결정 문서화. |
| VXVCLS 도 yfinance ^VIX3M 도 모두 fail (D4+D5) | C1 첫 hunk 실패 | VIX term component 제거 (composite 가 HY 0.55 + Cu/Au 0.20 = 0.75 만). spec 갱신 commit 따로. |
| C2 의 percentile-based 변환이 historical recession (2008-09, 2020-03) 에서 fire 안 함 (FN) | holdout FN 검증 fail | C2 폐기, issue close. cold analysis 의 design 자체가 retrospective fit 가능성. |
| C3 의 `krw_structural_weak` 추가가 24-cell 매핑을 깨트림 (Stage 2 와 conflict) | integration test fail | C3 partial revert (enum 값은 추가하되 mapping 은 기존 `krw_weak` 로). Stage 2 후속 PR 에서 본격 mapping. |
| `tests/integration/test_eval_regime_classifier.py` 의 8 fixture 중 expected fx_regime 이 hybrid 로 못 잡는 case | C3 integration test fail | fixture 별로 검토 — expected 가 옳은지 / hybrid 가 옳은지 결정. 결정 후 decisions.md 갱신. |
| Long-session 환각 누적 (8시간+) | 매 commit 후 `pytest tail -5` 출력 불일치 | execution-protocol 8 원칙 (filesystem-as-state) 의무 적용. 의심 시 decisions.md Read. |

---

## 7. Execution Protocol

`docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md` 8 원칙을 그대로 채택. 본 PR 의 차이점만 명시:

- 본 PR 은 5+ commit + conditional decision (D4/D6/D7/D8) + 백그라운드 holdout 측정 → **execution protocol 적용 의무 case**.
- Background measurement: holdout backtest 는 ~30min × 2 (baseline/proposed). job_status.json 갱신 필수.
- Decision 기록: `artifacts/2026-05-21/decisions.md` 사용 (stage2 의 `artifacts/2026-05-20/decisions.md` 와 별도).

---

## 8. Acceptance Criteria

본 PR 이 merge 되기 위한 조건:

1. **모든 unit test PASS** (`pytest tests/unit/ -q --timeout=30` 후 마지막 줄 quote, FAIL 0).
2. **Integration test PASS** (`test_eval_regime_classifier.py` 의 8 fixture 전부).
3. **Holdout false positive 감소** — 각 issue 의 D11 기준 만족, 또는 그 issue commit 폐기.
4. **Decision log 완전** — D0~D11 모두 채워짐, 결정 시각 + commit hash 기록.
5. **Schema migration 영향 9 파일 모두 update 확인** — Read tool 로 매 파일 검증.
6. **Cold analysis 의 모든 점이 spec/code 에 답변되어 있음** — non-goal 로 거부했든, 구현했든 명시.
7. **PR description 에 holdout summary table 포함** — baseline vs proposed FP, decision (채택/폐기).
