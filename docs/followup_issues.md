# Follow-up Issues — post 5/11 dry-run

5/28 본 제출까지의 작업 백로그. 각 issue는 GitHub에 그대로 file 가능한 형식.

---

## Issue #1 — debate: novelty 신호 추가로 무의미한 반복 토론 차단

### Problem
현재 `research_debate`의 2-신호(confidence + divergence) 적응형 루프는 한 가지 echo-chamber 케이스를 못 막는다:

- Bull과 Bear가 **같은 근거를 다른 표현으로 반복**하면 confidence는 안 오르고 divergence도 안 좁아짐.
- 결과: 새 정보 없는데도 hard cap(3 round)까지 돔.
- 5/11 dry-run 관찰은 안 했지만 LLM 응답 일반 패턴상 자주 발생.

### Proposed approach
`ResearcherTurn` 스키마에 **novelty 필드** 추가하고 `should_continue`의 3번째 정지 조건으로 활용. 이는 처음 설계 단계의 3-신호 옵션 중 simple 2-신호로 보류했던 항목.

```python
class ResearcherTurn(BaseModel):
    argument: str
    confidence: float
    proposed_risk_tilt: float
    new_evidence_points: list[str] = Field(default_factory=list, max_length=5)  # 신규
```

Bull/Bear 프롬프트에 "이전 라운드에서 안 나온 근거만 `new_evidence_points`에 적어라. 없으면 빈 list" 추가.

`should_continue` 신규 분기 (`debate_subgraph.py:29`):
```python
total_novelty = (
    len(bull_last.new_evidence_points) + len(bear_last.new_evidence_points)
)
if total_novelty == 0 and state["round_count"] >= 1:
    return "judge"   # 새 정보 0 — 더 토론해도 의미 없음
```

### Acceptance criteria
- [ ] `ResearcherTurn`에 `new_evidence_points` 필드 추가, max_length=5
- [ ] Bull/Bear prompt가 새 근거만 적시하도록 갱신
- [ ] `should_continue`에 novelty==0 정지 분기 추가
- [ ] 4개 시나리오 unit test 확장 (novelty==0 → 조기 정지, novelty≥2 → 계속)
- [ ] 5/28 dry-run 1회로 실제 LLM이 빈 list 출력하는지 확인

### Effort
~80 LOC + 1 schema field. 1~2 시간.

### Risk
LLM이 "새 근거"를 정직하게 분류할지 보정 안 됨. 처음엔 over-report 경향 있을 수 있음 (eval로 보정 필요).

---

## Issue #2 — allocator: 결정 과정 가시화 (debugging visibility)

### Problem
`portfolio_allocator`는 4 sub-step(candidate selection → returns matrix → method picker → constrained optimization)을 거치지만 **중간 상태가 trace에 안 남는다**. 최종 weights가 surprising할 때 어느 단계가 원인인지 진단 곤란.

5/11 dry-run에서 발견된 의문 예시:
- `risk_parity` method가 LLM에 의해 선택됐는데 왜?
- `A0061Z0` (RISE 단기특수은행채액티브)가 정확히 20% cap에 박힌 이유?
- 17 ETFs로 압축된 과정 (188 → 후보 → 최종)이 안 보임.

### Proposed approach
세 갈래 보완 (a + b 추천, c는 선택):

**a) `@traced` 데코레이터 추가** — sub-skill 각각을 LangSmith 자식 span으로:
```python
# tradingagents/skills/portfolio/candidate_selector.py
@traced(name="select_etf_candidates")
def select_etf_candidates(...): ...

# tradingagents/skills/portfolio/method_picker.py — already has @register_subagent which is traced
```

**b) `state["allocator_trace"]` 구조화 dict 추가** — node return에:
```python
return {
    "candidate_set": candidates,
    "weight_vector": wv,
    "allocation_attempts": attempts + 1,
    "allocator_trace": {  # 신규
        "eligible_pool_size_per_bucket": {b: len(t) for b, t in eligible_by_bucket.items()},
        "candidates_chosen": {b: candidates.bucket_to_tickers[b] for b in candidates.bucket_to_tickers},
        "method_chosen": method_choice.method.value,
        "method_rationale": method_choice.reasoning[:200],
        "feedback_applied": bool(feedback_violations),
        "binding_constraints": [t for t, w in wv.weights.items() if w >= 0.199],
    },
}
```

**c) (선택) `--verbose` 플래그 시 `artifacts/{date}/allocator_debug.json` 작성** — 후처리 분석용.

### Acceptance criteria
- [ ] 4 sub-skill에 `@traced` (또는 그에 준하는 logging) 추가
- [ ] `allocator_trace` dict가 state에 들어가고 portfolio_manager에서 portfolio.json에 포함
- [ ] LangSmith trace tree에서 allocator stage 클릭 시 4 자식 span 확인 가능
- [ ] 어느 ETF가 단일 cap에 binding됐는지 한눈에 보임

### Effort
~40 LOC. 1시간.

### Risk
LangSmith trace size 증가 (무료 티어 5000 traces 한도엔 영향 없음 — span 수 늘어도 trace count는 동일).

