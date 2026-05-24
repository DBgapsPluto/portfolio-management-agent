# Stage 1 Enhance for Factor Model PR — Decisions

> Brainstorming 의 결정 + grill-me 4 회 의 후속 결정 기록.

| # | 항목 | 결정 | 근거 | 시각 | commit |
|---|---|---|---|---|---|
| D1 | Scope | PR0 hotfix + PR1 Stage 1 enhance (single PR) | brainstorm Q1+Q2 | 2026-05-23 | spec |
| D2 | Coverage | Definition 1 — current design 100% (PR0 + 5 신규) | brainstorm Q3 | 2026-05-23 | spec |
| D3 | Schema | A2 hybrid — 3 신규 class + 2 field 확장 | brainstorm Q4 | 2026-05-23 | spec |
| D4 | Commit grouping | X1 per-indicator (5 commit) | brainstorm Q3 detail | 2026-05-23 | spec |
| D5 | Sub-skill | A pattern — 신규 skill module per indicator | brainstorm Q4 detail | 2026-05-23 | spec |
| D6 | Quality gates | per-commit regression + selective grill-me 4 회 | brainstorm 추가 | 2026-05-23 | spec |
| D7 | Sub-skill API shape (grill-me #1) | **X Hybrid** — 기존 snapshot 확장 indicator (CFNAI, slope_5_30y, sector_dispersion) = scalar/tuple return + analyst .model_copy(update=...). 신규 class (KRValuationSnapshot, RealVolSnapshot) = full Snapshot return + MacroReport/RiskReport field 직접 채움. | grill-me #1 user 결정 | 2026-05-23 | C2 후 |
| D8 | Error handling pattern (grill-me #1) | **B Graceful in skill** — fetch 실패 시 skill 이 None 반환 + logger.warning. Analyst 는 None check 후 *기존 field default 유지* (model_copy skip). factor_estimator 의 `_safe_get` None handling 과 일관. | grill-me #1 | 2026-05-23 | C2 후 |
| D9 | Fetch retry policy (grill-me #1) | **A No retry, no cache** — skill 이 매번 fresh fetch. lru_cache + retry 불필요 (production weekly cadence, simplest path). external_fetchers.py 는 *5min lru_cache* 유지 (temporary path 차원이라 별도). | grill-me #1 | 2026-05-23 | C2 후 |
| D9b | F6 foreign_flow_z normalization (C1 implementer 발견) | **Defer to C8** — net_20d_krw 가 raw KRW (수조) 인데 factor_baselines (mean=0, sd=1) mismatch. C8 grill-me #3 에서 baseline 재교정 또는 component drop 결정. 현재는 known issue. | grill-me #1 추가 결정 | 2026-05-23 | C2 후 |
| D10 | C3 결과 pattern adjust (grill-me #2) | **C3 pattern 그대로 적용 C4-C7**: (1) CFNAI 중복 fetch 유지 — 각 block 독립 graceful failure 가 architectural 가치 (silent broken 차단). (2) D9 의 "no cache" = *skill-internal cache 만 금지*, fetcher TieredCache OK (다른 17 series 와 일관). (3) logger cleanup 은 별도 PR (본 PR scope 외). | grill-me #2 user 결정 | 2026-05-23 | C3 후 |
| D11 | C8 weight magnitude (grill-me #3) | **Plan default 그대로** — F1: cfnai 0.10 + cfnai_3m 0.08; F4: slope_5_30y 0.20; F7: realized_vol_60d 0.13; F8: kospi_pbr 0.25; F9: vrp 0.30 + sector_dispersion 0.15. 각 factor sum=1.0 재정규화. Cold prior — PR2 backtest 에서 calibration. | grill-me #3 | 2026-05-24 | C7 후 |
| D11a | F6 foreign_flow_z normalization | **factor_baselines.py 재교정** — (mean=0, sd=1e12) 로 raw KRW 접교. net_20d_krw 의 일반 magnitude 가 ~수조 KRW. C8 에서 baseline update. | grill-me #3 | 2026-05-24 | C7 후 |
| D11b | F7 skew_change placeholder | **C7.5 mini-task — SkewSnapshot.change_1m_z field 추가**. Skill: skew_metrics.py 신설. Analyst: skew_value historical series 의 1m change z 계산 + populate. C8 에서 활성화. | grill-me #3 | 2026-05-24 | C7 후 |
| D12 | 2026-05-15 diff interpretation (grill-me #4) | **Accept (3 항 모두)**: (1) 5/6 신규 component degraded (Windows path encoding, pykrx KOSPI200 API mismatch) — *환경 문제* 로 backlog Issue #20, #21 추가. (2) F6 −3.00 floor clamp — baseline sd=1e12 부족 → backlog Issue #22 (sd 재교정). PR2 backtest 시 real historical 으로 re-estimate. (3) dominant_scenario kr_boom + KR equity +8.2pp narrative — F6 floor clamp 가 narrative 에 명시되어 의미 있음. Production fix 는 별도 PR. | grill-me #4 | 2026-05-24 | C10 후 |
| D13 | C10 의 *실제 신호 변화 limitation* | 4 개 (CFNAI + slope_5_30y + F6 baseline + F3 real_rate path)만 production 반영. KOSPI PBR, realized_vol, sector_dispersion, skew change 는 sentinel. Linux/CI 환경에서 verify 필요. | grill-me #4 추가 | 2026-05-24 | C10 후 |
