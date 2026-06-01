# Tier 3 — LLM Bucket Overlay (Additive, Dynamic-weighted)

- **작성일:** 2026-05-28
- **대상:** Stage 2 후처리 / Stage 4 overlay 구현자
- **선행 의존:** [Tier 0](./2026-05-28-tier0-factor-model-reform-design.md) (12 factor), [Tier 1](./2026-05-28-tier1-bucket-taxonomy-design.md) (8 bucket), [Tier 2](./2026-05-28-tier2-calibration-design.md) (calibrated β)
- **외부 참조:** TrustTrade (Selective Consensus, Reflective Memory), Man Group "LLM 과대-extrapolation bias" 연구

---

## 0. TL;DR

Stage 2 factor model의 bucket allocation은 **quant-only**. Tier 3는 *additive overlay*로 LLM의 정성적 macro/news 신호를 8-bucket directional view로 추가. Multi-sample consensus (K=5) + dynamic weighting (`novelty × consensus × credibility`) + bounded deviation (BAND=±5pp) + EWMA credibility 학습.

**Flow:**
```
factor model output (8-bucket quant) 
  → LLM K=5 sample (LLMBucketView)
  → compute (novelty, consensus, credibility)
  → blend: target_b = quant_b + clip(w_LLM × Δ_b, ±BAND)
  → project_to_mandate_qp (mandate cap 0.70 재적용)
```

**Cold-start:** credibility prior 0.3 → α=0.1 EWMA update from realized hit rate.
**Architectural:** factor model 대체 X, *추가 overlay*. PR2a/Tier 2 calibrated β는 quant baseline 유지.

---

## 1. Architecture

```
Stage 1 (data) → Stage 2 (factor model) → Tier 3 LLM overlay → Stage 3 (selector) → Stage 4 (risk overlay)
                       ↓                          ↓
                  quant β output          additive directional Δ
                  (8 bucket weights)         (8 bucket deltas)
                       └──────────────┬───────┘
                                      ↓
                              blend & re-project
                                      ↓
                             final bucket target
```

**핵심 원칙:**
- LLM은 *factor model을 대체하지 않음*. Factor가 capture 못하는 *qualitative macro/event signal* (예: 정책 surprise, geopolitical breaking news)을 *additive*로 추가.
- BAND = ±5pp 제약으로 *blast radius* 제한. cred=0.3 cold-start로 *대회 초기* LLM 영향 minimal.
- Backtest validation 어려움 (LLM은 historical replay 불가) → forward-tuning이 본질적 제약.

---

## 2. LLM Bucket View 생성 (K=5 multi-sample)

### 2.1. Schema — `LLMBucketView`

`tradingagents/schemas/llm_overlay.py` (NEW):

```python
from typing import Literal
from pydantic import BaseModel, Field

BucketDirection = Literal["increase", "neutral", "decrease"]

class LLMBucketView(BaseModel):
    """Single LLM forward output — directional bucket view."""
    
    # Per-bucket directional delta in [-1, +1] (scale-invariant)
    kr_equity: float = Field(ge=-1.0, le=1.0, description="+1 = max increase, -1 = max decrease")
    global_equity: float = Field(ge=-1.0, le=1.0)
    precious_metals: float = Field(ge=-1.0, le=1.0)
    cyclical_commodity_fx: float = Field(ge=-1.0, le=1.0)
    kr_bond: float = Field(ge=-1.0, le=1.0)
    credit: float = Field(ge=-1.0, le=1.0)
    global_duration: float = Field(ge=-1.0, le=1.0)
    cash_mmf: float = Field(ge=-1.0, le=1.0)
    
    # LLM's self-reported confidence (independent of consensus)
    confidence: float = Field(ge=0.0, le=1.0, description="LLM's self-rated confidence")
    
    # Reasoning (audit trail)
    reasoning: str = Field(max_length=500, description="LLM rationale, max 500 chars")
    
    # Source citations (from Stage 1 news_report) - prevents hallucination
    cited_events: list[str] = Field(default_factory=list, max_length=5)
    
    def to_delta_dict(self) -> dict[str, float]:
        """Return {bucket: delta} dict."""
        return {
            "kr_equity": self.kr_equity,
            "global_equity": self.global_equity,
            "precious_metals": self.precious_metals,
            "cyclical_commodity_fx": self.cyclical_commodity_fx,
            "kr_bond": self.kr_bond,
            "credit": self.credit,
            "global_duration": self.global_duration,
            "cash_mmf": self.cash_mmf,
        }
```