---

## Issue #3 — risk_debate: 역할 명확화 + 산출물 정의

### Problem
Stage 4(`risk_debate`)는 현재 **stub 상태**(`trading_graph.py:99`). 3-way debate 코드(Aggressive/Conservative/Neutral/RiskJudge)는 작성돼 있으나:
- 그래프에 wiring 안 됨
- 출력 `WeightAdjustment.delta`가 downstream에 소비되지 않음
- ±0.05 per ticker로 제약돼 최적화 결과를 미세조정만 가능
- 3-persona가 사전에 stance 정해진 *theatrical* 패턴

5/11 분석에서 옵션 B(simpler single risk_reviewer)와 D(현 stub 유지)를 후보로 봤고 D로 결정했지만, 그 후 본 dry-run을 거치면서 **포기보다는 "역할 재정의"가 더 유효**할 수 있다는 판단.

### Proposed approach
**스트레스 시나리오 시뮬레이션으로 재정의 (decision: option c)**

- Aggressive → bull-case scenario simulation (e.g., +10% equity rally with retained vol)
- Conservative → tail-risk scenario (e.g., -20% drawdown + VIX 40)
- Neutral → base-case
- Risk Judge → expected max DD + scenario-specific portfolio behavior
- Optimizer가 직접 못 하는 *forward-looking what-if* 정성 분석
- philosophy.md "5. 시장 충격 시나리오" 섹션을 LLM이 풍부하게 채움 (대회 §4.1 요구 사항)

기각한 대안 (요약):
- **a) Pure observational (read-only Risk Review)**: 가중치에 영향 없어 의미 작음.
- **b) Hold-out audit (정합성 점수)**: allocator 결과 사후 검증만 — 시나리오 narrative 산출 X, 대회 §4.1 미충족.
- **d) Stage 4 제거**: 가장 깨끗하지만 시장 충격 시나리오 섹션을 수기 작성해야 함.

### Acceptance criteria
- [ ] `WeightAdjustment` 스키마 → `StressScenarioReport` 스키마로 교체:
  ```python
  class StressScenarioReport(BaseModel):
      scenarios: list[dict]  # [{name, regime_assumption, expected_pnl, expected_dd, defensive_actions}]
      expected_max_dd: float
      narrative: str
  ```
- [ ] Aggressive/Conservative/Neutral prompts → 시나리오 시뮬레이션 형식으로 재작성
- [ ] RiskJudge가 3 시나리오 종합 → `StressScenarioReport` 출력
- [ ] `trading_graph.py:99` stub → `build_risk_debate_subgraph` 진짜 호출로 교체
- [ ] portfolio_manager가 `stress_scenario_report`를 state에서 받아 philosophy.md "5. 시장 충격 시나리오" 섹션에 주입
- [ ] 5/28 dry-run에서 시나리오 narrative 품질 확인

### Effort
~250 LOC + 4개 새 prompt + 통합 테스트. 4~6시간.

### Risk
- 비용 ~$0.02/run 추가 (3 quick + 1 deep LLM)
- LLM의 forward-looking scenario simulation은 *plausible*이지 *predictive* 아님 — narrative quality에만 의존
- 시나리오 prompt 보정 1~2 iteration 필요

---

## Issue #4 — analysts: 참고 지표/소스 확장 (umbrella)

### Context
현재 4개 애널리스트가 보는 정보:
- **macro_quant**: US yield curve (DGS10/2/3m), US CPI/employment (CPIAUCSL/UNRATE/PAYEMS), KR rate/CPI divergence (ECOS)
- **market_risk**: VIX, VKOSPI, HY/IG OAS, fear/greed, breadth, PCA
- **technical**: ETF 모멘텀 (3/6/12m), correlation cluster, TA indicators
- **macro_news**: 7 RSS + FOMC/BOK/KR 매크로 캘린더

**Coverage gap (자산배분 의사결정에 가치 있을만한 미수집 신호)**:

1. **KR-specific**: KRW/USD, 외국인 KOSPI 순매수, KOSDAQ
2. **Cross-asset**: MOVE 지수, BTC 추세, 원유 term structure, 금/은 비율
3. **Sentiment 보강**: AAII, Put/Call ratio, 한국 주식형 펀드 자금 흐름
4. **Earnings/fundamentals**: S&P500 earnings revision, KOSPI EPS 컨센서스

3개 sub-issue로 split — 독립적으로 PR 가능. #4-a 먼저, 시간 남으면 #4-b → #4-c.

### Common risk (모든 sub-issue 공통)
- LLM 프롬프트가 더 많은 지표를 한 번에 받으면 신호 분별력 떨어짐 (information overload) — summary_for_downstream에 1줄씩만 반영하여 완화
- 분석 latency 증가 (FRED 호출 N개 추가 → ~5초/호출)
- 데이터 부재(KRW/USD 같은 비공식 시리즈)의 fallback 필요

---

## Issue #4-a — 기존 애널리스트 확장 (minimal)

