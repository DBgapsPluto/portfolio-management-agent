# Stage 3 — Cluster-aware ETF Selection 고도화 (Track A)

- **작성일:** 2026-05-25
- **범위:** Stage 3 candidate **selection** funnel (eligibility → scoring → de-dup). "어느 ETF가 bucket에 들어가나".
- **비범위:** Stage 3 **optimizer**(weight·제약, ④) 및 아키텍처 리뷰 AP1/AP7/AP8/AP11 → **별도 Track B**. Stage 2 factor model(AP4/AP10) → PR2a(친구) 영역. broad-beta 앵커 → 후속(backtest 후 재고).
- **선행 분석:** `docs/architecture-review-2026-05-24.md`(AP 백로그), 본 대화의 pool 두께·두 패러다임·데이터 가용성 조사.
- **검증:** mechanism/non-regression/synthetic(현 환경) + economic backtest(Linux gate).

---

## 1. 배경 + 동기

### 1.1 문제

Stage 1 technical analyst는 Tier 1~5로 188 ETF × 다수 지표(`extended_indicators`, `trend_quantification`, `universe_breadth`, `sector_rotation`, `risk_adjusted`, `correlation_clusters`)를 생산하지만, **의사결정엔 `factor_panel`(Stage 3 선정) + `correlation_clusters`(Stage 4/5 cluster cap)만** 소비됨. Stage 2 factor model은 technical을 0개 읽음. 대부분의 풍부한 출력이 사장.

### 1.2 냉정한 진단 (코드·데이터 검증)

- **현 `factor_scorer`는 순수 "패러다임 2"**: bucket 내 cross-sectional momentum/low-vol/Sharpe/size 랭킹 + corr<0.85 de-dup. **sector 선택 = 이 composite 점수가 결정**하고, de-dup은 상관 높은 쌍만 제거(어느 sector를 담을지는 안 정함).
- **bucket 구조는 대체로 자산배분 분해** → 많은 sub-pool ETF가 **같은 beta의 대체재**(국내주식_지수, 채권, 현금). 대체재에 momentum 랭킹은 노이즈; 진짜 차별점(비용·추적·유동성)은 현재 로직·데이터에 **부재**.
- **실제 pool 두께** (188 ETF, 1조 AUM 필터 후): kr_equity 21, global_equity 14(충분) / **fx_commodity 2, bond 5, cash_mmf 4(굶주림)**. → 3/5 bucket은 scoring이 무의미하고 optimizer infeasibility 유발.
- **데이터 가용성:** 추적오차(`get_etf_tracking_error`)·괴리율(`get_etf_price_deviation`)·거래량(이미 fetch)은 pykrx로 가능(Linux). **TER·bid-ask spread는 직접 불가** — 추적오차가 TER 효과 proxy, 거래량이 spread proxy.
- **산업 실무**(Schwab/Betterment/State Street/CFA): 대체재 sleeve 선정은 **비용·추적·유동성**(구현-품질)이 1순위. 우리가 빠뜨린 차원.

### 1.3 핵심 아이디어 — cluster-aware 선택

technical `correlation_clusters`로 bucket pool을 **노출 그룹**으로 분할:
- **그룹 *간*(다른 beta) → alpha 랭킹**(어느 노출/sector — 패러다임 2, 정당).
- **그룹 *내*(대체재) → 구현-품질 랭킹**(대체재 중 최선 vehicle — 패러다임 1).

한 규칙이 (a) 미사용 clusters를 선택에 활용, (b) 두 패러다임을 통일 로직으로 화해(분기 if 아니라 cluster 멤버십이 기준 결정), (c) technical 출력을 제자리에 활용.

---

## 2. 설계 결정 요약

