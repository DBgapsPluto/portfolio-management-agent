# 2026-05-15 Stage 2 산출물 pre/post (C1-C5 적용) diff

본 PR (C1-C5) 의 Stage 2 changes 가 2026-05-15 산출물에 어떻게 반영되었는지 요약.

- **Pre**: 2026-05-20 15:22 시점 산출물 (β=2.38 sharpening + "stagflation" mis-label + 단일 prompt)
- **Post**: 2026-05-21 16:35 재생성 (β=1, "overheating" label, system/user prompt split, EMA infra default no-op)

LLM stochastic 재실행이므로 raw scenario probability 자체도 약간 다름 (B raw 76% → 84%).
따라서 본 diff 는 "C 의 알고리즘 변경" + "재실행 LLM noise" 가 섞인 결과.

---

## 1. ResearchDecision diff

| 항목 | Pre | Post | Δ | 원인 |
|---|---|---|---|---|
| dominant_cycle | B | B | — | 일관 (variance n=20 100% B) |
| dominant_cycle_probability (raw) | 76.0% | 84.0% | +8.0pp | LLM 재실행 noise (variance σ 6.5pp 내) |
| conviction_beta | **2.38** | **1.00** | -1.38 | **C3 D1 (option A) — sharpening 제거** |
| effective B marginal | **97.9%** | **84.0%** | **-13.9pp** | β=1 → effective == raw (24-cell cross-effect 보존) |
| dominant_cell | B_N_F | B_N_F | — | 일관 |
| dominant_cell_probability | 58.0% | 62.0% | +4.0pp | LLM 재실행 |
| dominant_scenario | "stagflation" | **"overheating"** | label 변경 | **C1 Issue #7 — B (growth+inflation) ≠ stagflation** |

---

## 2. BucketTarget diff

| 자산 | Pre | Post | Δ (pp) |
|---|---|---|---|
| kr_equity | 9.67% | 8.83% | **-0.85** |
| global_equity | 19.68% | 20.56% | +0.88 |
| fx_commodity | 29.76% | 27.90% | **-1.86** |
| bond | 20.88% | 22.81% | **+1.93** |
| cash_mmf | 20.01% | 19.91% | -0.09 |
| bond_tips_share | 78.98% | 73.73% | **-5.25** |

해석:
- bond +1.93pp, fx -1.86pp — sharpening 제거로 비 dominant cell (특히 C/D) 의 weight 가 portfolio 에 작게나마 반영됨. C/D 둘 다 채권 친화이므로 bond ↑.
- bond_tips_share -5.25pp — 비 B 셀에서 TIPS 비중 적은 cell (예: C_N_F 의 nominal 채권) 가 더 살아남음.
- 위험자산 합: 59.1% → 57.3% (-1.8pp) — sharpening 제거로 약간 더 보수적.

---

## 3. Method choice diff

| 단계 | Pre | Post | 원인 |
|---|---|---|---|
| Stage 3 method_picker | **risk_parity** | **HRP** | **C1 Issue #7 fix** — "overheating" → HRP (이전엔 "stagflation" 으로 잘못 매핑되어 RISK_PARITY) |
| Stage 4 overlay (concentration lens) | (no overlay) | min_variance 강제 | concentration lens 가 critical (top1=20%, max_cluster=27.9%) 판정 → 70% strength overlay 적용. Pre 도 동일 universe 라면 같은 결과 가능성 — 본 diff 는 Stage 4 overlay 가 active 인 점이 새로움 (Pre 는 risk_parity 자체가 보수적이라 overlay strength 0%). |
| Top-level "method" field | risk_parity | min_variance | overlay 결과 |

**중요**: method_picker (Stage 3 의 사실상 결정) 는 Issue #7 fix 가 직접 영향 — risk_parity → HRP. Stage 4 의 min_variance overlay 는 concentration lens 의 별개 처방 (cluster cap 위반 우려).

---

## 4. Portfolio composition diff

- n_assets: 18 → 15 (3 net 감소)
- 공통: 11, 신규 add: 4, drop: 7

**Top 15 weight changes (sorted by |Δ|):**