### Problem
Issue #4 Context 참조. 가장 ROI 높은 시작점.

### Proposed approach
기존 3개 애널리스트에 지표만 추가, 노드 신설 X:
- **macro_quant**: DTWEXBGS USD index, KRWUSD (via Yahoo Finance)
- **market_risk**: MOVE 지수, 원유 term spread (USOIL12-USOIL1), GOLDPMGBD228NLBM (금), 금/은 ratio
- **technical**: 외국인 순매수 추세 (pykrx `get_foreign_inv` API, 5d/20d MA)

### Acceptance criteria
- [ ] macro_quant에 USD index + KRW/USD daily 추가
- [ ] market_risk에 MOVE + 원유 term spread + 금/은 ratio 추가
- [ ] technical에 외국인 순매수 추세 (5d/20d MA) 추가
- [ ] 각 analyst의 `summary_for_downstream`에 새 지표 1줄씩 반영
- [ ] KRW/USD fetch 실패 시 stale-marked sentinel (D5 tier-3 패턴) 적용
- [ ] 5/28 dry-run trace에서 새 지표가 narrative에 등장하는지 확인

### Effort
~150 LOC + 6 새 FRED/Yahoo 시리즈 alias + fetcher. 3~4시간.

---

## Issue #4-b — 신규 애널리스트 추가 (flow + sentiment)

### Problem
#4-a로는 *지표*만 늘어남. 자금 흐름 분석은 별도 노드로 분리해야 narrative 품질 ↑.

Depends on: #4-a (지표 fetcher 인프라 재사용)

### Proposed approach
2개 노드 신설:
- **`flow_analyst`**: 외국인/기관/개인 순매수, 한국 주식형 펀드 흐름
- **`sentiment_analyst`**: AAII bullish/bearish, CBOE Put/Call, KRX 옵션 시장 sentiment

### Acceptance criteria
- [ ] `tradingagents/agents/analysts/flow_analyst.py` 신설 + 그래프 wiring
- [ ] `tradingagents/agents/analysts/sentiment_analyst.py` 신설 + 그래프 wiring
- [ ] 각 analyst의 schema (`FlowReport`, `SentimentReport`) 정의
- [ ] research_debate에서 2개 신규 report를 input으로 받도록 수정
- [ ] 5/28 dry-run에서 두 노드가 trace에 추가됨 확인

### Effort
~200 LOC + 2 새 노드 wiring + research_debate 입력 수정. 4~6시간.

---

## Issue #4-c — Cross-asset 종합 애널리스트

### Problem
#4-a, #4-b로도 cross-asset 시그널(BTC 추세, 금/은 ratio, MOVE/VIX 격차, FX 변동성)을 종합 해석하는 *상위 narrative*는 없음.

Depends on: #4-a

### Proposed approach
- **`cross_asset_analyst`**: BTC 추세, 원유/금 ratio, MOVE/VIX 격차, FX 변동성을 묶어 risk-on/off 종합 narrative 생성

### Acceptance criteria
- [ ] `tradingagents/agents/analysts/cross_asset_analyst.py` 신설
- [ ] `CrossAssetReport` 스키마 정의
- [ ] research_debate가 cross_asset_report를 input으로 받음
- [ ] 5/28 dry-run에서 narrative quality 평가

### Effort
~250 LOC. 6~8시간.

### Risk
4개 cross-asset 신호의 *상관성*이 높을 수 있어 노드 추가의 marginal value 작을 수 있음 — #4-a 결과 보고 진행 여부 재검토.

---

## Issue #5 — research_mapper: β-sharpening 이 24-cell 을 1-cell 로 짓누름

### Problem
`scenario_mapper._compute_conviction_beta` 가 `_BETA_SLOPE=3.0` 으로 sharpening. 2026-05-15 run 에서 p_dom=0.76 → β=2.38 → effective B marginal 0.98 (raw 0.76). 24-cell 디자인의 cross-effect 가 high-conviction 에서 통째로 사라짐. backtest 캘리 근거 없는 magic number.

### Proposed approach
variance n=20 + backtest grid (β_slope ∈ {0,1,2,3}) 측정 후 셋 중 하나:
- A. β=1 고정 (sharpening 제거) — default
- B. backtest 결과로 (slope, threshold) 캘리
- C. Bayesian shrinkage (역방향, low conviction 시 prior 로 끌어당김)

### Acceptance criteria
- [x] variance 측정 결과 인용 + 옵션 선택 근거 commit body 에 명시
- [ ] `_compute_conviction_beta` 변경 후 unit test (옵션별) — C3
- [ ] e2e snapshot 으로 portfolio 영향 검증 — C3

### Measurement result (2026-05-21, n=20, 2026-05-15 fixture)
- dominant_cycle flip rate: **0%** (20/20 모두 B)
- bond weight σ: **0.3pp** ≪ 3pp 임계
- effective B (post β=2.38 sharpening): mean 99.2%, range [96.3%, 100%] — sharpening 이 cross-effect 짓누름
- Summary: `artifacts/2026-05-20/variance/summary.md`
- **C3 옵션: A (β=1 고정)** — `artifacts/2026-05-20/decisions.md` D1