### 2.2. LLM 입력 구조

LLM은 **4가지 종류의 입력**을 받음:

1. **Stage 1 4개 analyst report의 narrative summary 결합** — 모든 macro/risk/technical/news 정성 신호
2. **12 factor z-scores** (Stage 2 factor model 출력) — quant가 현재 *어떤 신호를 보고 있는지*
3. **Stage 2 quant bucket target** (8 bucket weights, factor model 최종 출력) — quant의 *결과*
4. **Stage 2 audit diagnostics** (선택) — cap_hits, projection_intervened, extreme_factor_active

#### 2.2.1. Stage 1 analyst summary 결합

**Pluto state class 실측 (A13 ambiguity 해소):** `tradingagents/agents/utils/agent_states.py`의 `AgentState(MessagesState)`. 다음 fields 보유:

```python
class AgentState(MessagesState):
    # Stage 1 Pydantic structured outputs
    macro_report: Optional[MacroReport]
    risk_report: Optional[RiskReport]
    technical_report: Optional[TechnicalReport]
    news_report: Optional[NewsReport]
    
    # === LLM-ready markdown summaries (≤2KB each) ===
    # D2 hybrid topology — downstream stages 가 raw schema 대신 받음
    macro_summary: str
    risk_summary: str
    technical_summary: str
    news_summary: str
    
    # Stage 2 outputs
    research_decision: Optional[ResearchDecision]
    bucket_target: Optional[BucketTarget]
    ...
```

**즉 Tier 3 LLM 입력은 state 안 *_summary fields 직접 사용** — *_AnalystReport.summary_for_downstream* 별도 추출 불필요.

| Report | AgentState field | 내용 |
|---|---|---|
| MacroReport | `state.macro_summary` (≤2KB markdown) | GDP/CPI/Fed/KRW/China 거시 정성 view |
| RiskReport | `state.risk_summary` | VIX/MOVE/credit/breadth/real_vol 시장 위험 |
| TechnicalReport | `state.technical_summary` | Asset momentum, ETF ranking |
| NewsReport | `state.news_summary` | Calendar/sentiment/cb_speakers/geopolitical |

**결합 logic:**

```python
def _build_analyst_context(state: AgentState) -> str:
    """Stage 1의 4개 analyst summary 결합 (≤8KB total, ~2000 tokens).
    
    AgentState의 *_summary fields는 이미 markdown ≤2KB, LLM-ready.
    """
    sections = []
    if state.get("macro_summary"):
        sections.append(f"## Macro (macro_quant_analyst)\n{state['macro_summary']}")
    if state.get("risk_summary"):
        sections.append(f"## Market Risk (market_risk_analyst)\n{state['risk_summary']}")
    if state.get("technical_summary"):
        sections.append(f"## Technical (technical_analyst)\n{state['technical_summary']}")
    if state.get("news_summary"):
        sections.append(f"## News (macro_news_analyst)\n{state['news_summary']}")
    return "\n\n".join(sections)
```

> **주의:** AgentState는 `langgraph.MessagesState` subclass (TypedDict-style). attribute 접근은 `state["macro_summary"]` 또는 `state.get("macro_summary")` 형식. `state.macro_summary` 같은 dot-access는 작동 안 함.

> **주의:** Stage 1 News agent가 수정 중 (다른 구현자) — 수정 후 NewsReport schema 변경 가능성 있음. 변경된 schema 따라 본 결합 logic 재검토 필요.

#### 2.2.2. Factor z-scores 12개

```python
def _build_factor_context(factor_scores: FactorScores) -> str:
    """12 factor z-scores + interpretation.
    
    LLM 이 quant가 *어떤 macro signal*을 보고 있는지 이해 → 
    자신의 view를 quant signal과 *연결* 또는 *분리* 해석 가능.
    """
    z_dict = factor_scores.to_dict()  # {F1_growth: +1.2, ..., F12: -0.3}
    lines = []
    for factor, z in z_dict.items():
        # _interpretation 헬퍼: |z|<0.25 neutral, <1 modest, <2 strong, ≥2 extreme
        interp = _interpretation_text(factor, z)
        lines.append(f"  {factor}: z={z:+.2f}  ({interp})")
    return "Factor z-scores (Stage 2 factor model):\n" + "\n".join(lines)
```

