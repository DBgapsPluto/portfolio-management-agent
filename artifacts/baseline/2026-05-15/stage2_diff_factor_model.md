# Stage 2 Diff: Factor Model vs 24-cell Framework (2026-05-15)

> PR `feat/stage2-factor-model` (factor model, C7 시점) vs PR `feat/stage2-bottleneck-fixes` (Mega-PR head `47b5590`, 24-cell 최종 산출물).

본 diff 는 *프레임워크 자체* 의 교체 효과를 측정한다. C1–C5 가 24-cell scenario probability framework → 9-factor z-vector + additive regression + QP mandate projection 으로 redesign.

- **Pre** (24-cell, `47b5590`): 12 scenario marginal (4 cycle × 3 tail × 2 kr) + LLM 합성 24-cell probability table → bucket weight 가중평균.
- **Post** (factor model, C7): 9 deterministic factor (F1 growth ~ F9 liquidity) → additive regression (W * z) → baseline bucket 에 가산 → QP projection 으로 mandate 강제.

산식·코드 변경이므로 LLM 재실행 noise 가 결과 차이의 원인이 아니다 (단, F2/F7/F9 estimator 들이 가져오는 정량 신호가 LLM scenario 보다 *훨씬 다른 시그널* 을 표현하는 점이 핵심).

---

## 1. ResearchDecision diff

| 항목 | Pre (24-cell) | Post (factor) | 비고 |
|---|---|---|---|
| schema | `dominant_cell`, `cycle_marginals`, `scenario_probabilities`, `conviction_beta`, ... | `factor_scores` (9), `factor_contributions`, `safety_diagnostics`, `dominant_scenario`, `baseline_bucket` | C5 에서 24-cell field 완전 제거 (`extra="ignore"` 로 archive 호환) |
| dominant_scenario | `overheating` (B_N_F 기반) | `goldilocks` | F2 inflation 음수 (낮음) + F1 growth 약간 음수 + F7 변동성 spike — 종합 분류기는 "goldilocks" 인식 |
| conviction | `high` | `medium` | factor model 의 z 합산이 분산된 시그널 (F7 만 극단, 나머지 0/약함) → high 수렴 어려움 |
| dominant_cell | `B (cycle) / N (tail) / F (kr)` 62% | (없음) | factor model 은 cell 개념 폐기 |
| baseline_bucket | (해당 없음) | `{kr_equity:0.12, global_equity:0.20, fx_commodity:0.15, bond:0.33, cash_mmf:0.20}` | C3 에 정의된 시작점 (factor=0 시 bucket) |
| factor_scores (top \|z\|) | (해당 없음) | F7_equity_vol_regime **+2.32**, F2_inflation **-0.50**, F5_credit_cycle **-0.48**, F9_liquidity_regime **-0.36** | F7 만 극단치 — 변동성 체제 dominant |
| safety_diagnostics.projection_intervened | (해당 없음) | **True** (L2=0.0207) | additive regression 결과 sum≈0.954 (1 미만) → QP 가 mandate-conformant 로 보정 |
| safety_diagnostics.extreme_factor_active | (해당 없음) | False | \|z\| ≤ 2.5 threshold 미달 (F7 2.32 — 거의 경계) |
| safety_diagnostics.mandate_violated_pre_projection | (해당 없음) | False | risk_asset_share 29.5% — 0.05 ≤ x ≤ 0.95 통과 |

핵심 관찰:
- 24-cell 은 *LLM 이 정성적 cell 확률 24개 를 일관되게 추정* 해야 했으나 factor 는 *정량 estimator 9 개 합산* 이므로 결정 경로가 다르다.
- "overheating" → "goldilocks" 전환은 *Stage 1 macro 가 같은 데이터를 보고도* 24-cell LLM 은 B (growth+inflation) 우세로 해석한 반면, factor estimator 는 F2 (inflation z) 가 음수 (`-0.50`) 로 측정되어 *디스인플레이션 친화* 신호를 우세로 본 결과.
- 가장 큰 신호는 F7 (equity_vol_regime) `+2.32` — VIX/MOVE 또는 vol-of-vol 상승. 이 단일 factor 가 bucket weight 의 *방향성 대부분* 을 만든다 (bond ↑, cash ↑, equity ↓).