### Effort
~3-4시간 (분석 백그라운드 제외)

### Risk
β 변경이 portfolio 방향을 크게 흔들 수 있음 → C5 산출물 diff 검증 단계로 mitigation.

---

## Issue #6 — D2/D3 baseline σ 가 hand-coded — decontamination 가 placeholder

### Problem
`conditional_stress._BASELINE` 의 (mean, σ) 20개 entry, `kr_residual_signals._BETA_KR_CORP_VS_HY=0.50`, `_ALPHA_KR_CORP=50.0`, `_KR_MARGIN_SIGMA_PCT=8.0` 모두 hand-coded. 코드 주석이 직접 인정: "P1 TODO: 1970-2024 quarterly historical regression 으로 교체". z-score 외관만 있고 통계적 의미 없음 (false precision).

### Proposed approach
- `_BASELINE` 5 metrics × 4 quadrants = 20 entries 를 1970-2024 분기 데이터에서 quadrant-conditional mean/std 로 회귀.
- KR β/α 는 1990-2024 분기 `kr_corp_spread ~ hy_oas` OLS 실측.
- `_KR_MARGIN_SIGMA_PCT` 도 실측 σ.
- `scripts/regress_stage2_baselines.py` 로 reproducibility 보장.

### Acceptance criteria (재정의 — 2026-05-21 data gap 확인 후)
- [ ] (Phase A) US partial regression: BAA10Y/VIXCLS/funding/equity_bond_corr 1990-2024
  분기 quadrant-conditional mean/σ 산출. HY OAS 는 BAA10Y proxy 로 대체 또는
  ICE BofA 대체 source 확보 (예: FRED `BAMLC0A4CBBB` BBB-spread).
- [ ] (Phase B) KR fetcher: ECOS API 로 KR AA-3y corp spread + KR 국고채 3y 분기
  series 확보 (~2003+). `tradingagents/dataflows/ecos.py` 확장.
- [ ] (Phase C) `_BETA_KR_CORP_VS_HY` OLS 실측 (Phase B 완료 후).
- [ ] `scripts/regress_stage2_baselines.py` reproducibility.
- [ ] 2008 Q4 historical event z>+1.0 sanity test (Phase A 후 가능).

### Status (2026-05-21, C4 시점)
**Defer full regression to follow-up PR** (decisions.md D7).
본 PR (Stage 2 mega-PR) 의 C4 scope 는 prompt caching 만 처리.
`_BASELINE` 5×4 + `_BETA_KR_CORP_VS_HY` 는 hand-coded 유지 + 데이터 gap 명시 주석 추가.

근거:
1. HY OAS (BAMLH0A0HYM2) 2023 vintage 변경 — historical 가용 불가 (proxy 별도 결정 필요)
2. KR 분기 corp spread series 별도 ECOS fetcher 필요 (현재 미구현)
3. 1970-2024 quarterly 전체는 새 data infrastructure 작업 — 4-6시간 단순 회귀 아니라 fetcher + reconciliation 포함

### Effort (재추정)
- Phase A (US partial, proxy 결정 포함): ~3-4시간
- Phase B (ECOS KR fetcher): ~2-3시간
- Phase C (OLS + sanity): ~1-2시간
- 총 ~6-9시간 — 별도 PR cycle 필요

### Risk
- HY OAS proxy 선택이 결정적 — BAA10Y (IG) 는 KR 신용 cycle 와 약한 상관, BAMLC0A4CBBB (BBB) 가 더 가까울 가능성. proxy backtest 필요.
- ECOS API rate limit 으로 historical fetch 가 batch 필요.

---

## Issue #7 — research.dominant_scenario 가 B(growth+inflation) 를 stagflation 으로 mis-label

### Problem
`schemas/research.py:201` `if cycle in ("B", "D"): return "stagflation"`. B 는 growth+inflation (overheating, 1972/2021H2), D 는 recession+inflation (real stagflation, 1973-80). 둘을 같은 label 로 묶어 downstream method_picker 가 stagflation defensive (RISK_PARITY) 를 잘못 트리거. 2026-05-15 run: dominant_cycle=B, GDPNow 4.0% 였으나 risk_parity 적용됨. expected_sharpe 0.02 의 직접 원인일 가능성.

### Proposed approach
- `cycle == "D"` → `"stagflation"`
- `cycle == "B"` → `"overheating"` (신규 label)
- method_picker `_SCENARIO_METHOD` 에 `"overheating"` case 추가 (HRP — equity-tilted 분산)

### Acceptance criteria
- [x] 매핑 unit test 7개 (각 cycle × tail 조합)
- [x] method_picker overheating branch test
- [x] 595 기존 unit test pass

### Effort
~30분 (즉시 fix)

### Risk
없음 — 한 줄 production bug fix.

---

## Issue #8 — Stage 2 의 incremental information value 미측정

