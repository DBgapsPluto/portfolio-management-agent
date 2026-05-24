# PR2a Calibration — Decisions Log

본 파일은 spec `2026-05-23-stage2a-calibration-design.md` 의 section 0 결정 의 외부화.
모든 grill-me 결정도 본 파일에 append.

## Brainstorming 결정 (확정 — 2026-05-23)

- Q1 Scope: 2-PR decompose (PR2a data+calibration / PR2b benchmarks+analysis)
- Q2 Window: 1991-Q1 to 2024-Q3 (135Q) with graceful per-factor degradation
- Q3 Calib target: β only (45 params) with shrinkage + sign penalty
- Q4 Calib protocol: shrinkage grid {0.1, 0.3, 0.5, 1.0, 2.0} × walk-forward (initial_train=80, test=7) → 7 folds
- Q5 Acceptance: strict-default 5-condition (Critical 3 강화)
- Q6 Reconstruction: production reuse with date-parameterized minimal-proxy Stage 1 builder
- Q7 Linux/cache: Linux-first + multi-tier cache (raw gitignored, quarterly + factor z + bucket returns + samples committed)
- Q8 Execution: PR1 방식 — commit 순차 + grill-me 3회 + per-commit regression
- Q9 Issue scope: 최소 범위 — Linux 우회 #20/#21, 영구 fix 별도 PR

## Critical issue 처리

- C1 (Point-in-time): ALFRED vintage fetch for 7 series (CFNAI, NFCI, ANFCI, GDPNOW, UNRATE, CPIAUCSL, PCEPILFE) — **2026-05-24 정정 완료**: plan/spec 4개 문서의 `CFNAINMNI` typo (ALFRED 에 존재하지 않는 ID) 를 `CFNAI` 로 일괄 정정. 정정 대상: stage2a plan/spec + stage1 plan/spec (PR1 의 잔존 typo). Production 코드는 처음부터 `CFNAI`/`CFNAIMA3` 를 사용 중. C1 의 fetcher_alfred.py 는 정정된 plan 기준으로 작성.
- C2 (News-sentinel mismatch): factor_estimators 의 mode="historical" flag — news weight 0 + quant renorm
- C3 (Gate strictness): paired-t p<0.20 + |IS-OOS|<0.30 + ≥6/7 folds positive
- C4 (Currency basis): KRW basis with USDKRW translation, pre-1996 kr_equity None

## macOS 호환성 검증 결과 (2026-05-24, pre-C0)

Plan 은 명시적으로 "Linux-first" 라고 명시하나, 실제 macOS arm64 환경에서 smoke test:

- **FRED** (`dataflows.fred.fetch_fred_series`): PASS — DGS10 2024-01 23 rows.
- **ALFRED** (vintage HTTP): 6/7 PASS, 1 series ID 오류 (`CFNAINMNI` 부재 → `CFNAI` 로 정정 예정).
- **yfinance** (`yf.download("^GSPC", ...)`): PASS — Issue #20 (Windows curl_cffi SSL fail) 은 macOS 에서 manifest 안 함.
- **pykrx** KOSPI200 fundamental (`stock.get_index_fundamental("1028")`): PASS — Issue #21 (Windows pykrx API mismatch) 도 macOS 에서 manifest 안 함. `.env` 의 KRX_ID/KRX_PW 로 로그인 정상.
- **pykrx** foreign flow (production-used): PASS — 7 rows.

결론: macOS 에서 plan 실행 가능. Linux-only 가정 무효.

## Deferred items

- **Shiller CAPE static CSV** (Task 2.3): plan 은 1881-2024 monthly CAPE10
  (~1700 rows / ~50KB) 정적 commit 을 요구 하나, 본 데이터 는 외부 manual
  download (Robert Shiller site / multpl.com) 이 필요. C2 의
  `assemble_quarterly_panel` 은 CSV 부재 시 `shiller_cape` 컬럼만 graceful
  skip (다른 columns 정상). F8 (KR equity valuation) factor 는 KOSPI200
  PBR/PER 만으로도 partial coverage — degradation 허용. C5 의 135Q sample
  생성 전에 user 협조 받아 CSV 추가 필요 시 grill-me #1 시점에 결정.

