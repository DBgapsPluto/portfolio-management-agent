# Stage 2 Mega-PR Execution Decisions (2026-05-20)

> 조건부 결정의 외부 state. 모든 C1-C5 코드 변경은 본 표에 결정이 등록된 후에만
> 진행. 코딩 시점에 본 파일 Read 해서 인용. spec line 번호로 chain 추적.

| # | 항목 | 결정 | 근거 | 시각 | commit |
|---|---|---|---|---|---|
| D1 | β 옵션 (Issue #5) | **A (β=1 고정)** | variance n=20: bond σ 0.3pp ≪ 3pp, flip 0%. sharpening 자체 불필요. 현 β=2.38 은 24-cell cross-effect 짓누름. (variance/summary.md) | 2026-05-21T(C2) | _C2_ |
| D2 | EMA λ (Issue #11) | **1.0 (no smoothing)** | variance σ ≈ 0 — EMA 가 줄일 noise 없음. λ<1.0 추가는 magic number. infrastructure 만 구축 (λ=1.0 default). | 2026-05-21T(C2) | _C2_ |
| D3 | Hysteresis on/off | **off** | flip rate 0% — hysteresis trigger 없음. | 2026-05-21T(C2) | _C2_ |
| D4 | Method picker overheating | HRP | equity tilt + 분산. goldilocks 와 동등 처방. (spec §2 C1) | 2026-05-20T(C0) | edf4aad (C1) |
| D5 | C3 input pruning | **keep prompt as-is** | L1(baseline, no_macro)=1.0 → macro 제거 시 결과 무의미 (goldilocks 폴백). anchoring ratio 0.72 < 2.0 → 단순 reformat 아님. stage 2 LLM 호출 제거는 위험. (ablation/summary.md) | 2026-05-21T(C2) | _C2_ |
| D6 | C5 philosophy.md narrative | _pending_ | stage2_diff.md 본 후 결정 | — | — |
| D7 | C4 baseline 회귀 fallback | **defer full regression (hand-coded 유지 + scope adjustment)** | Data gap: BAA10Y (IG proxy) 만 1990+, HY OAS 자체 historical 없음. KR 분기 ~2003+. 1970-2024 quarterly 5×4 baseline + KR β OLS 는 새 data infrastructure 필요 (FRED HY OAS 대체 source, ECOS 분기 reconciliation). 본 PR scope 초과. `_BASELINE` + KR β/α 는 macro consensus + 1970-2024 근사로 reasonable proxy 유지. Issue #6 scope 재정의: (1) `_BASELINE` 의 BAA10Y 부분만 1990-2024 부분 회귀 (가능), (2) 나머지 metric (VIX, funding, equity_bond_corr) 은 1990+ FRED 시리즈로 가능, (3) KR 부분은 ECOS data 별도 확보 후. → 별도 PR. | 2026-05-21T(C4) | _C4_ |

## 사용 규칙

1. C2 결과 회수 직후 D1-D3, D5 결정 → 본 표 갱신 → commit (`chore(stage2): decisions update from variance + ablation`)
2. 코드 작성 시 본 파일 Read → 결정 row 인용 → 그 결정에 부합하는 코드만 작성
3. 결정 변경 필요 시 *새 row 추가* (덮어쓰지 말 것 — chain 추적용)