#### 2.2.3. (선택) Stage 2 audit diagnostics

```python
def _build_audit_context(safety_diag: dict) -> str:
    """Stage 2 factor model의 *한계* signal — LLM에게 transparency.
    
    cap_hits: single factor×bucket이 ±10pp cap에 saturate한 경우 → 
              quant model이 그 신호를 *완전히 표현 못 하고 있음*
    projection_intervened: mandate constraint (위험 70% cap) 활성화 → 
              quant가 위험 자산을 더 가지고 싶었지만 mandate에 막힘
    extreme_factor_active: |z|≥2.5 factor 존재 → tail event 가능성
    """
    cap_hits = safety_diag.get("cap_hits", 0)
    intervened = safety_diag.get("projection_intervened", False)
    extreme = safety_diag.get("extreme_factor_active", False)
    
    notes = []
    if cap_hits > 0:
        notes.append(f"⚠️  {cap_hits} factor×bucket cells saturated at cap")
    if intervened:
        notes.append("⚠️  Mandate constraint actively binding (위험자산 70% cap)")
    if extreme:
        notes.append("⚠️  Extreme factor z (|z|≥2.5) detected — tail regime")
    return "Quant model limits:\n" + "\n".join(notes) if notes else ""
```

### 2.3. LLM 프롬프트

```python
SYSTEM_PROMPT = """You are a senior macroeconomic strategist for a KRW-denominated 
multi-asset portfolio. Output a directional view on 8 bucket allocations.

Output STRICT JSON conforming to LLMBucketView schema. Per-bucket delta ∈ [-1, +1].
- +1 = strongly increase from quant baseline
- 0  = no view (neutral)
- -1 = strongly decrease from quant baseline

Rules:
1. NO arithmetic — output directional view only, not specific weights
2. CITE sources from provided analyst narratives (cited_events field)
3. Confidence reflects YOUR uncertainty, not market volatility
4. Reasoning must be in 500 chars max, KR or EN
5. Your view should ADD value beyond quant — focus on what quant z-scores might miss:
   - Breaking events / policy surprises (recent news)
   - Regime shifts (correlation breakdown, structural shifts)
   - Qualitative signals (central bank tone, geopolitical narrative)

Buckets:
- kr_equity (KR 주식)
- global_equity (글로벌 주식)
- precious_metals (금/은)
- cyclical_commodity_fx (원유/구리/곡물/달러)
- kr_bond (한국 국채)
- credit (회사채/하이일드)
- global_duration (미국 장기국채)
- cash_mmf (단기 현금성)
"""

USER_PROMPT_TEMPLATE = """=== Stage 1 Analyst Reports ===

{analyst_context}

=== Stage 2 Factor Model Signals ===

{factor_context}

{audit_context}

=== Stage 2 Quant Bucket Target ===

{quant_target_json}

=== Task ===

Review the analyst narratives and factor signals above. Identify:
1. Macro/news signals that quant z-scores might be UNDER-weighting
2. Regime characteristics that linear factor model might miss
3. Tail risks or asymmetric scenarios not captured by mean-variance logic

Then output your directional view as LLMBucketView JSON.
"""


def build_user_prompt(
    state: PipelineState,
    factor_scores: FactorScores,
    quant_target: dict[str, float],
    safety_diag: dict | None = None,
) -> str:
    return USER_PROMPT_TEMPLATE.format(
        analyst_context=_build_analyst_context(state),
        factor_context=_build_factor_context(factor_scores),
        audit_context=_build_audit_context(safety_diag) if safety_diag else "",
        quant_target_json=json.dumps(quant_target, indent=2),
    )
```

### 2.4. K=5 sampling