### Problem
Stage 2 는 macro_quant_analyst 의 regime quadrant 를 cycle marginal 로 거의 1:1 reformat 하는 것에 가까울 가능성. 2026-05-15 run: macro_quant `growth_inflation=0.84` → stage 2 cycle B=0.76. ablation 실험 없이는 stage 2 LLM 호출 ($, latency 243s) 의 ROI 미지수.

### Proposed approach
`scripts/measure_stage2_ablation.py` 로 3-mode 실험:
- `baseline`: 정상 (n=3)
- `no_macro`: macro_summary block 제거 (n=3)
- `perturb_quadrant`: macro 의 regime quadrant swap (n=3)

L1 distance 로 anchoring 정도 정량화. > 90% anchoring 시 stage 2 LLM 호출 자체 제거 평가.

### Acceptance criteria
- [x] 3-mode 실험 결과 artifacts 보관 (`artifacts/2026-05-20/ablation/`)
- [x] anchoring 정도 followup_issues.md 에 인용 (본 section)
- [x] stage 2 input pruning 결정 commit body 명시

### Measurement result (2026-05-21, 3 mode, 2026-05-15 fixture)
- baseline (n=3): cycle B=0.79, dominant_scenario=overheating × 3
- no_macro (n=2): cycle A=0.49, dominant_scenario=goldilocks × 2 (큰 shift)
- perturb_quadrant (combined n=3 from 9 attempts): cycle B=0.47, dominant_scenario=overheating × 3
- L1(baseline, no_macro): **0.995** (≫ 0.15)
- L1(baseline, perturb): **0.727** (> 0.40)
- Anchoring ratio: **0.73** (< 2.0 — 단순 reformat 아님)
- Summary: `artifacts/2026-05-20/ablation/summary.md`
- **C3 input pruning: keep prompt as-is** — decisions.md D5
- Caveat: no_macro/perturb 일부 runs LLM sum-to-1 validator (0.5% tol) 실패. n 작음.

### Effort
~30-40분 wall (백그라운드)

### Risk
LLM 비용 ~$2. anchoring 결과가 모호 (60-90%) 면 입력 그대로 유지.

---

## Issue #9 — Stage 2 LLM noise 의 portfolio 흡수 미측정

### Problem
24-dim simplex sampling 은 LLM categorical sampling 분산이 큰 영역. variance 측정 인프라(`measure_llm_variance.py`) 있으나 실측 결과 미보고. dominant_cycle flip rate, bucket weight σ 모르면 smoothing 처방 필요성 판단 불가. variance 만으로 매주 portfolio 가 흔들리는 turnover 비용은 expected Sharpe 0.02 환경에서 결정적 손실.

### Proposed approach
- `measure_llm_variance.py --n 20` 백그라운드 실행 (~80분 wall).
- 산출 metric: dominant_cycle flip rate, cycle marginal σ, bucket weight σ.
- bond σ > 3pp 또는 fx σ > 3pp 또는 flip > 5% → C3 EMA + hysteresis 의무.