---

## 2. BucketTarget diff

| Bucket | Pre (24-cell) | Post (factor) | Δ (pp) | Δ (%) |
|---|---:|---:|---:|---:|
| kr_equity     | 0.0883 |  0.0790 |  -0.93 | -10.5% |
| global_equity | 0.2056 |  0.1674 |  -3.82 | -18.6% |
| fx_commodity  | 0.2790 |  0.0761 | **-20.29** | **-72.7%** |
| bond          | 0.2281 |  0.4573 | **+22.93** | **+100.5%** |
| cash_mmf      | 0.1991 |  0.2202 |  +2.11 | +10.6% |
| bond_tips_share | 0.7373 | 0.2317 | **-50.56** | -68.6% |

**위험자산 합** (kr_equity + global_equity + fx_commodity):
- Pre: 0.5728
- Post: 0.3224
- Δ: **-25.04pp** (위험자산 대폭 축소)

**해석**:
1. **bond 절반 증가, fx_commodity 1/4 축소**: F7_equity_vol_regime `+2.32` 가 bond/cash 방어로 큰 흐름 형성. 24-cell 에서 B (overheating) 가 commodity-heavy 였던 것과 정반대.
2. **bond_tips_share 73% → 23%**: 24-cell 의 "overheating" 은 TIPS 비중을 매우 높게 (인플레이션 대비) 잡았는데, factor 의 F2_inflation 이 음수 (디스인플레이션) 로 측정되어 *nominal bond 가 우세* 가 되었음.
3. **위험자산 25pp 감소**: 단일 factor (F7) 가 변동성 spike 로 매우 보수적 신호를 발산. 이는 24-cell 의 "B + N tail = risk-on" 해석과 반대 방향.
4. **QP projection 개입** (`projection_intervened=True`): regression sum 이 0.954 였으므로 QP 가 (1) sum=1 enforce, (2) mandate band 통과시키도록 0.021 L2 거리 보정. 보정량은 작음 — additive regression 결과가 거의 mandate 친화.

---

## 3. Method choice diff (Stage 3)

| 항목 | Pre (24-cell) | Post (factor) |
|---|---|---|
| method | `hrp` | `hrp` |
| params | `{}` | `{}` |
| reasoning | `scenario=overheating, conviction=high: overheating (growth+inflation) → equity tilt + 분산, HRP` | `scenario=goldilocks, conviction=medium: goldilocks → 분산 친화, HRP` |

method 자체는 **불변** (둘 다 HRP). 단 *근거 시나리오* 가 overheating → goldilocks 로 변경. method_picker 의 분기가 이 두 scenario 모두 HRP 로 매핑하므로 결과 동일.

만약 dominant_scenario 가 `broad_recession` / `global_credit` / `kr_stress` 로 분류되었다면 method 가 변경되었을 것 (예: risk_parity).

---

## 4. Weight vector diff (Stage 3 ETF level)

Pre top5 (24-cell):
| ticker | weight |
|---|---:|
| A411060 | 0.1650 |
| A0061Z0 | 0.1371 |
| A488770 | 0.1238 |
| A144600 | 0.1140 |
| A133690 | 0.0826 |

Post top5 (factor):
| ticker | weight |
|---|---:|
| A0061Z0 | 0.1650 |
| A488770 | 0.1409 |
| A468370 | 0.1278 |
| A273130 | 0.1025 |
| A360750 | 0.0796 |

- n_assets: pre **15** → post **16** (+1)
- 변경: bucket target 의 bond ↑ / fx ↓ 가 Stage 3 의 후보 ETF 우선순위를 *방어형 채권 / TIPS* 쪽으로 끌어당김.
- A411060 (pre 16.5%) → post 3.9% (drop), A468370 (KODEX iShares 미국인플레이션국채선물ETF, pre missing) → post 12.8% (신규).
- Stage 4 overlay 는 동일하게 `concentration=critical, strength=0.70, multiplier=1.00` 적용 — top1/top3 비중이 여전히 높음.

---

## 5. Validator diff (Stage 5 mandate)