```python
async def generate_llm_views(
    state: PipelineState,                # 4개 analyst report (macro/risk/technical/news) 포함
    factor_scores: FactorScores,         # 12 factor z-scores
    quant_target: dict[str, float],      # 8 bucket weights (Stage 2 final)
    safety_diag: dict | None = None,     # Stage 2 audit (선택)
    k: int = 5,
    temperature: float = 0.7,
) -> list[LLMBucketView]:
    """K samples from same prompt (independent stochastic forward).
    
    K=5 (Tier 3 default): consensus estimation 충분, latency ~30s.
    Temperature 0.7: 자연스러운 diversity, deterministic 회피.
    
    Input dim:
      - 4 analyst summary_for_downstream: 4 × ~1000 char ≈ 1000 tokens
      - 12 factor z-scores + interpretations: ~200 tokens
      - quant_target JSON: ~100 tokens
      - audit diagnostics: ~50 tokens (optional)
      - SYSTEM_PROMPT: ~300 tokens
    Total per call: ~1700 tokens prompt. K=5 → ~8500 input tokens / rebalance.
    """
    user_prompt = build_user_prompt(
        state=state,
        factor_scores=factor_scores,
        quant_target=quant_target,
        safety_diag=safety_diag,
    )
    
    views = []
    for _ in range(k):
        response = await llm_client.complete(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            response_schema=LLMBucketView,
            temperature=temperature,
        )
        views.append(response)
    
    return views
```

**LLM client:** 기존 `tradingagents/llm_clients/` 모듈 재사용 (OpenAI/Anthropic/Gemini multi-provider 지원).

---

## 3. Novelty 계산 + salience persistence

`tradingagents/skills/overlay/novelty.py` (NEW):

### 3.1. Persistence (A12 ambiguity 해소)

**파일:** `data/llm_overlay/salience_history.parquet` (daily append-only).

```python
SALIENCE_HISTORY_PATH: Final[Path] = Path("data/llm_overlay/salience_history.parquet")


def append_daily_salience(news_report: NewsReport, run_date: date) -> None:
    """Stage 1 후처리 시 매일 salience score 1개 row 추가.
    
    Schema: {date: date, salience: float}
    Idempotent: 같은 date 중복 append 안 함.
    """
    salience = _compute_today_salience(news_report)
    row = pd.DataFrame({"date": [run_date], "salience": [salience]})
    if SALIENCE_HISTORY_PATH.exists():
        existing = pd.read_parquet(SALIENCE_HISTORY_PATH)
        if run_date in existing["date"].values:
            return  # already recorded
        combined = pd.concat([existing, row], ignore_index=True).sort_values("date")
    else:
        SALIENCE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        combined = row
    combined.to_parquet(SALIENCE_HISTORY_PATH, index=False)


def load_salience_history(as_of: date, window_days: int = 60) -> pd.Series:
    """Load trailing N-day salience history before as_of date."""
    if not SALIENCE_HISTORY_PATH.exists():
        return pd.Series(dtype=float)
    df = pd.read_parquet(SALIENCE_HISTORY_PATH)
    cutoff = as_of - timedelta(days=window_days)
    df = df[(df["date"] >= cutoff) & (df["date"] < as_of)]
    return df.set_index("date")["salience"]
```

### 3.2. Novelty score

```python
def compute_novelty(news_report: NewsReport, as_of: date, window_days: int = 60) -> float:
    """News salience anomaly score, ∈ [0, 1].
    
    novelty = clip(z(today_salience) / 3.0, 0, 1)
    
    Today salience = log(1 + high_impact_event_count) + |avg_sentiment_macro|.
    Historical: trailing window_days from salience_history.parquet.
    
    Returns:
        0 = no novelty (boring day, factor 신호로 충분)
        1 = extreme novelty (z >= 3, exceptional event)
    """
    today_salience = _compute_today_salience(news_report)
    historical = load_salience_history(as_of, window_days)
    
    if len(historical) < 10:
        return 0.0  # insufficient history (대회 첫 10일)
    
    mu = float(historical.mean())
    sd = float(historical.std(ddof=1)) or 1e-9
    z = (today_salience - mu) / sd
    return float(np.clip(z / 3.0, 0.0, 1.0))


def _compute_today_salience(news_report: NewsReport) -> float:
    """Salience = log(1 + high_impact_event_count) + |avg_sentiment|."""
    high_imp = float(_safe_get(news_report, "release_surprise", "high_importance_today") or 0)
    sent_mag = abs(float(_safe_get(news_report, "news_sentiment", "avg_sentiment", "macro") or 0.0))
    return np.log1p(high_imp) + sent_mag
```

**Backtest compatibility:** 
- Backtest mode에서 news_report 없으면 → `today_salience = 0`, `novelty = 0` (LLM signal off)
- Forward (live) mode: 매일 Stage 1 종료 시 `append_daily_salience()` 호출
- 대회 첫 10일은 historical 부족 → novelty = 0 (LLM 영향 자동 minimal)

