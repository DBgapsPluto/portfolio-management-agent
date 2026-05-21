"""24-cell 확률 → BucketTarget 결정적 매핑.

각 cell의 playbook은 scenario_definitions.make_playbook(cycle,tail,kr)에서
산출. mapper는 cell 확률 × playbook 가중평균.

dominant_cell vs dominant_cycle 차이:
  - dominant_cell: max P_cell (24 cell 중). 가장 likely한 단일 상태.
  - dominant_cycle: max D1 marginal P (4 cycle 중). cycle dimension에서의
    overall 방향. conviction은 dominant_cycle_probability 기준.
"""
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.schemas.research import (
    ALL_CELLS, CYCLE_CODES, CellCoord, ConvictionLevel, KR_CODES,
    ResearchDecision, ScenarioProbabilities24, TAIL_CODES, cell_key, parse_cell_key,
)
from tradingagents.skills.registry import register_skill
from tradingagents.skills.research.scenario_definitions import (
    make_bond_tips_share, make_playbook,
)


# Conviction thresholds — dominant_cycle marginal 기준.
_CONVICTION_HIGH = 0.55
_CONVICTION_MEDIUM = 0.35

# Sharpening 옵션 — Issue #5 / spec §2 C3 / decisions.md D1.
# C2 variance n=20 측정 결과 (2026-05-15 fixture):
#   - dominant_cycle flip rate: 0% (20/20 모두 B)
#   - bond σ: 0.3pp ≪ 3pp 임계
#   - effective B (post β=2.38 sharpening): 99.2% — 24-cell cross-effect 통째 짓누름
# → 옵션 A 채택: β=1 고정 (sharpening 자체 제거).
# 미래 cycle transition 시점에 variance 재측정하여 옵션 B/C 재평가 권장.
# 옛 상수 (_BETA_THRESHOLD=0.30, _BETA_SLOPE=3.0, _BETA_CAP=4.0) 는 결정 후 제거.


def _classify_conviction(max_cycle_prob: float) -> ConvictionLevel:
    if max_cycle_prob >= _CONVICTION_HIGH:
        return "high"
    if max_cycle_prob >= _CONVICTION_MEDIUM:
        return "medium"
    return "low"


def _compute_conviction_beta(dominant_cycle_prob: float) -> float:
    """β=1.0 고정 — sharpening 비활성 (option A, decisions.md D1).

    인자 보존 (legacy caller 호환) 하되 항상 1.0 반환.
    """
    return 1.0


def _sharpen_cycle_marginal(
    prob_dict: dict[str, float], beta: float,
) -> dict[str, float]:
    """Cycle marginal에 P^β/Z 적용, P(tail, kr | cycle) 보존.

    β=1이면 입력 그대로 반환. β>1이면 dominant cycle 강화.
    """
    if abs(beta - 1.0) < 1e-9:
        return dict(prob_dict)

    # 1. cycle marginal 계산
    marg: dict[str, float] = {c: 0.0 for c in CYCLE_CODES}
    for key, p in prob_dict.items():
        c, _, _ = parse_cell_key(key)
        marg[c] += p

    # 2. sharpen + normalize
    sharp_marg = {c: marg[c] ** beta for c in CYCLE_CODES}
    z = sum(sharp_marg.values())
    if z <= 1e-9:
        return dict(prob_dict)
    sharp_marg = {c: v / z for c, v in sharp_marg.items()}

    # 3. conditional 보존하며 cell 재구성
    out: dict[str, float] = {}
    for key, p in prob_dict.items():
        c, _, _ = parse_cell_key(key)
        cond = (p / marg[c]) if marg[c] > 1e-9 else 0.0
        out[key] = sharp_marg[c] * cond
    return out


def _renormalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("All weights non-positive")
    return {k: v / total for k, v in weights.items()}