| 항목 | Pre | Post |
|---|---|---|
| validation_report.passed | **True** | **True** |
| violations count | 0 | 0 |
| suggestions count | 0 | 0 |

Mandate **양쪽 모두 통과**. Post 는 QP projection 이 bucket 단계에서 이미 mandate band (cash_mmf ≤ 0.30, risk_asset 0.05–0.95 등) 를 enforce 하므로 validator 가 항상 clean.

---

## 6. 분석 — 5/28 대회 narrative 관점

### Factor model 이 만든 portfolio 의 성격
- 24-cell: "성장+인플레 (overheating, high conviction) → 위험자산 57%, TIPS 가 채권의 74%"  
  → equity·commodity·TIPS 중심의 *진취적 분산*.
- Factor: "디스인플레이션 + 변동성 spike (goldilocks 라 분류, medium conviction) → 위험자산 32%, 채권의 23% 만 TIPS"  
  → bond·cash 중심의 *방어적 분산*.

같은 datapoint (2026-05-15) 에서 정반대 portfolio 가 산출됨. 두 모델의 의사결정 기준이 다른 데이터 단면을 보기 때문:

| 측면 | 24-cell | factor |
|---|---|---|
| 인플레이션 해석 | CPI 3.9%, 3m 7.3% accelerating → "B (overheating) 84%" | F2 z=-0.50 (디스인플레 친화) — Mega-PR 변동 fixture 가 *최근 momentum 감속* 을 포착 |
| 변동성 해석 | VIX 18.4 calm, MOVE 100, term ratio contango → "N tail 84%" (안정) | F7 z=+2.32 (vol regime spike) — vol-of-vol 또는 단기 surface 가 *경계 수준* 으로 측정 |
| KR 신용 | KR corp spread +63bp elevated, KOSDAQ-KOSPI -25% → "F kr 84%, S 12% residual" | F5 z=-0.48 (credit_cycle 양호) — 미국 HY OAS 280bp 기준 |

→ Factor model 은 *변동성 체제* 한 축 (F7) 에 dominated. 다른 factor 들은 거의 0 ~ -0.5 범위로 *작은 신호* 만 기여.

### Mandate 통과
- **Pre/Post 모두 `passed=True`**. QP projection 이 작동 (L2 0.0207 보정) 하여 factor 결과를 mandate-feasible 영역으로 끌어옴.
- safety_diagnostics 가 archive 에 저장되어 *왜 보정되었는가* 추적 가능 (C3 의 design goal 충족).

### 대회 narrative 측면
- philosophy.md 가 *F7 변동성 체제* 와 *F2 디스인플레이션* 을 핵심 근거로 인용하므로, "왜 채권 45.7%, MMF 22%?" 를 단일 변수로 설명 가능 (이전 narrative 는 24-cell probability table 을 *모든 면에서* 인용해야 했음 — 가독성 ↓).
- 단, "goldilocks 인데 위험자산 32% 만?" 은 *직관적 미스매치* — F7 의 극단치가 시나리오 분류와 bucket weight 의 거리를 만든 결과. PR2 (real-data calibration) 에서 W matrix 보정 시 이 차이가 어떻게 변할지 검증 필요.

---

## 부록 — Top factor contributors per bucket (post)

각 bucket 의 weight 변화에 가장 크게 기여한 factor:

| bucket | top contributor | 2nd | 3rd |
|---|---|---|---|
| kr_equity     | F7_equity_vol_regime −0.0927 | F5_credit_cycle +0.0242 | F9_liquidity_regime +0.0108 |
| global_equity | F7_equity_vol_regime −0.1000 | F5_credit_cycle +0.0290 | F9_liquidity_regime +0.0179 |
| fx_commodity  | F7_equity_vol_regime −0.0463 | F2_inflation −0.0350 | F5_credit_cycle −0.0048 |
| bond          | F7_equity_vol_regime **+0.0927** | F2_inflation +0.0250 | F9_liquidity_regime −0.0144 |
| cash_mmf      | F7_equity_vol_regime **+0.1000** | F5_credit_cycle −0.0580 | F9_liquidity_regime −0.0179 |

F7 (equity_vol_regime) 이 5 개 bucket 모두에서 1위 contributor — 본 일자 portfolio 의 핵심 driver.