---

## 4. Consensus 계산

`tradingagents/skills/overlay/consensus.py` (NEW):

```python
def compute_consensus(views: list[LLMBucketView]) -> dict[str, float]:
    """Per-bucket consensus score, ∈ [0, 1].
    
    consensus_b = |sum(sign(view_i[b]))| / K
    
    K=5 sample 중 same-sign 비율 측정.
    All same direction → consensus = 1.0
    Split 2-3 또는 mostly neutral → consensus = 0.2-0.6
    Equally split → consensus = 0.0
    
    Returns: {bucket: consensus_score}
    """
    consensus = {}
    for bucket in BUCKETS:
        signs = [np.sign(getattr(v, bucket)) for v in views]
        # Treat |sign| < 0.1 as neutral (0)
        signs = [s if abs(s) >= 0.1 else 0 for s in signs]
        if all(s == 0 for s in signs):
            consensus[bucket] = 0.0
        else:
            consensus[bucket] = abs(sum(signs)) / len(signs)
    return consensus
```

**해석:**
- consensus=1.0: 5 sample 모두 같은 방향 (high signal)
- consensus=0.6: 3-2 split (medium signal)
- consensus=0.2: 1-4 split (noisy)
- consensus=0.0: all neutral (no LLM signal)

---

## 5. Credibility EWMA 학습

`tradingagents/skills/overlay/credibility.py` (NEW):

```python
@dataclass
class CredibilityState:
    """Per-bucket LLM credibility (EWMA running estimate).
    
    Persisted to disk between sessions.
    """
    bucket_cred: dict[str, float]  # {bucket: cred ∈ [0, 1]}
    history_count: int             # total updates
    last_updated: date


COLD_START_PRIOR: Final[float] = 0.3  # 대회 시작 시 모든 bucket cred=0.3
EWMA_ALPHA: Final[float] = 0.1        # learning rate


def update_credibility(
    state: CredibilityState,
    bucket: str,
    predicted_delta: float,    # LLM blended delta (signed)
    realized_return: float,    # realized bucket return next period
) -> None:
    """EWMA update with hit/miss signal.
    
    Hit: sign(predicted_delta) == sign(realized_return) → +1
    Miss: otherwise → 0
    
    cred_new = (1 - α) * cred_old + α * hit
    
    State persisted: writes to `data/llm_overlay/credibility.json` after each update.
    """
    if abs(predicted_delta) < 0.005 or abs(realized_return) < 0.005:
        # Too small to evaluate (noise)
        return
    
    hit = 1.0 if predicted_delta * realized_return > 0 else 0.0
    current = state.bucket_cred.get(bucket, COLD_START_PRIOR)
    state.bucket_cred[bucket] = (1 - EWMA_ALPHA) * current + EWMA_ALPHA * hit
    state.history_count += 1
    state.last_updated = date.today()
    _persist_credibility(state)


def get_credibility(state: CredibilityState, bucket: str) -> float:
    """Get current credibility, falling back to cold-start prior."""
    return state.bucket_cred.get(bucket, COLD_START_PRIOR)
```

**Persistence:** `data/llm_overlay/credibility.json`. 대회 시작 시 8개 bucket 모두 0.3.

**Convergence:**
- α=0.1 → effective horizon ~10 observations
- 대회 3개월 × 주 1회 rebalance = ~12 update / bucket
- 충분히 학습은 안 되지만 *prior에서 약간 이동* 정도

---

## 6. Additive Blending

`tradingagents/skills/overlay/apply.py` (NEW):