| # | 결정 | 선택 | 비고 |
|---|---|---|---|
| D1 | 범위 | 선택 funnel만 (레버 0~3) | optimizer·AP = Track B |
| D2 | eligibility floor | **flat ~500억** + `_RELAXED_MIN_AUM_KRW`(sub-cat) 유지 | 1조→500억(≈5×100억 capital). per-bucket floor 안 함 |
| D3 | 유동성 | hard filter→**impl_score의 scored factor**로 이동 | 병목 해소 + 구현-품질 도입 동시 |
| D4 | alpha·impl 결합 | **분리(no blend)**: 그룹 간=alpha, 그룹 내=impl | 임의 가중 0 |
| D5 | alpha 강화 | qual=mean(sharpe,sortino,calmar,−maxDD), mom=mean(skip1m,trend_strength,accel) | regime weight 테이블 불변 |
| D6 | timing 오버레이 | bounded soft 가감점, named const(`cap=0.3, δ=0.1`) | 수치는 backtest 튜닝 |
| D7 | impl_score | Phase1: 거래량·괴리율·log_aum / Phase2: +추적오차 | per-signal neutral fallback |
| D8 | cluster source | technical `correlation_clusters` ∩ bucket eligible; 미포함=singleton; sparse면 pairwise corr fallback | |
| D9 | acceptance | Δcorr≤0 ∧ Δvol≤+ε ∧ do-no-harm(Δret≥−ε); win-rate informational | ε는 spec 수치(아래) |
| D10 | broad-beta 앵커 | **OUT** (cluster-aware가 부분 완화; backtest 후 재고) | |

