# 결정론 다이얼 튜닝 하네스 설계

**작성일:** 2026-06-04
**상태:** 설계 확정 (구현 대기)
**선행:** 백테스트 PIT 정직성(2026-06-04) — lookahead 제거 완료. 데이터 품질 선결 조건 충족.

---

## 1. 배경 — 목적

`vol_haircut`·`duration` 등 v1 시드 상수가 백테스트로 검증되지 않았다. 이 하네스는 **결정론(post-LLM) 다이얼을 과거 날짜들에서 sweep해 realized forward 성과로 점수화하고, 레짐 전반에서 robust한 값을 *추천*** 한다 (자동 적용 안 함).

**핵심 비용/정직성 통찰 (탐색으로 확정):**
- 다이얼이 *1개의 LLM tilt 호출* 기준 어디에 있느냐로 비용이 갈린다. **post-LLM 다이얼(vol_haircut floor/margin)** 은 tilt를 고정하면 LLM 무호출로 ms 단위 재실행 가능.
- post-LLM 다이얼 입력은 PIT 깨끗(vol=가격, duration=종목명). + tilt 고정 → **LLM 오염·비결정 노이즈가 다이얼 *상대* 비교에서 상쇄.**
- replay 인프라 검증됨: 4개 튜닝 날짜 전부 `runs/{as_of}/` 아카이브 존재, `technical_report.factor_panel`(realized_vol_60d) 복원 확인, `run_stage(graph,"allocator",state,write_to_archive=False)`로 allocator 단건 재실행 가능.

---

## 2. 범위

**In scope (확정):**
- 다이얼: **vol_haircut `floor`{0.5,0.6,0.7} × `margin`{0.1,0.2,0.3}** = 9 조합.
- 날짜: **4개** — 2022-12-15, 2023-04-14, 2024-08-14, 2025-04-15 (forward 데이터 충분, 2026-05 제외).
- 목표: **robust Sharpe** (날짜 전반 median 1차 + min 병기), forward horizon **63 거래일(~3M)**.
- 산출: 조합 랭킹 리포트 (stdout + `artifacts/tuning/vol_haircut_sweep.json`). **자동 적용 안 함.**

**Out of scope:**
- QUADRANT_BASELINE 등 **LLM-입력 다이얼** (full 재실행 필요 + 더 많은 데이터 — 별도).
- duration/SINGLE_CAP 다이얼 plumbing (이번 grid 미사용 — YAGNI, 미배선).
- 튜닝값 자동 코드 반영 (사람이 리포트 보고 결정).
- 캐시 단계 자동화(4 날짜 이미 아카이브 존재; 없으면 `run_backtest.py`로 선실행).

---

## 3. 컴포넌트

### 3.1 Trader 노드 plumbing (`tradingagents/agents/trader/trader_allocator.py`)
세 가지 (sweep 가능하게):
1. **`cached_tilt` 사용** (force_method 패턴): 현재 `tilt = invoke_structured_obj(structured_a, _step_a_prompt(...), BucketTilt(), "TraderStepA")` →
   ```python
   tilt = state.get("cached_tilt") or invoke_structured_obj(
       structured_a, _step_a_prompt(...), BucketTilt(), "TraderStepA")
   ```
   `cached_tilt` 있으면 LLM skip. (라이브/일반 실행은 None → 기존대로 LLM 호출, 불변.)
2. **`portfolio_dials` 적용**: `apply_vol_haircut` 호출에 floor/margin override:
   ```python
   dials = state.get("portfolio_dials") or {}
   hc_kwargs = {}
   if "vol_haircut_floor" in dials:  hc_kwargs["floor"]  = dials["vol_haircut_floor"]
   if "vol_haircut_margin" in dials: hc_kwargs["margin"] = dials["vol_haircut_margin"]
   bucket_weights = apply_vol_haircut(bucket_weights, bucket_vol, **hc_kwargs)
   ```
   (dials 없으면 함수 기본값 = 현재 상수 → 불변.)
3. **tilt 노출** (하네스가 첫 실행서 캡처): `attribution["step_a"]["tilt"] = dict(tilt.tilts)`.

> `cached_tilt`·`portfolio_dials`는 AgentState 옵셔널 필드로 추가(force_method 패턴; 미설정 시 None). 라이브 graph.run 경로 불변.