```python
BAND: Final[float] = 0.05  # ±5pp blast radius per bucket


def apply_llm_overlay(
    quant_target: dict[str, float],          # Stage 2 factor model output
    views: list[LLMBucketView],              # K=5 samples
    novelty: float,                          # ∈ [0, 1]
    consensus: dict[str, float],             # per-bucket ∈ [0, 1]
    credibility: CredibilityState,           # EWMA state
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Blend quant + LLM directional view, then re-project to mandate.
    
    Per-bucket weight:
        w_LLM(b) = novelty × consensus[b] × credibility[b]
    
    Blended delta:
        Δ_b = mean(view.delta[b]) × confidence_avg
    
    Final delta (clipped):
        actual_delta[b] = clip(w_LLM(b) × Δ_b, -BAND, +BAND)
    
    Blended target:
        blended[b] = quant_target[b] + actual_delta[b]
    
    Final (mandate-compliant):
        target = project_to_mandate_qp(normalize(blended))
    
    Returns:
        - final_target: dict[bucket, weight]
        - audit: per-bucket breakdown (quant, llm_delta, w_LLM, clipped_delta)
    """
    avg_delta = _aggregate_views(views)  # per-bucket mean × avg confidence
    
    audit: dict[str, dict[str, float]] = {}
    blended = dict(quant_target)
    
    for bucket in BUCKETS:
        w = novelty * consensus.get(bucket, 0.0) * get_credibility(credibility, bucket)
        raw_delta = w * avg_delta.get(bucket, 0.0)
        clipped = float(np.clip(raw_delta, -BAND, +BAND))
        
        blended[bucket] = quant_target[bucket] + clipped
        audit[bucket] = {
            "quant": quant_target[bucket],
            "llm_avg_delta": avg_delta.get(bucket, 0.0),
            "w_LLM": w,
            "clipped_delta": clipped,
            "blended": blended[bucket],
        }
    
    # B6 fix: normalize step 제거. project_to_mandate_qp 가 sum=1 + cap + non-negativity 모두 처리.
    # QP는 L2-projection이라 negative blended weight를 0으로 clip하면서 sum=1로 재조정.
    final_target = project_to_mandate_qp(blended)
    
    # Sanity: degenerate input handling
    if all(abs(v - quant_target[b]) < 1e-9 for b, v in final_target.items()):
        # No LLM effect — return quant (defensive)
        return quant_target, audit
    
    return final_target, audit


def _aggregate_views(views: list[LLMBucketView]) -> dict[str, float]:
    """Per-bucket mean delta × average confidence."""
    avg_conf = np.mean([v.confidence for v in views]) if views else 0.0
    result = {}
    for bucket in BUCKETS:
        deltas = [getattr(v, bucket) for v in views]
        result[bucket] = float(np.mean(deltas)) * avg_conf
    return result
```

---

## 7. Integration with Stage 2 Pipeline

### 7.1. 호출 위치

`tradingagents/agents/managers/research_manager.py` 또는 별도 overlay agent:

```python
# Stage 2 factor model output
factor_scores = compute_all_factors(state, mode="production")
bucket, tips_share, contributions, safety_diag = apply_factor_model_with_safety(
    factor_scores.to_dict()
)

# Tier 3 LLM overlay (if enabled and conditions met)
if config.get("tier3_llm_overlay_enabled", False):
    views = await generate_llm_views(
        state=state,                  # 4 analyst reports
        factor_scores=factor_scores,  # 12 z-scores
        quant_target=bucket,          # 8 bucket weights
        safety_diag=safety_diag,      # Stage 2 audit
        k=5,
    )
    novelty = compute_novelty(state.news_report, historical_salience)
    consensus = compute_consensus(views)
    
    final_bucket, audit = apply_llm_overlay(
        quant_target=bucket,
        views=views,
        novelty=novelty,
        consensus=consensus,
        credibility=credibility_state,
    )
    research_decision.llm_overlay_audit = audit
else:
    final_bucket = bucket  # quant-only

research_decision.bucket_target = final_bucket
```

### 7.2. Feature flag

```python
DEFAULT_CONFIG = {
    ...
    "tier3_llm_overlay_enabled": False,  # default off — explicit enable
    "tier3_llm_k_samples": 5,
    "tier3_band": 0.05,
    "tier3_ewma_alpha": 0.10,
    "tier3_cred_cold_start": 0.30,
}
```

**Rationale:** Tier 3는 forward-tuning 필수 (LLM 비결정성). Default off → 대회 첫 1주는 quant-only로 안정 운영, baseline 검증 후 enable.

### 7.3. Reflective Memory (TrustTrade-inspired)

대회 진행 중 *LLM 결정 → 결과* trail 기록:

```python
@dataclass
class LLMOverlayJournal:
    """매 rebalance 마다 LLM overlay 의사결정 기록."""
    timestamp: datetime
    quant_target: dict[str, float]
    llm_views: list[LLMBucketView]
    novelty: float
    consensus: dict[str, float]
    credibility_snapshot: dict[str, float]
    final_target: dict[str, float]
    audit: dict[str, dict[str, float]]
    # 후행 — N period 후 update
    realized_returns: dict[str, float] | None = None
```