**검증 환경 제약 (정직):** economic backtest(`run_krx_backtest`)는 KRX creds·pykrx cache·Linux 필요 → **현 Windows 환경에서 실행 불가**(pykrx Issue #21). 현 환경 = mechanism/non-regression/synthetic까지. economic 판정 = Linux gate.

---

## 3. Architecture — cluster-aware 선택 파이프라인

```
bucket eligible = tradable ∩ category ∩ AUM ≥ floor(~500억, sub-cat 완화)     [D2]
  │
  ├─ alpha_score(t)  = regime-blend{mom*,lowvol,qual*,size} + scenario_boost + timing   [D5,D6]
  └─ impl_score(t)   = z(거래량↑) + z(−|괴리율|) + z(log_aum) [+ z(−추적오차) Phase2]    [D7]
  │
  cluster-aware select (n = per_bucket_n):                                       [D8]
    1. eligible → groups: correlation_clusters ∩ bucket (멤버 공유=대체재), 미포함=singleton
    2. 각 group의 alpha_repr = max(alpha_score over group members)
    3. groups를 alpha_repr 내림차순 정렬 → 상위 n개 group 선택            (= 어느 beta/sector)  [D4]
    4. 선택된 각 group에서 impl_score 최고 1개 대표 선택                   (= 대체재 중 최선 구현) [D4]
    5. 선택 group 수 < n 이면, 이미 뽑힌 그룹의 차순위 member + 남은 ticker를
       alpha_score 순으로 패딩 (현행 select_diverse 패딩과 동등 — 얇은 pool에서 bucket 채움 우선)
  │
  chosen[:n] → CandidateSet
```

- **`select_diverse` 흡수:** corr<0.85 greedy de-dup → cluster 그룹화가 substitutability 정의. **cluster 없거나 sparse하면 기존 pairwise-corr 그룹화로 graceful fallback** (통일 로직 유지).
- 얇은 pool: group 수 < n이면 패딩(현행 select_diverse 패딩과 동등) → graceful.

---

## 4. 컴포넌트

### 4.1 `alpha_score` — "어느 노출" (factor_scorer 강화)

regime weight 테이블(`REGIME_FACTOR_WEIGHTS`) **불변**. family 내부만 sub-composite로:
```
qual_raw  = mean( z(sharpe_60d), z(sortino_60d), z(calmar_12m), z(−max_drawdown_12m) )   # risk_adjusted
mom_raw   = mean( z(skip1m_mom_composite), z(trend_strength_score), z(momentum_acceleration) )  # +trend_quant
lowvol_raw= −z(realized_vol_60d)        # 현행
size_raw  = z(log_aum)                  # 현행
composite = w_mom·mom_raw + w_lowvol·lowvol_raw + w_qual·qual_raw + w_size·size_raw
            (w = blend_regime_weights(quadrant, confidence) — 현행) + scenario log_boost(현행)

timing = clamp( −δ·divergence(bearish) + δ·divergence(bullish)
                −δ·overbought(%B>1 ∨ mfi>80 ∨ stoch_k>80)
                −δ·(trend_state ∈ {breakdown, downtrend})
                +δ·is_mean_reversion_candidate,  −cap, +cap )   # extended_indicators + risk_adjusted
alpha_score = composite + timing
```
- regime 적합도는 기존 blend가 자동 처리(침체 regime에서 qual/lowvol 가중↑ → sortino/calmar/maxDD 강조). timing엔 별도 regime 파라미터 없음.
- 모든 패널 누락 ticker → 해당 신호 z=0(현행 `_zscore` None→0 정합).

### 4.2 `impl_score` — "대체재 중 최선 vehicle" (신규 순수 함수)

```
Phase 1: impl_score = z(거래량/거래대금 ↑) + z(−|괴리율|) + z(log_aum)      # 현 환경 가능 (괴리율 없으면 생략)
Phase 2: impl_score += z(−추적오차)                                          # Linux fetch + universe enrich
```
- bucket pool 내 상대 z. 신호 누락 → neutral(0). Phase 2는 Phase 1 interface에 adapter로 추가(코드 구조 불변).

### 4.3 cluster-aware select (신규, `select_diverse` 대체/흡수)

§3의 5단계. 입력: eligible, alpha_score, impl_score, clusters, n. 출력: chosen 리스트. clusters sparse/부재 시 pairwise-corr 그룹화 fallback.

### 4.4 eligibility floor 교정 (`list_eligible_tickers`/`select_etf_candidates`)

flat floor 1조 → ~500억(config/capital 파라미터). `_RELAXED_MIN_AUM_KRW` 유지. **중복 eligibility 필터 정리**: `list_eligible_tickers`와 `select_etf_candidates`가 동일 필터를 두 번 계산 → 단일 helper로 통합(in-path 정리).

---

## 5. 2-Phase 구성

- **Phase 1 (현 환경 완결):** D2,D3,D4,D5,D6,D8 + impl_score(거래량·괴리율·AUM proxy). mechanism/non-regression/synthetic 검증.
- **Phase 2 (Linux):** D7의 추적오차 — `dataflows/pykrx_data.py`에 `fetch_etf_tracking_error` 추가 + universe enrich 스크립트 + impl_score에 adapter. economic backtest gate.

---

## 6. 검증 전략

### 6.1 현 환경 (가능)

- **Property test** (mechanism, 구성상 증명):
  - 동일 sharpe·높은 sortino → 높은 alpha; bearish divergence/overbought/breakdown → 페널티; mean-reversion → 보너스; timing ∈ [−cap,+cap].
  - cluster 그룹 내에서 **impl_score 최고가 대표로 선택**됨(alpha 최고가 아니라).
  - 그룹 간은 alpha 순.
- **Non-regression:** 새 패널·clusters·impl 데이터 미제공 시 선정 결과가 **현행과 동일**(backward-compat 기본값). 기존 factor_scorer/candidate_selector 테스트 통과.
- **Synthetic:** `backtest_candidate_selection.py --mode synthetic` 확장 — 대체재 그룹에서 추적오차/유동성 우량이 선택되는지, 차별 그룹에서 momentum 작동하는지.

### 6.2 Linux gate (economic, commit/push 전제)

- `backtest_candidate_selection.py`를 **"현행 vs 신규"** 비교로 확장(현재는 legacy-momentum vs multi-factor). 분기 grid forward 수익/vol/corr.
- **Acceptance:** `mean(Δcorr) ≤ 0` **AND** `mean(Δvol) ≤ +0.2%p` **AND** `mean(Δreturn) ≥ −0.2%p`. win-rate는 보고만.
- 미통과 시: "더 낫다" 주장·머지 보류, 진단 후 파라미터(δ/cap/floor/ε) 재튜닝 또는 설계 재검토.

---

## 7. Backward-compat & 안전

- `score_candidates`·`select_etf_candidates`에 신규 인자(패널·clusters·impl 데이터)는 **optional, 기본 None/empty** → 미제공 시 현행과 수학적 동일. 모든 기존 호출부·테스트 보호.
- 스키마(`BucketTarget`/`CandidateSet`/`WeightVector`) **불변**. optimizer(④) **불변**. Stage 2 **불변**.
- floor 인하는 투자성 최소선 유지(거래 가능) + 유동성 scored factor가 soft 선호 → 영세 ETF 과다 선택 방지.

---

## 8. 건드리는 파일

**수정:**
- `tradingagents/skills/portfolio/factor_scorer.py` — alpha family 강화 + `_timing_overlay`(신규) + `impl_score`(신규) + cluster-aware select helper.
- `tradingagents/skills/portfolio/candidate_selector.py` — cluster-aware select 호출, 패널·clusters thread, eligibility 필터 통합, floor 인하.
- `tradingagents/agents/allocator/portfolio_allocator.py` — technical 패널(`risk_adjusted`/`trend_quantification`/`extended_indicators`/`correlation_clusters`) thread.
- (Phase 2) `tradingagents/dataflows/pykrx_data.py` — `fetch_etf_tracking_error`/`_price_deviation`.
- (Phase 2) `scripts/enrich_universe_*.py` 또는 신규 — 추적오차/괴리율 enrich.
- `scripts/backtest_candidate_selection.py` — 현행 vs 신규 비교 모드.

**테스트(신규):**
- `tests/unit/skills/test_portfolio_factor_scorer.py` 확장 — family 강화·timing·impl property + non-regression.
- `tests/unit/skills/test_portfolio_candidate.py` 확장 — cluster-aware select(그룹 간 alpha / 그룹 내 impl / fallback).

---

## 9. 비범위

- Stage 3 optimizer 제약 통일(AP1/AP8/AP11), risk-asset 정의 정리(AP7) → **Track B**.
- Stage 2 factor model(AP4/AP10) → PR2a.
- broad-beta 앵커 → backtest 후 재고(cluster 구조상 1줄 추가 가능).
- TER/bid-ask spread 직접 데이터 → 미확보(추적오차/거래량 proxy로 대체).

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| economic 검증을 현 환경에서 불가 | Linux gate 명시; 현 환경은 mechanism/non-regression까지. "더 낫다"는 gate 통과 후에만 주장 |
| pykrx 추적오차 데이터 품질(공식과 상이 가능, GitHub 이슈) | Phase 2에서 enrich 시 품질 검증 단계 포함; 미신뢰 시 거래량 proxy로 degrade |
| ~10 분기 grid → 통계적 유의성 부족 | acceptance를 "통제 가능 지표(corr/vol) gate + 수익률 do-no-harm"으로 설계(노이즈 이기기 요구 안 함) |
| cluster sparse(top returns만 계산) → 그룹화 불완전 | pairwise-corr fallback + singleton 처리 |
| floor 인하로 영세 ETF 과다 | 유동성 scored factor + 투자성 최소선 유지 |
| 통일 로직이 사실 paradigm-split이라 복잡 | cluster 멤버십이 기준을 자동 결정 → 분기 if 없음. fallback 1개 |

---

## 11. Sign-off Checklist

- [ ] Phase 1 구현 + property/non-regression test 통과(현 환경)
- [ ] non-regression: 신규 입력 미제공 시 현행과 동일 선정 확인
- [ ] synthetic backtest: 대체재 그룹 impl 선택 + 차별 그룹 momentum 작동
- [ ] Phase 2: 추적오차/괴리율 fetch + enrich + 품질 검증 (Linux)
- [ ] economic backtest(현행 vs 신규) Linux 실행 + acceptance(Δcorr≤0 ∧ Δvol≤+ε ∧ Δret≥−ε)
- [ ] acceptance 통과 시에만 "개선" 주장 + 머지; 미통과 시 재튜닝/재검토
- [ ] 스키마·optimizer·Stage 2 불변 확인

---

## 12. 참조

- 아키텍처 백로그: `docs/architecture-review-2026-05-24.md` (Track B = AP1/7/8/11)
- 현행 선정: `tradingagents/skills/portfolio/{candidate_selector,factor_scorer}.py`
- backtest harness: `scripts/backtest_candidate_selection.py`
- technical 스키마: `tradingagents/schemas/technical.py`, `reports.py` (TechnicalReport)
- 데이터: pykrx `get_etf_tracking_error`/`get_etf_price_deviation`; KRX/KOFIA(TER)