### 3.2 Forward 성과 점수 (`tradingagents/backtest/forward_perf.py`, 신규)
```python
def score_forward_performance(
    weights: dict[str, float], as_of: date, horizon_trading_days: int = 63,
) -> dict:
    """[as_of, as_of+H거래일] realized 포트 성과. fetch_returns_matrix + statistics 재사용."""
```
- `fetch_returns_matrix(tickers, as_of, as_of + timedelta(days=ceil(H*1.6)))` → 일별 수익 행렬.
- 포트 일별수익 = Σ wᵢ·rᵢ; 앞에서 `horizon_trading_days` 행만 사용.
- 반환: `{sharpe, total_return, ann_vol, max_drawdown, n_obs}`.
  - sharpe = `tradingagents/backtest/statistics._sharpe(daily, periods_per_year=252)`.
  - max_drawdown = `drawdown_analysis(daily)["max_drawdown"]`.
  - n_obs < ~40이면 `{"status":"insufficient_data", "n_obs":n}` (점수 제외).

### 3.3 Sweep 하네스 (`scripts/tune_dials.py`, 신규)
```
DATES = ["2022-12-15","2023-04-14","2024-08-14","2025-04-15"]
GRID  = product(floor∈{0.5,0.6,0.7}, margin∈{0.1,0.2,0.3})   # 9

graph = TradingAgentsGraph(preset_name="db_gaps")
per_date_tilt = {}
for d in DATES:
    state = restore_state(d, "allocator")          # 아카이브 복원 (factor_panel 포함)
    assert technical_report.factor_panel 비어있지 않음   # 가드 — 없으면 sweep 무의미
    out = run_stage(graph, "allocator", state)     # LLM tilt 1회
    per_date_tilt[d] = BucketTilt(tilts=out["allocation_attribution"]["step_a"]["tilt"])

results = []   # (floor, margin, {date: sharpe}, median, min)
for (floor, margin) in GRID:
    sharpes = {}
    for d in DATES:
        state = restore_state(d, "allocator")
        state["cached_tilt"] = per_date_tilt[d]          # LLM 무호출
        state["portfolio_dials"] = {"vol_haircut_floor": floor, "vol_haircut_margin": margin}
        out = run_stage(graph, "allocator", state)
        weights = out["weight_vector"].weights
        perf = score_forward_performance(weights, date.fromisoformat(d), 63)
        if perf.get("status") != "insufficient_data":
            sharpes[d] = perf["sharpe"]
    results.append({floor, margin, sharpes, median, min, mean})

# median desc 정렬, min 병기 → stdout 표 + artifacts/tuning/vol_haircut_sweep.json
# 현재 기본값(0.6, 0.2) 행을 baseline으로 표시. 자동 적용 안 함.
```

---

## 4. 데이터 흐름 / 비용
- 4 날짜 아카이브 이미 존재 → 캐시 단계 skip. tilt 캡처 = 날짜당 LLM 1회(~3s) × 4 = ~12s.
- Sweep = 9조합 × 4날짜 = 36 allocator 재실행 × ~10ms(LLM 무호출) + forward 가격 fetch(캐시됨) → 수십 초.
- forward 가격은 `fetch_etf_price_batch`/`fetch_returns_matrix`가 pykrx 캐시 사용.

## 5. 에러 처리
- restore_state 실패(아카이브 없음) → 그 날짜 skip + 경고(또는 사전 `run_backtest`로 생성 안내).
- factor_panel 비어있음 → assert로 중단(sweep 무의미 방지).
- forward 데이터 부족(n_obs 적음) → 그 날짜 점수 제외, robust 집계서 빠짐(로그).
- 순수 함수·읽기 전용 sweep, 아카이브 미변경(`write_to_archive=False`).

## 6. 테스트
**단위:**
- `score_forward_performance` — `fetch_returns_matrix` monkeypatch로 알려진 행렬 주입 → sharpe/total_return/mdd 값·부호 검증; n_obs 부족 → insufficient_data.
- 노드: `cached_tilt` 주입 시 LLM(structured_a) 미호출 + 그 tilt 사용 / `portfolio_dials` floor 변경 → b8 비중 변화 (기존 test_trader_allocator 패턴 재사용, _FakeStep으로 LLM 호출 카운트).
- 노드 회귀: cached_tilt·portfolio_dials 미설정 → 기존 동작 불변.

**통합/E2E:**
- `scripts/tune_dials.py`를 1 날짜·축소 grid(floor{0.6}×margin{0.2})로 스모크 → 랭킹 결과·`vol_haircut_sweep.json` 생성, crash 없음.
- 전체 실행(4날짜×9조합) → 리포트 + baseline(0.6,0.2) 대비 robust median Sharpe 표를 사용자에게 보고.

## 7. 확장 항목 (v1 제외)
1. duration/SINGLE_CAP 다이얼 plumbing + grid 확장.
2. QUADRANT_BASELINE 등 LLM-입력 다이얼 (Tier-1 full 재실행 하네스).
3. robust 집계 대안(MDD 제약, IR, 가중 robust).
4. 더 촘촘한 날짜(월별) — 캐시 단계 자동화 필요.
5. 튜닝값 자동 반영(현재 수동).
6. BucketTilt를 `runs/`에 영구 아카이브(현재 in-memory 캡처).