Journal entry는 `data/llm_overlay/journal_YYYY-MM-DD.jsonl` 에 append. Credibility EWMA update 시 참조.

---

## 8. Acceptance Criteria

### 8.1. Schema + LLM contract
- [ ] `LLMBucketView` schema 검증 (8 bucket × delta ∈ [-1, +1])
- [ ] LLM 호출이 schema-locked JSON 반환 (structured output / tool use)
- [ ] `cited_events` field가 actual news_report event ID 참조 (hallucination 방지)
- [ ] K=5 sample 호출 latency < 60초

### 8.2. Calculation correctness
- [ ] `compute_novelty(zero salience history)` → 0
- [ ] `compute_novelty(extreme z)` → 1 (capped)
- [ ] `compute_consensus(all same sign)` → 1.0 for that bucket
- [ ] `compute_consensus(all neutral)` → 0.0
- [ ] `update_credibility(hit)` → cred 증가, `(miss)` → 감소
- [ ] Cred persistence: restart 후 cred 유지

### 8.3. Blending bounds
- [ ] `apply_llm_overlay` 출력에서 per-bucket delta ≤ BAND (±5pp)
- [ ] Mandate constraint 유지: final_target의 RISK_BUCKETS sum ≤ 0.70
- [ ] sum(final_target) = 1.0 (probability simplex)
- [ ] All weights ≥ 0

### 8.4. Cold-start behavior
- [ ] 대회 첫 day (credibility 모두 0.3, no historical_salience): novelty=0 → final_target == quant_target
- [ ] 1주일 후 cred update만 발생: w_LLM 효과 매우 작음 (cred=0.3 × novelty × consensus 곱)

### 8.5. Feature flag
- [ ] `tier3_llm_overlay_enabled: False` 환경에서 Stage 2 output 그대로 사용 (quant-only)
- [ ] Enable/disable runtime toggle 가능

### 8.6. Forward-tuning protocol
- [ ] LLM Overlay Journal jsonl 기록 작동
- [ ] N-period 후 realized_returns 자동 채움 (background job)
- [ ] BAND/α/cred_prior 수동 tune 가능 (config)

---

## 9. 영향받는 파일

| File | 변경 |
|---|---|
| `tradingagents/schemas/llm_overlay.py` | **신규** — LLMBucketView, CredibilityState, LLMOverlayJournal |
| `tradingagents/agents/overlay/llm_bucket_overlay.py` | **신규** — generate_llm_views (K-sample) |
| `tradingagents/skills/overlay/novelty.py` | **신규** |
| `tradingagents/skills/overlay/consensus.py` | **신규** |
| `tradingagents/skills/overlay/credibility.py` | **신규** + persistence |
| `tradingagents/skills/overlay/apply.py` | **신규** — apply_llm_overlay |
| `tradingagents/agents/managers/research_manager.py` | Tier 3 호출 포인트 추가 (feature-flag) |
| `tradingagents/default_config.py` | tier3_llm_overlay_enabled flag + 4 sub-flags |
| `data/llm_overlay/credibility.json` | persistence (runtime created) |
| `data/llm_overlay/journal_*.jsonl` | journal (append-only) |
| `tests/unit/schemas/test_llm_overlay.py` | schema tests |
| `tests/unit/skills/overlay/test_novelty.py` | novelty edge cases |
| `tests/unit/skills/overlay/test_consensus.py` | sign aggregation |
| `tests/unit/skills/overlay/test_credibility.py` | EWMA + persistence |
| `tests/unit/skills/overlay/test_apply.py` | blending bounds, mandate compliance |
| `tests/integration/test_tier3_overlay.py` | end-to-end mock LLM |

---

## 10. Limitations + Forward-tuning

**구조적 한계:**
- **Backtest validation 불가**: LLM 비결정성 + historical news replay 어려움. Tier 0-2와 달리 backtest로 Sharpe 측정 못 함.
- **Cold-start 1개월**: cred=0.3 prior로 시작 → 대회 첫 1개월은 LLM 영향 minimal (w_LLM ≈ 0.05-0.10).
- **K=5 cost**: 매 rebalance 마다 5× LLM call. 대회 12 rebalance × 5 = 60 LLM call. 비용 미미하나 latency ~30s.
- **BAND choice**: ±5pp는 *prior choice*. Forward observation 후 BAND tightening/loosening 가능 (BAND=0.03 conservative, BAND=0.07 aggressive).

