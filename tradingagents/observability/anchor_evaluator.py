"""Historical anchor evaluator — anchor 합의 기준 대비 Stage 3 행동 점수.

평가 흐름:
    1. anchor JSON 로드
    2. synthetic Stage 1·2 state 구성
        - factor_panel: real cache 데이터로 anchor 시점 계산 (실제 가격 사용)
        - macro_report / risk_report / research_decision: anchor가 적은 합의 값
    3. Stage 3 allocator 실행
    4. expected_stage3 조건 7축으로 채점:
        method_ok / required_present / forbidden_absent
        min_weights_met / max_weights_met / diversity_ok / risk_asset_ok

결과는 단일 score가 아니라 **7축의 pass/fail dict + 위반 상세**.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator
from tradingagents.dataflows.universe import Universe, load_universe
from tradingagents.schemas.portfolio import BucketTarget, OptimizationMethod
from tradingagents.skills.portfolio.candidate_selector import list_eligible_tickers
from tradingagents.skills.portfolio.factor_scorer import compute_factor_panel
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    expected: Any = None
    actual: Any = None


@dataclass
class AnchorEvalResult:
    anchor_id: str
    as_of_date: str
    title: str
    checks: list[CheckResult]
    chosen_method: str
    weights: dict[str, float]
    sub_category_totals: dict[str, float]
    n_unique_sub_categories: int
    risk_asset_total: float
    allocation_attribution: dict | None = None

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def to_dict(self) -> dict:
        return {
            "anchor_id":         self.anchor_id,
            "as_of_date":        self.as_of_date,
            "title":             self.title,
            "chosen_method":     self.chosen_method,
            "pass_count":        self.pass_count,
            "fail_count":        self.fail_count,
            "checks":            [asdict(c) for c in self.checks],
            "weights":           self.weights,
            "sub_category_totals":     self.sub_category_totals,
            "n_unique_sub_categories": self.n_unique_sub_categories,
            "risk_asset_total":  self.risk_asset_total,
        }


# ─────────────────────────────────────────────────────────────────────
# Synthetic state builders
# ─────────────────────────────────────────────────────────────────────

def _build_factor_panel(
    tickers: list[str], returns: pd.DataFrame,
    aum_lookup: dict[str, float],
) -> dict:
    """Compute factor_panel from real returns matrix at the anchor date."""
    panel = {}
    for t in tickers:
        aum = aum_lookup.get(t, 1e12)
        if t in returns.columns:
            panel[t] = compute_factor_panel(returns[t], aum)
        else:
            panel[t] = compute_factor_panel(pd.Series(dtype=float), aum)
    return panel


def _build_state(
    anchor: dict, universe: Universe, returns: pd.DataFrame,
    universe_path: str,
) -> dict:
    """Construct minimal state dict accepted by Stage 3 allocator.

    Uses SimpleNamespace for nested attribute access (allocator only does .x.y reads).
    """
    as_of = date.fromisoformat(anchor["as_of_date"])
    tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}

    # bucket_target
    bt_data = anchor["stage2"]["bucket_target"]
    bucket_target = BucketTarget(
        kr_equity=bt_data["kr_equity"],
        global_equity=bt_data["global_equity"],
        fx_commodity=bt_data["fx_commodity"],
        bond=bt_data["bond"],
        cash_mmf=bt_data["cash_mmf"],
        bond_tips_share=bt_data.get("bond_tips_share", 0.0),
        rationale=f"anchor: {anchor['anchor_id']}",
    )

    regime = SimpleNamespace(
        quadrant=anchor["stage1"]["regime"]["quadrant"],
        confidence=anchor["stage1"]["regime"]["confidence"],
    )
    macro_report = SimpleNamespace(regime=regime)

    systemic = SimpleNamespace(
        score=anchor["stage1"]["systemic"]["score"],
        regime=anchor["stage1"]["systemic"]["regime"],
    )
    risk_report = SimpleNamespace(systemic_score=systemic)

    panel = _build_factor_panel(tickers, returns, aum_lookup)
    technical_report = SimpleNamespace(factor_panel=panel)

    cell_key = anchor["stage2"]["dominant_cell"]
    dominant_cell = SimpleNamespace(key=cell_key)
    research_decision = SimpleNamespace(
        dominant_cell=dominant_cell,
        dominant_scenario=anchor["stage2"].get("dominant_scenario_legacy"),
        conviction=anchor["stage2"]["conviction"],
    )

    return {
        "as_of_date":          as_of.isoformat(),
        "universe_path":       universe_path,
        "bucket_target":       bucket_target,
        "macro_report":        macro_report,
        "risk_report":         risk_report,
        "technical_report":    technical_report,
        "research_decision":   research_decision,
        "allocation_attempts": 0,
        "allocation_feedback": [],
    }


# ─────────────────────────────────────────────────────────────────────
# Check helpers
# ─────────────────────────────────────────────────────────────────────

_RISK_BUCKETS = {"kr_equity", "global_equity", "fx_commodity"}


def _sub_category_totals(
    weights: dict[str, float], universe: Universe,
) -> dict[str, float]:
    sc_lookup = {e.ticker: (e.sub_category or "_unknown") for e in universe.etfs}
    out: dict[str, float] = {}
    for t, w in weights.items():
        sc = sc_lookup.get(t, "_unknown")
        out[sc] = out.get(sc, 0.0) + w
    return out


def _bucket_of_ticker(universe: Universe) -> dict[str, str]:
    cat_to_bucket = {
        "국내주식_지수": "kr_equity", "국내주식_섹터": "kr_equity",
        "해외주식_지수": "global_equity", "해외주식_섹터": "global_equity",
        "FX 및 원자재": "fx_commodity",
        "국내채권_종합": "bond", "국내채권_회사채": "bond",
        "해외채권_종합": "bond", "해외채권_회사채": "bond",
        "금리연계형/초단기채권": "cash_mmf",
    }
    return {
        e.ticker: cat_to_bucket.get(e.category, "_unknown")
        for e in universe.etfs
    }


# ─────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────

def evaluate_anchor(
    anchor_path: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
) -> AnchorEvalResult:
    anchor_path = Path(anchor_path)
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))

    universe = load_universe(universe_path)
    as_of = date.fromisoformat(anchor["as_of_date"])

    # eligible tickers + returns matrix (1 year for factor panel)
    bt = BucketTarget(
        kr_equity=anchor["stage2"]["bucket_target"]["kr_equity"],
        global_equity=anchor["stage2"]["bucket_target"]["global_equity"],
        fx_commodity=anchor["stage2"]["bucket_target"]["fx_commodity"],
        bond=anchor["stage2"]["bucket_target"]["bond"],
        cash_mmf=anchor["stage2"]["bucket_target"]["cash_mmf"],
        bond_tips_share=anchor["stage2"]["bucket_target"].get("bond_tips_share", 0.0),
        rationale="anchor evaluation",
    )
    eligible_by_bucket = list_eligible_tickers(
        universe, bt, as_of=as_of, min_aum_krw=1_000_000_000_000,
    )
    eligible = sorted({t for ts in eligible_by_bucket.values() for t in ts})
    if not eligible:
        raise RuntimeError(f"{anchor['anchor_id']}: no eligible tickers")

    returns = fetch_returns_matrix(
        eligible, as_of - timedelta(days=365 * 3), as_of, cache_path=cache_path,
    )

    state = _build_state(anchor, universe, returns, universe_path)

    # Stage 3 실행
    node = create_portfolio_allocator(cache_path=cache_path)
    out = node(state)

    wv = out["weight_vector"]
    mc = out["method_choice"]
    weights = wv.weights
    sub_totals = _sub_category_totals(weights, universe)
    n_unique = sum(1 for sc, w in sub_totals.items() if sc != "_unknown" and w > 0)

    # bucket → ticker로 risk_asset 비중 계산
    bucket_of = _bucket_of_ticker(universe)
    risk_asset_total = sum(
        w for t, w in weights.items() if bucket_of.get(t) in _RISK_BUCKETS
    )

    # ─── 7축 체크 ───
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

    # 2. required sub_categories (strict label check)
    required = expected.get("required_sub_categories", [])
    missing_req = [sc for sc in required if sub_totals.get(sc, 0) <= 0]
    checks.append(CheckResult(
        name="required_present",
        passed=len(missing_req) == 0,
        detail=f"missing={missing_req}" if missing_req else "all present (or none required)",
        expected=required, actual={sc: sub_totals.get(sc, 0) for sc in required},
    ))

    # 2b. required substitute groups (outcome-based — KOSPI200 covers semis 등)
    groups = expected.get("required_substitute_groups", [])
    group_results = []
    group_failures = []
    for g in groups:
        total = sum(sub_totals.get(sc, 0) for sc in g["any_of"])
        min_w = g["min_total_weight"]
        # 1e-6 tolerance — floating-point 누적 오차 (예: 0.11999999... vs 0.12)
        ok = total >= min_w - 1e-6
        group_results.append({
            "name": g["name"], "total": total, "min": min_w, "ok": ok,
            "any_of": g["any_of"],
        })
        if not ok:
            group_failures.append(f"{g['name']}: {total:.3f} < {min_w:.3f} (any_of={g['any_of']})")
    checks.append(CheckResult(
        name="substitute_groups_met",
        passed=len(group_failures) == 0,
        detail=(
            "; ".join(group_failures) if group_failures
            else f"{len(groups)} group(s) all met" if groups else "none configured"
        ),
        expected=groups, actual=group_results,
    ))

    # 3. forbidden sub_categories
    forbidden = expected.get("forbidden_sub_categories", [])
    violated_forb = [sc for sc in forbidden if sub_totals.get(sc, 0) > 1e-6]
    checks.append(CheckResult(
        name="forbidden_absent",
        passed=len(violated_forb) == 0,
        detail=(
            f"present={[(sc, sub_totals[sc]) for sc in violated_forb]}"
            if violated_forb else "all absent"
        ),
        expected=forbidden, actual={sc: sub_totals.get(sc, 0) for sc in forbidden},
    ))

    # 4. min_weights
    min_w = expected.get("min_sub_category_weights", {})
    failed_min = {sc: (sub_totals.get(sc, 0), thr) for sc, thr in min_w.items()
                  if sub_totals.get(sc, 0) < thr}
    checks.append(CheckResult(
        name="min_weights_met",
        passed=len(failed_min) == 0,
        detail=(
            "; ".join(f"{sc}: {v:.3f} < {t:.3f}" for sc, (v, t) in failed_min.items())
            if failed_min else "all minima met"
        ),
        expected=min_w,
        actual={sc: sub_totals.get(sc, 0) for sc in min_w},
    ))

    # 5. max_weights
    max_w = expected.get("max_sub_category_weights", {})
    failed_max = {sc: (sub_totals.get(sc, 0), thr) for sc, thr in max_w.items()
                  if sub_totals.get(sc, 0) > thr + 1e-6}
    checks.append(CheckResult(
        name="max_weights_met",
        passed=len(failed_max) == 0,
        detail=(
            "; ".join(f"{sc}: {v:.3f} > {t:.3f}" for sc, (v, t) in failed_max.items())
            if failed_max else "all maxima met"
        ),
        expected=max_w,
        actual={sc: sub_totals.get(sc, 0) for sc in max_w},
    ))

    # 6. diversity
    min_unique = expected.get("min_unique_sub_categories", 1)
    checks.append(CheckResult(
        name="diversity_ok",
        passed=n_unique >= min_unique,
        detail=f"n_unique={n_unique}, min={min_unique}",
        expected=min_unique, actual=n_unique,
    ))

    # 7. risk_asset cap
    risk_max = expected.get("risk_asset_max", 1.0)
    checks.append(CheckResult(
        name="risk_asset_ok",
        passed=risk_asset_total <= risk_max + 1e-6,
        detail=f"risk_asset={risk_asset_total:.3f}, max={risk_max:.3f}",
        expected=risk_max, actual=risk_asset_total,
    ))

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
    )


def evaluate_all(
    catalog_dir: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
) -> list[AnchorEvalResult]:
    catalog_dir = Path(catalog_dir)
    anchor_files = sorted(
        p for p in catalog_dir.glob("*.json")
        if not p.name.startswith("_")
    )
    results = []
    for p in anchor_files:
        try:
            r = evaluate_anchor(p, universe_path=universe_path, cache_path=cache_path)
            results.append(r)
        except Exception as e:
            logger.error("anchor %s evaluation failed: %s", p.name, e)
    return results
