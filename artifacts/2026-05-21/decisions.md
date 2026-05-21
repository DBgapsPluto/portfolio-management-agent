# Stage 1 Indicator Fixes — Decision Log (2026-05-21)

> **목적:** Multi-commit 작업 중 조건부 결정을 결정 시점에 외부화. 코딩 시점에는 이 파일을 Read해서 인용.
>
> **Protocol:** `docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md` 8 원칙 그대로 적용 (filesystem-as-state).

---

## 결정 테이블

| # | 항목 | 결정 | 근거 | 시각 | commit |
|---|---|---|---|---|---|
| D0 | Base branch | `feat/db-gaps-redesign` (origin tip `77f70b2`) | 사용자 선택 (AskUserQuestion 응답); stage2 와 독립 진행 | 2026-05-21 | (spec commit) |
| D1 | Scope | 4 issue 모두 — cold analysis 의 수정 권고 반영 | 사용자 선택; #1 sequential framework / #2 HY OAS full / #3 schema migration plan 포함 / #4 display only | 2026-05-21 | (spec commit) |
| D2 | PR style | Mega-PR (spec → plan → C0 → C1~C5) | 사용자 선택; stage2 패턴 답습 | 2026-05-21 | (spec commit) |
| D3 | Holdout window | 2022-06-01 ~ 2024-12-31 | cold analysis 마지막 첨언; "역사 룰이 모두 깨졌던 시기" | 2026-05-21 | (spec commit) |
| D4 | VXVCLS 가용성 | **TBD — C1 시작 시 측정** | FRED API 직접 fetch 필요. deprecated 의심 (직전 VVIXCLS/MOVE 전례) | 측정 후 갱신 | C1 |
| D5 | VXVCLS fallback | yfinance `^VIX3M` (D4 fail 시) | CBOE 공식 3-month VIX, yfinance 안정 | C1 | C1 |
| D6 | Risk composite weights | **TBD — C0 holdout 결과로 결정** | 0.55/0.20/0.25 (원안) vs ablation 후 재조정. dataclass 외부화 | C0 종료 후 | C2 |
| D7 | YC bull steepener 임계 | **TBD — percentile 기반 변환** | `-25bps min spread` 등 절대값 → 5y percentile (e.g., spread 5y 5pct 이하 = "deeply inverted") | C2 시작 전 | C2 |
| D8 | FX level window | 5y vs 10y | yfinance USD/KRW 10y 데이터 가용성에 따름. C3 시작 시 측정 | C3 시작 전 | C3 |
| D9 | `krw_structural_weak` enum 위치 | `FXSnapshot.regime` Literal 4 → 5 값 | 영향 파일 사전 리스팅 완료 (spec §4.3) | 2026-05-21 | C3 |
| D10 | Fed display field count | 6m/12m/24m bps + implied_moves_12m (4개) | adaptive band 분류 로직 변경 X — display 전용 | 2026-05-21 | C4 |
| D11 | Holdout false positive 채택 기준 | 신규 룰의 FP 가 baseline 의 50% 이하 | cold analysis 의 정량 기준 부재 → 절반 감소를 합격선으로 임의 설정. 결과 분포에 따라 C0 종료 후 재검토 | 2026-05-21 | (spec) |

---

## 결정 분기 (앞으로 발생할)

- **D4 결과**: VXVCLS 사용 가능 → 그대로 진행 / 사용 불가 → D5 (yfinance ^VIX3M) 으로 데이터 소스 교체
- **D6 결과**: holdout FP 가 weights 변화에 민감 → dataclass 외부화 + sensitivity test / 둔감 → 0.55/0.20/0.25 채택
- **D7 결과**: percentile 변환 시 historical recession trigger 6/6 잡힘 → 채택 / 일부 누락 → 절대값 hybrid 검토
- **D8 결과**: yfinance USD/KRW 10y full data 가용 → 10y 채택 / gap → 5y 로 fallback

각 결정 직후 이 파일에 row 추가 + commit. **결정과 코드 변경은 다른 commit 으로 분리**.

---

## Background process / measurement log

(C0 부터 채워질 예정)

| job | started | expected_done | status | output |
|---|---|---|---|---|
| holdout backtest (baseline) | TBD | ~30min | not started | `artifacts/2026-05-21/holdout/baseline_fp.json` |
| holdout backtest (proposed) | TBD | ~30min | not started | `artifacts/2026-05-21/holdout/proposed_fp.json` |
| VXVCLS availability check | TBD | <5min | not started | `artifacts/2026-05-21/vxvcls_check.txt` |

---

## Cross-reference

- Cold analysis (직전 세션, 본 PR의 직접 동기): conversation history (2026-05-21)
- 직전 PR (`77f70b2` 까지 merged on origin): hardcode caveat #2~#7 + indicator audit
- Stage 2 동시 진행 (`feat/stage2-bottleneck-fixes`): 본 PR 과 file-level overlap 없음 (확인 완료, spec §1.4)