### Acceptance criteria
- [x] variance n=20 결과 artifacts 보관 (`artifacts/2026-05-20/variance/n20_run.json`)
- [x] flip rate, σ followup_issues.md 인용 (Issue #5 section)
- [x] EMA λ 값 선택 근거 commit body 명시

### Measurement result (2026-05-21, n=20)
- Dominant cycle flip rate: **0%** — variance 가 portfolio 에 전혀 전달 안 됨
- bond σ: 0.3pp, fx σ: 0.2pp, kr_equity σ: 0.6pp
- **EMA λ: 1.0 (no smoothing)** — variance 가 0 에 가까워 EMA 가 줄일 noise 없음. magic number 회피. decisions.md D2. infrastructure 만 구축 (λ=1.0 default).
- 후속: 미래 cycle transition 시점 (예: 2027 Q2 추정 inflation peak) 에 variance 재측정 → λ 재평가.

### Effort
~80분 wall (백그라운드) — *실측 ~3분* (LLM 빠름)

### Risk
LLM 비용 ~$1 — *실측 ~$0.5*

---

## Issue #10 — Prompt 의 ~50% 가 고정인데 prompt caching 미사용

### Problem
ESTIMATOR_PROMPT 는 ~10KB. 그 중 framework + 24-cell 정의 + 추정 절차 (~5KB) 가 매 호출 동일. Anthropic API 의 `cache_control` 적용 시 cache hit 시 input cost 90% 절감 + latency 단축. 현재 single `{"role": "user", "content": prompt}` 로 통째 전송.

### Proposed approach
- 고정 부분을 system message 로 분리.
- system message 에 `cache_control: {"type": "ephemeral"}` 적용.
- `invoke_with_structured_retry` 가 system/user 분리 message format 지원하는지 검증, 필요 시 보강.

### Acceptance criteria
- [ ] system/user 분리된 prompt 구조
- [ ] cache_control 마커 mock client 가 받는 messages 에서 검증
- [ ] variance 측정 시 latency 감소 확인

### Effort
~30-60분

### Risk
LLM client wrapper 가 cache_control 미지원 시 wrapper 자체 보강 필요.

---

## Issue #11 — Time-series smoothing 부재 — 매주 portfolio 가 LLM noise 로 흔들림

### Problem
`research_manager.node` 가 stateless. 이전 ResearchDecision 을 prior 로 안 봄. cycle regime 은 slowly-varying latent state 인데 매주 독립 추정 → LLM sampling 으로 dominant_cycle flip 가능 → bond ±15pp, fx ±20pp swing → turnover 비용 (5-15bps round-trip × 회전). expected Sharpe 0.02 환경에서 직접 손실.

### Proposed approach
- state 에 `prior_research_decision` 키 추가, wire 통과.
- EMA blend: `final = λ · new + (1-λ) · prior`. λ 는 variance + ablation 결과로 결정.
- Hysteresis (옵션): dominant_cycle 변경에 +Δ threshold.

### Acceptance criteria
- [ ] state wire 검증 unit test
- [ ] EMA blend (prior None / present) unit test
- [ ] hysteresis (off/on) unit test
- [ ] e2e snapshot 으로 prior 적용 시 portfolio 변동 폭 감소 확인

### Effort
~1-2시간

### Risk
λ 값 정당화 안 되면 magic number. variance 결과 의존.

---

## 우선순위 제안

대회 5/28 일정과 ROI 관점에서:

| 순위 | Issue | 이유 |
|---|---|---|
| 1 | **#2 (allocator visibility)** | 디버깅 가시성 — 다른 issue 작업 효율 ↑. 4시간 ROI 최고. #3의 prerequisite. |
| 2 | **#1 (novelty signal)** | 비용 절감 + 토론 품질. 1~2시간으로 완료 가능. |
| 3 | **#4-a (analyst 지표 확장 minimal)** | narrative 품질 ↑, 본 제출 직전 가치. 3~4시간. |
| 4 | **#3 (risk_debate → stress scenarios)** | philosophy.md "5. 시장 충격 시나리오" 섹션 자동화에 직결. 4~6시간. #2에 의존. |
| 5 | #4-b, #4-c | 시간 남으면 5/28 후 작업. |
| 6 | **#7 (B mis-label)** | 1줄 production bug, downstream 영향 결정적. 즉시 fix. |
| 7 | **#9 + #5 (variance + β)** | 분석 후 처방 핵심. EMA λ, β 옵션 결정. |
| 8 | **#11 (hysteresis)** | #9 측정 결과 의존. turnover 직접 절감. |
| 9 | **#10 (caching)** | 비용/latency 즉시 개선. |
| 10 | **#8 (ablation)** | stage 2 ROI 정량화. |
| 11 | **#6 (baseline 회귀)** | data 의존, 시간 가장 큼. |

---

## Issue #12 — Stage 1 macro_quant 에 KR FX skill 추가 (factor model F6 Gap E+F)

### Problem
factor model 의 F6 krw_regime 가 KRW/USD level + REER 필요. 현재 Stage 2 의
`external_fetchers.py` 가 yfinance 임시 fetch. Stage 1 fetch + cache 가 더 적절.

### Proposed approach
- macro_quant 의 sub_skill: kr_fx (KRW/USD level via yfinance KRW=X, REER via BIS monthly)
- MacroReport schema 에 `kr_fx: KRFXSnapshot` 필드 추가
- factor_estimators.py 의 F6 가 `stage1.macro_report.kr_fx.*` 으로 source 변경 (external_fetcher 제거)

### Effort
~4-6시간

### Dependencies
None (Stage 1 작업)

### Priority
High — factor F6 의 *current level* 가 *2026-05 reliability medium-high*. fetch 의 임시 성격
이 production 운영 시 reliability risk.

---

## Issue #13 — Stage 1 macro_quant 에 LEI + ISM sub-components 추가 (factor model F1 Gap A+B)

### Problem
factor F1 growth_surprise 의 LEI 6m change + ISM PMI sub-components (new orders, employment,
prices) component weight 가 PR1 에서 *0* (data 부재). F1 의 reliability ↓.

### Proposed approach
- macro_quant 에 LEI fetch (FRED 의 USSLIND 또는 CB LEI)
- ISM PMI sub-components fetch (Bloomberg/FRED)
- MacroReport.growth schema 확장
- factor_baselines.py 에 baseline 추가
- factor_estimators.py 의 F1 weights 재조정 (현재 sum=0.85 → 1.0)

### Effort
~3-4시간

### Priority
Medium

---

## Issue #14 — Stage 1 macro_quant 에 r-star (HLW) + ACM/KW term premium 추가 (factor model F3+F4 Gap C+D)

### Problem
factor F3 의 r-star, F4 의 ACM/Kim-Wright term premium model 모두 부재. F3 의 single-component
의존, F4 의 slope-only (post-COVID de-anchored issue) 가 reliability risk.

### Proposed approach
- HLW r-star fetch (NY Fed quarterly publish)
- Kim-Wright term premium (Fed published) — ACM 의 2024 review 대신
- MacroReport.fed_path 에 r_star 추가, yield_curve 에 term_premium_kim_wright 추가
- factor_baselines.py + factor_estimators.py 의 F3/F4 weights 재조정

### Effort
~5-7시간

### Priority
Medium-high — F4 의 post-COVID de-anchored issue 직접 mitigation.

---

## Issue #15 — Stage 1 market_risk 에 valuation skill 추가 (factor model F8 Gap G)

### Problem
factor F8 valuation 의 forward P/E, ERP component 모두 Stage 2 의 external_fetchers (yfinance
trailing P/E proxy). forward P/E 가 더 적절 (Bloomberg / Refinitiv 필요).

### Proposed approach
- market_risk 에 sub_skill: equity_valuation (forward P/E via yfinance + earnings revision)
- RiskReport.equity_valuation schema 추가
- factor_estimators.py 의 F8 source 변경

### Effort
~3-5시간

### Priority
Medium — F8 가 *2026 reliability medium* (AI environment noise). 정확도 향상 marginal.

---

## Issue #16 — Stage 1 market_risk 에 cross-currency basis 추가 (factor model F9 Gap H)

### Problem
factor F9 liquidity_regime 의 cross-currency basis component 부재 (현재 weight=0).
funding liquidity 의 *forward signal* 누락.

### Proposed approach
- market_risk 에 cross_currency_basis fetch (Bloomberg / DTCC public data)
- RiskReport.funding_stress 에 cross_currency_basis 추가
- factor_estimators.py 의 F9 weight 재조정

### Effort
~2-3시간

### Priority
Low — F9 의 다른 components (VRP, dispersion) 가 이미 작동.

---

## Issue #17 — external_fetchers.py 의 임시 fetch 를 Stage 1 으로 migrate (cleanup)

### Problem
PR `feat/stage2-factor-model` 가 `tradingagents/skills/research/external_fetchers.py` 신설:
- `fetch_krw_usd_level()` via yfinance (KRW/USD)
- `fetch_sp_trailing_pe()` via yfinance (S&P trailing P/E)

본 모듈은 *Stage 2 의 layering 위반* (Stage 2 가 external API 직접 호출).

### Proposed approach
Issue #12 (KR FX), #15 (valuation) 완료 후:
- factor_estimators.py 의 F6/F8 source 가 Stage 1 의 macro_quant/market_risk struct
- `external_fetchers.py` 자체 삭제
- 해당 test 도 삭제

### Effort
~1시간 (cleanup only — 의존성 작업 완료 후)

### Dependencies
Blocked by Issue #12 + #15

### Priority
Medium (cleanup) — production 운영 전 권장.

---

## Issue #18 — factor model β 의 real historical fetch + production calibration

### Status (PR2a 완료, 2026-05-24) — **RESOLVED**

PR2a 의 walk-forward calibration acceptance gate PASS. INITIAL_BETA 가
data-driven 으로 교체됨 (commit C9, 2d81a7b).

- Improvement Δ: **+0.342 OOS Sharpe** (prior 0.829 → calibrated 1.171, +41%)
- Paired-t p: 0.080 (< 0.20 threshold)
- 5/5 acceptance conditions PASS (sign tolerance 1e-3, grill-me #3 결정)
- Best shrinkage: 2.0

산출물:
- backtest/historical/samples.parquet: 133Q × 23 col (1991-Q2 ~ 2024-Q2)
- artifacts/2026-05-24/calibration_runs/validation_report.json
- tradingagents/skills/research/factor_to_bucket.py: INITIAL_BETA = 45
  data-driven entries.

다음 단계: PR2b 의 benchmark 비교 (24-cell / 60-40 / 1-N / risk parity) +
empirical superiority 통계 검증 + 2026-05-15 산출물 regen.

### (Historical) Problem
PR1 의 C6 calibration 은 *synthetic data* 으로 infrastructure 검증만. real INITIAL_BETA
update 가 *Stage 1 real fetch + walk-forward Sharpe* 필요.

### (Historical) Proposed approach
1. Historical fetch script:
   - FRED quarterly (1991-2024): CPI, GDP, NFCI, CFNAI, yield curve, TIPS, fed funds
   - yfinance quarterly: S&P 500, KOSPI, IEF, DJP, ^IRX
   - pykrx quarterly: 외국인 순매수, KRW REER (BIS monthly aggregated)
2. `factor_calibration.load_historical_data()` 의 *synthetic fallback* 제거 → real fetch
3. `scripts/calibrate_factor_model.py --shrinkage-grid` 재실행
4. validation_report 확인 — acceptance criteria PASS 시 INITIAL_BETA 교체
5. Acceptance 미통과 시 design 재검토 (factor weights, sample window, etc.)

---

## Issue #19 — factor reliability audit 6m 재검증 (AUDIT_DATE update)

### Problem
factor_reliability_audit.py 의 COMPONENT_RELIABILITY 가 *시점 의존*. 6m 마다 재검증 권장
(test 가 강제 fail trigger).

### Proposed approach
- 매 6개월:
  - Sahm rule, yield curve, SKEW level, valuation 의 *2026 의 weakening 가 여전한지* 검토
  - 새로 weakening 된 indicator 식별 (예: VIX 의 post-2024 새 patterns)
  - AUDIT_DATE update, COMPONENT_RELIABILITY 갱신
  - test_factor_indicator_validity.py 의 EXPECTED_COMPONENTS 도 update

### Effort
~2-3시간 per cycle

### Priority
Recurring (low/medium)

---

## Issue #13 — Stage 1 macro_quant 에 LEI + ISM sub-components 추가 (F1 Gap A+B)

### Status (2026-05-24, PR `feat/stage1-enhance-for-factor-model`)
- **PARTIAL RESOLVED**: CFNAI 추가 (C3) — LEI + ISM sub-components 는 *별도 후속 PR*
- Factor F1 coverage: ~40% → ~95% (path fix + CFNAI)

---

## Issue #15 — Stage 1 market_risk 에 valuation skill 추가 (F8 Gap G)

### Status (2026-05-24)
- **PARTIAL RESOLVED**: KOSPI PBR/PER/DivYield 추가 (C5) — pykrx 기반
- Forward P/E (S&P 500) 는 여전히 external_fetcher 의존 — Issue #17 cleanup 대기
- Factor F8 coverage: ~30% → ~85% (path fix + kospi_pbr; production 환경 의존)
- **Known issue (#21)**: pykrx KOSPI200 API mismatch — Linux/Mac OS 검증 필요

---

## Issue #16 — Stage 1 market_risk 에 cross-currency basis 추가 (F9 Gap H)

### Status (2026-05-24)
- **UNCHANGED**: Tier 3 priority. PR1 Stage 1 enhance 의 scope 외.

---

## Issue #20 — Windows path encoding 의 yfinance/curl_cffi SSL 호환성

### Problem
Windows 한글 path (e.g., `C:\Users\parkj\OneDrive\바탕 화면\...`) 에서 curl_cffi 가
hardcoded `certifi/cacert.pem` path 를 corruption (`���� ȭ��`) — yfinance fetch SSL fail.

영향:
- F7 realized_vol_60d (SPY history)
- F8 forward P/E (SPY .info — 단 external_fetcher 가 처리)
- F9 sector_dispersion (11 SPDR ETF history)
- C10 의 production 환경에서 *5/6 신규 component degraded*

### Proposed approach
- Env var (REQUESTS_CA_BUNDLE 또는 SSL_CERT_FILE) 설정
- 또는 curl_cffi 의 cacert path workaround (절대 경로 explicit)
- Linux/CI 환경 (Docker, GitHub Actions) 에서 verify

### Effort
~2-4h

### Priority
High — production deploy 전 필수.

---

## Issue #21 — pykrx KOSPI200 API mismatch

### Problem
C5 의 `stock.get_market_fundamental(date_str, market="KOSPI200")` 가 *KeyError 'KOSPI200'*.
pykrx 의 *최신 API* 에서 market parameter 의 valid values 가 변경되었거나 fundamental
endpoint 의 KOSPI200 지원 변경 가능성.

### Proposed approach
- pykrx 의 *현행 API* 확인 (예: `market="KOSPI"` vs `"KOSPI200"`)
- 필요 시 KOSPI200 constituent ticker list 수동 fetch 후 average
- pykrx version pin 또는 alternative source 검토 (KRX 직접 API)

### Effort
~2-3h

### Priority
High — F8 valuation 의 kospi_pbr component degraded.

---

## Issue #22 — F6 foreign_flow_z baseline sd 재교정

### Problem
C8 의 D11a 결정에서 `("F6_krw_regime", "foreign_flow_z")` baseline = (0, 1e12) 설정 —
hand-coded 의 *추정 sd*. C10 production 에서 *floor clamp* (z = -3.00) 발생 — sd 가 *너무 작음* (raw KRW 가 sd 보다 큼).

### Proposed approach
- net_20d_krw 의 *historical empirical sd* 측정 (1991-2024 분기 또는 월 단위)
- baseline (mean, sd) 재교정 (예상: sd ~5e12 또는 1e13)
- 또는 F6 foreign_flow_z component drop (Q2 의 옵션 C 였음 — A 선택했으므로 backlog)

### Effort
~3-5h

### Priority
High — F6 의 dominant driver 가 floor clamp 면 *systematic bias*.

---

## Issue #23 — 5/6 신규 component 의 Linux/CI 환경 verify

### Problem
C10 의 production replay 결과:
- 실제 신호 변화 = 4개만 (CFNAI + slope_5_30y + F6 baseline + F3 real_rate path)
- KOSPI PBR, realized_vol, sector_dispersion, skew change_1m_z 모두 *Windows 환경 한계* 로 sentinel
- *5/6 신규 component 가 Linux/CI 환경 에서 정상 작동* 여부 검증 안 됨

### Proposed approach
- Linux Docker container 에서 C10 replay 재실행
- 모든 6 신규 component 의 *real signal* 확인
- 차이 가 있으면 sed environment fix (Issue #20, #21 dependent)

### Effort
~2-3h (Docker setup + replay)

### Priority
High — production environment verify gate.