@register_skill(name="map_scenarios_to_bucket", category="research")
def map_probs_to_bucket(
    probs: ScenarioProbabilities24, rationale_seed: str = "",
) -> ResearchDecision:
    """24-cell prob → BucketTarget. Conviction sharpening 적용 (P0 step 3).

    흐름:
      1. raw cycle marginal에서 dominant_cycle + conviction 분류
      2. β = f(raw dominant_cycle_probability) 계산
      3. cycle marginal에 P^β/Z 적용, P(tail,kr|cycle) 보존 → sharpened cell probs
      4. sharpened probs로 portfolio (가중평균)
      5. cycle_marginals 등 메타데이터는 RAW (LLM view) 유지,
         effective_cycle_marginals에 sharpened 값 노출.

    Invariant: 모든 playbook이 risk≤0.70 → 선형결합도 ≤0.70 (mandate 안전).
    """
    raw_prob_dict = probs.as_dict()

    # === Raw marginals (LLM's view, transparency용) ===
    cycle_marginals: dict[str, float] = {c: probs.cycle_marginal(c) for c in CYCLE_CODES}
    tail_marginals: dict[str, float] = {t: probs.tail_marginal(t) for t in TAIL_CODES}
    kr_marginals: dict[str, float] = {k: probs.kr_marginal(k) for k in KR_CODES}

    dominant_cycle = max(cycle_marginals, key=lambda c: cycle_marginals[c])
    dominant_cycle_prob = cycle_marginals[dominant_cycle]
    conviction = _classify_conviction(dominant_cycle_prob)

    # === Conviction sharpening ===
    beta = _compute_conviction_beta(dominant_cycle_prob)
    sharp_prob_dict = _sharpen_cycle_marginal(raw_prob_dict, beta)

    # effective cycle marginal (sharpened)
    eff_cycle_marg: dict[str, float] = {c: 0.0 for c in CYCLE_CODES}
    for key, p in sharp_prob_dict.items():
        c, _, _ = parse_cell_key(key)
        eff_cycle_marg[c] += p

    # === Portfolio (from sharpened probs) ===
    accumulator: dict[str, float] = {
        "kr_equity": 0.0, "global_equity": 0.0,
        "fx_commodity": 0.0, "bond": 0.0, "cash_mmf": 0.0,
    }
    tips_acc = 0.0
    for key in ALL_CELLS:
        p = sharp_prob_dict[key]
        if p <= 0:
            continue
        c, t, k = parse_cell_key(key)
        pb = make_playbook(c, t, k)
        for asset, w in pb.items():
            accumulator[asset] += p * w
        tips_acc += p * make_bond_tips_share(c, t, k)
    normalized = _renormalize(accumulator)

    # === Dominant cell — raw 기준 (LLM view) ===
    dominant_key = max(raw_prob_dict, key=lambda k: raw_prob_dict[k])
    dominant_cell = CellCoord.from_key(dominant_key)
    dominant_cell_prob = raw_prob_dict[dominant_key]

    rationale = (
        f"Cycle dominant: {dominant_cycle} "
        f"({dominant_cycle_prob:.0%}, {conviction}, β={beta:.2f}"
        f"→eff {eff_cycle_marg[dominant_cycle]:.0%}). "
        f"Top cell: {dominant_key} ({dominant_cell_prob:.0%}). "
        f"{rationale_seed}"
    )[:500]

    bucket = BucketTarget(
        kr_equity=normalized["kr_equity"],
        global_equity=normalized["global_equity"],
        fx_commodity=normalized["fx_commodity"],
        bond=normalized["bond"],
        cash_mmf=normalized["cash_mmf"],
        rationale=rationale,
        bond_tips_share=max(0.0, min(1.0, tips_acc)),
    )

    return ResearchDecision(
        bucket_target=bucket,
        scenario_probabilities=probs,
        dominant_cell=dominant_cell,
        dominant_cell_probability=dominant_cell_prob,
        dominant_cycle=dominant_cycle,  # type: ignore[arg-type]
        dominant_cycle_probability=dominant_cycle_prob,
        cycle_marginals=cycle_marginals,
        tail_marginals=tail_marginals,
        kr_marginals=kr_marginals,
        conviction=conviction,
        conviction_beta=beta,
        effective_cycle_marginals=eff_cycle_marg,
    )