## grill-me decisions (appended at each grill point)

### grill-me #1 (Task 3.4, 2026-05-24) — DECIDED

3개 review 주제 모두 user "OK — C4 진행" 결정.

1. **Fetcher API + retry/timeout** — current setting (0.6s sleep + 3-retry
   exponential backoff) 적절. 945 calls × ~9.5분. C5 실제 fetch 시점에
   문제 시 조정.
2. **Stage1 builder sentinel policy** — baseline mean fallback 그대로.
   staleness=99 명시 sentinel 과 calibration 효과 identical (panel z-score
   에서 mean=0 → z=0).
3. **Bucket returns KRW basis** — pre-1996 kr_equity NaN, pre-2002 bond
   yield-derived. Plan 의도된 trade-off 수용 (1996 이전 분기 data 손실
   불가피).

→ C4 (factor_estimators mode='historical' flag) 진행.

### grill-me #2 (Task 5.4, 2026-05-24) — DECIDED: OK, C6 진행

3개 review 주제 모두 user "OK — C6 진행" 결정.

1. **Factor z coverage by era** — confidence 0.723 (모든 era 동일).
   ALFRED 데이터 (CFNAI/NFCI/ANFCI 2011+, GDPNow 2016+) 가 era 별 다르지만
   baseline-fallback 이 confidence 일정 유지. Plan 의도된 trade-off.
2. **mode='historical' 효과** — 4 factor (growth/inflation/term_premium/
   equity_vol) std > 0.4 = calibration 충분 분산. F1 std=0.47 (ALFRED
   CFNAI fix 후 3배 확대).
3. **2008-Q4 GFC outlier** — 매크로 시그니처 합리적
   (inflation=-2.21, real_rate=+1.31, credit=+0.34, equity_vol=+1.83).

### grill-me #3 (Task 8.3, 2026-05-24) — DECIDED: B. Marginal accept

C8 calibration verdict: 4/5 PASS, 1 marginal sign violation (F7×kr_equity
β=+0.0009, expected negative).

User "B. Marginal accept" 결정 — 0.0009 는 noise level (β bound 0.20 의
0.5%). Spec section 3.6 의 tolerance 옵션 적용: `_SIGN_TOLERANCE` 1e-9 →
1e-3. Strict gate 의도 (큰 위반 reject) 유지하면서 numerical edge case 만
통과.

→ C9 path (PASS): INITIAL_BETA 교체. +34% OOS Sharpe gain 확보.

## Final Status (PR2a 완료, 2026-05-24) — PASS

- Acceptance: PASS (all 5 conditions, sign tolerance 1e-3)
- Best shrinkage: 2.0
- Improvement Δ: +0.342 OOS Sharpe (prior 0.829 → calibrated 1.171, +41%)
- Paired-t p: 0.080 (< 0.20 threshold)
- INITIAL_BETA: **data-driven 교체 완료 (C9)**

## Critical issue 처리 결과
- C1 ALFRED vintage: completed (7 series fetched + HTTP 400 graceful None)
- C2 mode='historical': completed (production-mode default backward-compat
  100% PASS)
- C3 strict default gate: applied with relaxed sign tolerance 1e-3
- C4 KRW basis bucket: applied (pre-1996 kr_equity NaN → 0.0 fallback)

## Plan errata 보정 (총 6건)
1. CFNAINMNI → CFNAI series ID 정정 (4 plan/spec docs, pre-C0).
2. test_fetcher_alfred 의 cache range/mock boundary 보정 (C1).
3. stage1_builder template 완전 재작성 (production schema mismatch, C3).
4. ALFRED HTTP 400 graceful None (C5 re-run 발견).
5. samples.parquet column → FACTORS key mapping fix (C8 re-run 발견).
6. test_factor_to_bucket 의 row-sum-zero invariant 제거 (C9).
