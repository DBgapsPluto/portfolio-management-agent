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

## 우선순위 제안

대회 5/28 일정과 ROI 관점에서:

| 순위 | Issue | 이유 |
|---|---|---|
| 1 | **#2 (allocator visibility)** | 디버깅 가시성 — 다른 issue 작업 효율 ↑. 4시간 ROI 최고. #3의 prerequisite. |
| 2 | **#1 (novelty signal)** | 비용 절감 + 토론 품질. 1~2시간으로 완료 가능. |
| 3 | **#4-a (analyst 지표 확장 minimal)** | narrative 품질 ↑, 본 제출 직전 가치. 3~4시간. |
| 4 | **#3 (risk_debate → stress scenarios)** | philosophy.md "5. 시장 충격 시나리오" 섹션 자동화에 직결. 4~6시간. #2에 의존. |
| 5 | #4-b, #4-c | 시간 남으면 5/28 후 작업. |