**Forward-tuning protocol (A14 ambiguity 해소):**

| Phase | Period | Action | Trigger |
|---|---|---|---|
| Phase 1 | Week 1-2 (6/1-6/14) | feature flag OFF, quant-only. Salience history accumulate. | unconditional |
| Phase 2 | Week 3 (6/15+) | feature flag ON, BAND=0.05, cred=0.3 cold-start. EWMA update 시작. | salience history ≥ 14일 + Stage 1-4 stable |
| Phase 3 | Week 4-12 | BAND auto-tune: 6 rebalance 후 cred mean 기반 자동 조정 | rebalance count ≥ 6 |

**Hit rate 산정 (A14 detail):**
- **N = 1 month** (next rebalance horizon — 주간 rebalance 시 4 weeks)
- Hit = `sign(predicted_delta_t) == sign(realized_return_{t+1m})` for each bucket
- Per-bucket EWMA: `cred[b]_t = (1-α) × cred[b]_{t-1} + α × hit_t` (α=0.1)
- Note: 첫 1m 후부터 hit rate 산정 가능 → Phase 2 시작 후 4 week 후부터 cred 실제 update

**BAND auto-tune logic (Phase 3):**

```python
def auto_tune_band(cred_state: CredibilityState, current_band: float) -> float:
    """6 rebalance 후 평균 cred 기반 BAND 자동 조정."""
    if cred_state.history_count < 6 * len(BUCKETS):
        return current_band  # insufficient history
    avg_cred = np.mean(list(cred_state.bucket_cred.values()))
    if avg_cred < 0.40:
        new_band = max(0.03, current_band - 0.01)  # tighten if LLM unreliable
    elif avg_cred > 0.60:
        new_band = min(0.07, current_band + 0.01)  # loosen if LLM reliable
    else:
        new_band = current_band
    if new_band != current_band:
        logger.info("Tier 3 BAND auto-tune: %.2f → %.2f (avg_cred=%.2f)",
                    current_band, new_band, avg_cred)
    return new_band
```

**Async architecture (B7 asymmetric blending — design intent 명시):**

LLM의 net direction (예: 모든 bucket 증가)이 *mandate constraint + QP projection*에 의해 redistributed. 이는 *의도된 trade-off*:

- **Pro**: portfolio manager의 *absolute level* 통제 우선 (위험 70% cap, sum=1)
- **Con**: LLM의 *"전반적 risk-on" 신호*는 individual bucket weight로만 변환되며 *total risk shift* 못 함

→ Tier 3는 *relative direction* signal로만 운영. *Absolute risk regime shift*는 quant factor model (특히 F10 systemic_liquidity) 책임.

---

## 11. Out of Scope

- **LLM provider 선택**: OpenAI vs Anthropic vs Gemini — 기존 `llm_clients/` 사용
- **LLM 비용 추적**: 대회 운영비 별도 (per-call cost 추적은 v2)
- **Multi-horizon overlay**: 현 spec은 single-period (next quarter). Multi-horizon은 v2
- **Reflective Memory 고도화**: 최소 journal 구현. RAG-based memory retrieval은 v2
- **Backtest 시뮬레이션**: LLM mock-based sanity test만, full backtest unfeasible

---

## 12. 참고문헌

- TrustTrade (Selective Consensus, Reflective Memory, Deterministic Temporal Anchoring) — Gemini Deep Research에 인용
- Man Group "LLM over-extrapolation/overreaction bias" — Gemini Deep Research에 인용
- Hybrid AI golden ratio (50-60% quant base / 30-40% LLM / 10-20% fusion) — 본 spec은 compute budget이 아닌 *decision weight* 적용 (cred=0.3 prior + dynamic)
- Black-Litterman 1992 (rejected for weight-space system — return-space machinery 부재)
- Asness 2003 "On the Profitability of Stocks Picked by Analysts" (LLM as analyst proxy)

---

**Tier 0/1/2/3 specs complete.** Next: spec self-review + user review → writing-plans skill.
