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

## grill-me decisions (appended at each grill point)

(grill-me #1: TBD — Task 3.4 시점)
(grill-me #2: TBD — Task 5.4 시점)
(grill-me #3: TBD — Task 8.3 시점)
