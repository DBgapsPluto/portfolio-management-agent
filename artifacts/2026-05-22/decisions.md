# Stage 2 Factor Model PR1 Decisions

> Brainstorming 의 결정 + 후속 조건부 결정 기록.

| # | 항목 | 결정 | 근거 | 시각 | commit |
|---|---|---|---|---|---|
| D1 | Scope | Stage 2 내부만, Stage 1 gap 별도 PR | brainstorming Q1 | 2026-05-22 | spec |
| D2 | Calibration | Hybrid (theory prior + walk-forward Sharpe optim with shrinkage) | brainstorming Q2 | 2026-05-22 | spec |
| D3 | LLM in Stage 2 | None (deterministic only) — LLM critic 은 future | brainstorming clarification | 2026-05-22 | spec |
| D4 | Migration | Hard cutover (24-cell 완전 제거) | brainstorming Q4 | 2026-05-22 | spec |
| D5 | Acceptance | OOS Sharpe > 현 framework + 0.05 AND ≥ 60/40 | brainstorming Q5 | 2026-05-22 | spec |
| D6 | macro_news 활용 | Option Z — NewsReport structured field deterministic | brainstorming clarification | 2026-05-22 | spec (fc345ca) |
| D7 | Shrinkage λ | **1.00** (synthetic 기준) — real fetch 후 재결정 필요 | C6 walk-forward grid: λ=1.00 median OOS Sharpe 2.399 최대 (0.10→2.230, 0.30→2.235, 0.50→2.367, 0.70→2.347, 1.00→2.399). 단 synthetic data 이므로 production 적용 보류 | 2026-05-23 | C7 (artifacts/2026-05-22/factor_calibration/validation_report.md) |
| D8 | Sample window | **full** (n=135 quarters, synthetic) — real fetch 후 재결정 가능 | C6 calibration 은 synthetic full window 만 사용 (1991-2024 vs 2010-2024 등 sub-window 비교는 real data fetch 후 수행). Stage 1 backlog Issue #18 (real historical fetch) 완료 시 PR2 에서 재calibration | 2026-05-23 | C7 (artifacts/2026-05-22/factor_calibration/validation_report.md) |
| D9 | yfinance KRW/USD vs Stage 1 fix | external_fetcher (PR1) + Stage 1 PR (Issue #12 backlog) | Gap E workaround | 2026-05-22 | spec |
| D10 | Mandate projection algorithm | QP-based (L2-optimal) + per-contribution cap (0.10) + safety diagnostics | user feedback 후 추가 결정 | 2026-05-22 | spec/plan (aa5e3d4) |