| ticker | Pre | Post | Δ (pp) |
|---|---|---|---|
| A468370 | 11.34% | 0.00% | -11.34 |
| A458730 | 6.40% | 0.00% | -6.40 |
| A133690 | 2.76% | 8.26% | +5.49 |
| A273130 | 0.00% | 5.24% | +5.24 |
| A360750 | 0.65% | 5.78% | +5.13 |
| A0061Z0 | 8.84% | 13.71% | +4.87 |
| A379810 | 4.48% | 0.00% | -4.48 |
| A487240 | 4.15% | 0.00% | -4.15 |
| A278530 | 0.00% | 3.70% | +3.70 |
| A455890 | 8.57% | 4.97% | -3.59 |
| A102110 | 0.00% | 3.45% | +3.45 |
| A430500 | 7.15% | 3.86% | -3.29 |
| A456600 | 2.64% | 4.88% | +2.24 |
| A395270 | 0.00% | 1.68% | +1.68 |
| A144600 | 9.78% | 11.40% | +1.62 |

대략 turnover ~30% (one-sided). method_picker risk_parity → HRP → min_variance 의 cascade 가 큰 영향.

---

## 5. Expected metrics 변경

| 지표 | Pre | Post |
|---|---|---|
| expected_volatility | 25.59 | **null** |
| expected_sharpe | **0.020** | **null** |

**ISSUE** — Post 산출물에 `expected_volatility` / `expected_sharpe` 가 None 으로 들어옴. 본 PR (C1-C5) 의 알고리즘 변경과 무관한 별개 버그 가능성 (Stage 4 overlay 적용 후 portfolio_manager 가 재계산 skip). 후속 issue 등록 권장.

---

## 6. D6 결정 — philosophy.md narrative

**결정: regenerated philosophy.md 그대로 채택** (별도 narrative 가공 없음).

근거:
1. **Diff magnitude**: bucket_target 변화 1-2pp 수준, top-level direction 변경 없음 (B-cycle, equity tilt 유지). "framework 개선" narrative 까지는 무겁고, "한계 인식 + 로드맵" narrative 까지는 가벼움 → 중간 (regenerated narrative 그대로).
2. **Narrative 자체가 새 framework 반영**:
   - Section 1: macro_quant growth_inflation 0.84
   - Section 3: B 84% dominant, β=1.00 인용, B_N_F 62%
   - Section 5: broad_recession / global_credit / kr_stress 시나리오
   - Section 6: method=min_variance + "overheating, high conviction → HRP" (Stage 3 picker 의 사유)
3. **대회 narrative 측면**: 70점 철학 점수 잘 채워짐 — 6 섹션 모두 충실 + Stage 1-4 수치 인용 + 자체 risk 통제 원칙 명확.

C1-C4 의 framework 변경은 dev 관심사이지 대회 narrative 의 주제가 아님. 별도 "Stage 2 framework 개선" 섹션 추가 안 함.

---

## 7. Mandate 검증

새 portfolio 의 mandate 검증:
- validation_report.passed: **True**
- violations: **[]**
- 위험자산 합: 57.3% ≤ 70% ✓
- top1: 20.0% ≤ 20% ✓ (정확히 cap)
- max_cluster: 27.9% — soft warning 수준 (Stage 4 lens 가 이미 critical 로 잡고 overlay 적용)

---

## 8. C1-C5 산출물 영향 요약

| Commit | 영향 | 산출물 변화 |
|---|---|---|
| C1 (#7 mis-label) | Stage 3 method_picker | risk_parity → HRP (Stage 3 picker 단계) |
| C2 (variance + ablation) | 측정만, 산출물 영향 없음 | — |
| C3 (β=1 + EMA/hyst infra) | Stage 2 sharpening 제거 | effective B 98% → 84%, bucket ±2pp |
| C4 (prompt split + D7 defer) | LLM I/O 구조 | scenario_probabilities raw 분포 변화 (LLM 재실행 noise 포함) |
| C5 (재생성) | 모든 stage 재실행 | portfolio.json, philosophy.md, trade_plan.csv 갱신 |
