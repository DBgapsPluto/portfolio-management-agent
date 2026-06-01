"""Historical anchor with LIVE Stage 1 — synthetic-input 모드의 보완.

기존 `anchor_evaluator.evaluate_anchor`는 anchor JSON에 적힌 Stage 1·2 값을
SimpleNamespace로 만들어 Stage 3에 주입. 이 모드는 Stage 3 격리 평가에는
좋지만, "실제 시장 데이터 → factor 계산 → Stage 3" 의 end-to-end 동작을
검증하지는 못 함.

이 모듈은 anchor의 as_of_date에 **Stage 1을 라이브 실행** 해서 진짜 macro/
risk/technical report를 만든 다음 Stage 3에 흘려보낸다.

Stage 2 (research_decision + bucket_target) 는 anchor JSON 그대로 사용 —
LLM 기반이라 historical에서 재현 어렵고, Stage 3 평가의 입력 변수로 고정해야
실험 비교 가능.

사용:
    from tradingagents.observability.anchor_live import evaluate_anchor_live
    result = evaluate_anchor_live(
        "data/historical_anchors/2024-11_kr_boom.json",
        universe_path="data/universe.json",
        cache_path="~/.tradingagents/cache/etf_prices.parquet",
    )
    print(result.pass_count, "/", len(result.checks))

비용: LIVE Stage 1당 LLM 2-5회 호출 (~$0.05). 5개 anchor 전체 ~$0.25.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from tradingagents.observability.anchor_evaluator import (
    AnchorEvalResult, CheckResult, _bucket_of_ticker, _sub_category_totals,
    _RISK_BUCKETS,
)

# Path setup for pandas_ta / pypfopt shim (Stage 1 freshness audit과 동일)
if "pandas_ta" not in sys.modules:
    try:
        import pandas_ta_classic as _ta_classic
        sys.modules["pandas_ta"] = _ta_classic
    except ImportError:
        pass

logger = logging.getLogger(__name__)


def _make_llms():
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.llm_clients import create_llm_client
    deep = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["deep_think_llm"],
    ).get_llm()
    quick = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["quick_think_llm"],
    ).get_llm()
    return quick, deep


def _run_live_stage1(
    as_of_str: str, universe_path: str, cache_path: str | None,
    quick_llm, deep_llm,
) -> dict:
    """Stage 1 (macro_quant + market_risk + technical) LIVE 실행 → 부분 state.

    macro_news는 건너뛴다 (Stage 3 입력에 직접 사용되지 않음, historical
    뉴스는 어차피 fetch 불가).
    """
    from tradingagents.agents.analysts.macro_quant_analyst import (
        create_macro_quant_analyst,
    )
    from tradingagents.agents.analysts.market_risk_analyst import (
        create_market_risk_analyst,
    )
    from tradingagents.agents.analysts.technical_analyst import (
        create_technical_analyst,
    )
    from tradingagents.agents.utils.agent_states import _create_empty_state

    state = _create_empty_state(
        as_of_date=as_of_str,
        universe_path=universe_path,
        capital_krw=1_000_000_000,
        preset_name="db_gaps",
    )

    out_state: dict = dict(state)

    for name, factory in [
        ("macro_quant",  lambda: create_macro_quant_analyst(quick_llm, deep_llm)),
        ("market_risk",  lambda: create_market_risk_analyst(quick_llm, deep_llm)),
        ("technical",    lambda: create_technical_analyst(quick_llm, deep_llm, cache_path=cache_path)),
    ]:
        logger.info("[anchor_live] running Stage 1 analyst: %s", name)
        node = factory()
        delta = node(out_state)
        if isinstance(delta, dict):
            out_state.update(delta)
    return out_state


def _build_stage2_synthetic(anchor: dict, stage1_state: dict) -> dict:
    """anchor JSON의 Stage 2 (research_decision + bucket_target) 를 SimpleNamespace로."""
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.observability.anchor_evaluator import _extract_bucket_weights

    bt_data = anchor["stage2"]["bucket_target"]
    bucket_target = BucketTarget(
        weights=_extract_bucket_weights(bt_data),
        bond_tips_share=bt_data.get("bond_tips_share", 0.0),
        rationale=f"anchor: {anchor['anchor_id']}",
    )
    cell_key = anchor["stage2"]["dominant_cell"]
    dominant_cell = SimpleNamespace(key=cell_key)
    research_decision = SimpleNamespace(
        dominant_cell=dominant_cell,
        dominant_scenario=anchor["stage2"].get("dominant_scenario_legacy"),
        conviction=anchor["stage2"]["conviction"],
    )
    return {
        "bucket_target":     bucket_target,
        "research_decision": research_decision,
    }


def evaluate_anchor_live(
    anchor_path: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
    quick_llm=None,
    deep_llm=None,
    with_stage4: bool = False,
) -> AnchorEvalResult:
    """Stage 1 LIVE + Stage 2 anchor 명세 + Stage 3 평가."""
    from tradingagents.agents.allocator.portfolio_allocator import (
        create_portfolio_allocator,
    )
    from tradingagents.dataflows.universe import load_universe

    anchor_path = Path(anchor_path)
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))

    universe = load_universe(universe_path)

    if quick_llm is None or deep_llm is None:
        quick_llm, deep_llm = _make_llms()

    # 1. Stage 1 LIVE
    state = _run_live_stage1(
        anchor["as_of_date"], universe_path, cache_path, quick_llm, deep_llm,
    )

    # macro_report / risk_report / technical_report가 채워졌어야 함
    for k in ("macro_report", "risk_report", "technical_report"):
        if state.get(k) is None:
            raise RuntimeError(f"Stage 1 LIVE 실패 — {k} 비어있음")

    # 2. Stage 2 from anchor spec
    state.update(_build_stage2_synthetic(anchor, state))

    # 3. Stage 3 노드 호출
    node = create_portfolio_allocator(cache_path=cache_path)
    out = node(state)

    wv = out["weight_vector"]
    mc = out["method_choice"]
    weights = wv.weights
    sub_totals = _sub_category_totals(weights, universe)
    n_unique = sum(1 for sc, w in sub_totals.items() if sc != "_unknown" and w > 0)

    bucket_of = _bucket_of_ticker(universe)
    risk_asset_total = sum(
        w for t, w in weights.items() if bucket_of.get(t) in _RISK_BUCKETS
    )

    # 4. 평가 (anchor_evaluator의 7-8축 체크 재현)
    expected = anchor["expected_stage3"]
    checks: list[CheckResult] = []

    # 1. method
    accepted = set(expected.get("acceptable_methods", []))
    method_str = mc.method.value
    checks.append(CheckResult(
        name="method_ok",
        passed=(not accepted) or (method_str in accepted),
        detail=f"chosen={method_str}, accepted={sorted(accepted)}",
        expected=sorted(accepted), actual=method_str,
    ))

    # 2. required (strict label)
    required = expected.get("required_sub_categories", [])
    missing_req = [sc for sc in required if sub_totals.get(sc, 0) <= 0]
    checks.append(CheckResult(
        name="required_present",
        passed=len(missing_req) == 0,
        detail=f"missing={missing_req}" if missing_req else "all present (or none required)",
        expected=required, actual={sc: sub_totals.get(sc, 0) for sc in required},
    ))

    # 2b. substitute groups
    groups = expected.get("required_substitute_groups", [])
    group_results = []
    group_failures = []
    for g in groups:
        total = sum(sub_totals.get(sc, 0) for sc in g["any_of"])
        ok = total >= g["min_total_weight"]
        group_results.append({"name": g["name"], "total": total,
                              "min": g["min_total_weight"], "ok": ok})
        if not ok:
            group_failures.append(
                f"{g['name']}: {total:.3f} < {g['min_total_weight']:.3f}"
            )
    checks.append(CheckResult(
        name="substitute_groups_met",
        passed=len(group_failures) == 0,
        detail=("; ".join(group_failures) if group_failures
                else f"{len(groups)} group(s) all met" if groups else "none configured"),
        expected=groups, actual=group_results,
    ))

    # 3. forbidden
    forbidden = expected.get("forbidden_sub_categories", [])
    violated_forb = [sc for sc in forbidden if sub_totals.get(sc, 0) > 1e-6]
    checks.append(CheckResult(
        name="forbidden_absent",
        passed=len(violated_forb) == 0,
        detail=(f"present={[(sc, sub_totals[sc]) for sc in violated_forb]}"
                if violated_forb else "all absent"),
        expected=forbidden, actual={sc: sub_totals.get(sc, 0) for sc in forbidden},
    ))

    # 4. min weights
    min_w = expected.get("min_sub_category_weights", {})
    failed_min = {sc: (sub_totals.get(sc, 0), thr) for sc, thr in min_w.items()
                  if sub_totals.get(sc, 0) < thr}
    checks.append(CheckResult(
        name="min_weights_met",
        passed=len(failed_min) == 0,
        detail=("; ".join(f"{sc}: {v:.3f} < {t:.3f}" for sc, (v, t) in failed_min.items())
                if failed_min else "all minima met"),
        expected=min_w, actual={sc: sub_totals.get(sc, 0) for sc in min_w},
    ))

    # 5. max weights
    max_w = expected.get("max_sub_category_weights", {})
    failed_max = {sc: (sub_totals.get(sc, 0), thr) for sc, thr in max_w.items()
                  if sub_totals.get(sc, 0) > thr + 1e-6}
    checks.append(CheckResult(
        name="max_weights_met",
        passed=len(failed_max) == 0,
        detail=("; ".join(f"{sc}: {v:.3f} > {t:.3f}" for sc, (v, t) in failed_max.items())
                if failed_max else "all maxima met"),
        expected=max_w, actual={sc: sub_totals.get(sc, 0) for sc in max_w},
    ))

    # 6. diversity
    min_unique = expected.get("min_unique_sub_categories", 1)
    checks.append(CheckResult(
        name="diversity_ok",
        passed=n_unique >= min_unique,
        detail=f"n_unique={n_unique}, min={min_unique}",
        expected=min_unique, actual=n_unique,
    ))

    # 7. risk asset
    risk_max = expected.get("risk_asset_max", 1.0)
    checks.append(CheckResult(
        name="risk_asset_ok",
        passed=risk_asset_total <= risk_max + 1e-6,
        detail=f"risk_asset={risk_asset_total:.3f}, max={risk_max:.3f}",
        expected=risk_max, actual=risk_asset_total,
    ))

    # Stage 4 (with_stage4=True 시만) — LIVE state 는 이미 risk_judge 가
    # 기대하는 형태 (correlation_clusters, vix_term, funding_stress) 이므로
    # risk_judge 노드 직접 호출.
    stage4_checks = stage4_outcome = stage4_weights = stage4_bucket_diff = None
    stage4_active = False
    if with_stage4:
        from tradingagents.observability.anchor_evaluator import (
            _score_eight_axes, _bucket_weights,
        )
        from tradingagents.agents.managers.risk_judge import create_risk_judge

        risk_state = dict(state)
        risk_state.update({
            "as_of_date":    anchor["as_of_date"],
            "weight_vector": wv,
            "candidate_set": out["candidate_set"],
        })
        risk_node = create_risk_judge(cache_path=cache_path)
        risk_out = risk_node(risk_state)
        stage4_weights = risk_out["weight_vector"].weights
        stage4_outcome = risk_out["risk_overlay"].overlay_apply_outcome
        stage4_active = not risk_out["risk_overlay"].is_empty()

        sub_totals_4 = _sub_category_totals(stage4_weights, universe)
        n_unique_4 = sum(
            1 for sc, w in sub_totals_4.items() if sc != "_unknown" and w > 0
        )
        risk_asset_total_4 = sum(
            w for t, w in stage4_weights.items() if bucket_of.get(t) in _RISK_BUCKETS
        )
        stage4_checks = _score_eight_axes(
            expected=anchor["expected_stage3"],
            weights=stage4_weights,
            sub_totals=sub_totals_4,
            n_unique=n_unique_4,
            risk_asset_total=risk_asset_total_4,
            method_str=method_str,
        )
        b3 = _bucket_weights(weights, universe)
        b4 = _bucket_weights(stage4_weights, universe)
        all_b = set(b3) | set(b4)
        stage4_bucket_diff = {
            b: round(b4.get(b, 0) - b3.get(b, 0), 4)
            for b in all_b
            if abs(b4.get(b, 0) - b3.get(b, 0)) >= 0.005
        }

    return AnchorEvalResult(
        anchor_id=anchor["anchor_id"],
        as_of_date=anchor["as_of_date"],
        title=anchor["title"],
        checks=checks,
        chosen_method=method_str,
        weights=weights,
        sub_category_totals=sub_totals,
        n_unique_sub_categories=n_unique,
        risk_asset_total=risk_asset_total,
        allocation_attribution=out.get("allocation_attribution"),
        stage4_checks=stage4_checks,
        stage4_outcome=stage4_outcome,
        stage4_weights=stage4_weights,
        stage4_overlay_was_active=stage4_active,
        stage4_bucket_diff=stage4_bucket_diff,
    )


def evaluate_all_live(
    catalog_dir: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
    with_stage4: bool = False,
) -> list[AnchorEvalResult]:
    catalog_dir = Path(catalog_dir)
    anchor_files = sorted(
        p for p in catalog_dir.glob("*.json")
        if not p.name.startswith("_")
    )
    # LLM 1번만 생성하고 재사용
    quick_llm, deep_llm = _make_llms()
    results = []
    for p in anchor_files:
        try:
            r = evaluate_anchor_live(
                p, universe_path=universe_path, cache_path=cache_path,
                quick_llm=quick_llm, deep_llm=deep_llm,
                with_stage4=with_stage4,
            )
            results.append(r)
        except Exception as e:
            logger.error("anchor %s LIVE evaluation failed: %s", p.name, e, exc_info=True)
    return results
