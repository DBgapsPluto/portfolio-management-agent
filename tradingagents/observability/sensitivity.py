"""Stage 3 weight/boost sensitivity analysis — anchor 카탈로그 기반.

각 (regime_quadrant, factor) 가중치와 각 (axis, sub_category) boost multiplier를
±delta 흔들면서 anchor 합산 pass count 변화 측정. 어느 값이 가장 영향력 있는지
정량화 → 어떤 값에 더 주의를 기울일지 알려줌.

평가 metric: anchor 카탈로그 전체의 pass_count 합. 변동이 크면 sensitive,
0이면 robust (현재 값에 마진 충분).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

from tradingagents.observability.anchor_evaluator import (
    AnchorEvalResult, evaluate_anchor,
)
from tradingagents.skills.portfolio import factor_scorer, sub_category as sc_mod

logger = logging.getLogger(__name__)


# ── 직접 perturb 할 수 있는 weight/boost 위치 인덱스 ──

def _regime_weight_keys() -> list[tuple[str, str]]:
    """(regime_quadrant, factor) tuple 목록."""
    out = []
    for q, w in factor_scorer.REGIME_FACTOR_WEIGHTS.items():
        for f in w:
            out.append((q, f))
    return out


def _boost_keys() -> list[tuple[str, str, str]]:
    """(axis, axis_value, sub_category) tuple 목록.

    axis ∈ {cycle, tail, kr}.
    """
    out = []
    for axis_value, m in sc_mod.BOOST_BY_CYCLE.items():
        for sc in m:
            out.append(("cycle", axis_value, sc))
    for axis_value, m in sc_mod.BOOST_BY_TAIL.items():
        for sc in m:
            out.append(("tail", axis_value, sc))
    for axis_value, m in sc_mod.BOOST_BY_KR.items():
        for sc in m:
            out.append(("kr", axis_value, sc))
    return out


# ── 값 patch helpers ──

def _patch_regime_weight(quadrant: str, factor: str, new_value: float):
    """REGIME_FACTOR_WEIGHTS[quadrant][factor] = new_value (정규화 X)."""
    orig = factor_scorer.REGIME_FACTOR_WEIGHTS[quadrant][factor]
    factor_scorer.REGIME_FACTOR_WEIGHTS[quadrant][factor] = new_value
    return orig


def _patch_boost(axis: str, axis_value: str, sub_category: str, new_value: float):
    table = {
        "cycle": sc_mod.BOOST_BY_CYCLE,
        "tail":  sc_mod.BOOST_BY_TAIL,
        "kr":    sc_mod.BOOST_BY_KR,
    }[axis]
    orig = table[axis_value][sub_category]
    table[axis_value][sub_category] = new_value
    return orig


# ── 평가 ──

@dataclass
class SensitivityRow:
    kind: str                    # "regime_weight" | "boost"
    key: tuple                   # (quadrant, factor) or (axis, axis_value, sub_category)
    orig_value: float
    delta_pct: float
    new_value: float
    baseline_pass: int
    perturbed_pass: int
    delta_pass: int              # perturbed - baseline (음수 = 악화)

    def to_dict(self):
        d = asdict(self)
        d["key"] = list(self.key)
        return d


def _total_pass(anchor_dir: Path, universe_path: str, cache_path: str | None) -> int:
    results = []
    for p in sorted(anchor_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            results.append(evaluate_anchor(p, universe_path=universe_path, cache_path=cache_path))
        except Exception as e:
            logger.warning("anchor %s failed: %s", p.name, e)
    return sum(r.pass_count for r in results)


def run_sensitivity(
    anchor_dir: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
    delta_pct: float = 20.0,
    include_regime: bool = True,
    include_boost: bool = True,
) -> list[SensitivityRow]:
    """각 weight/boost를 ±delta_pct% 흔들어서 anchor pass count 변화 측정."""
    anchor_dir = Path(anchor_dir)
    baseline = _total_pass(anchor_dir, universe_path, cache_path)
    logger.info("baseline pass count: %d", baseline)
    rows: list[SensitivityRow] = []

    def measure(kind, key, orig, patch_fn):
        for sign in (+1, -1):
            delta = sign * delta_pct / 100.0 * orig
            new_value = max(0.0, orig + delta)
            patch_fn(new_value)
            perturbed = _total_pass(anchor_dir, universe_path, cache_path)
            patch_fn(orig)   # 원복
            rows.append(SensitivityRow(
                kind=kind, key=key, orig_value=orig,
                delta_pct=sign * delta_pct, new_value=new_value,
                baseline_pass=baseline, perturbed_pass=perturbed,
                delta_pass=perturbed - baseline,
            ))

    if include_regime:
        for q, f in _regime_weight_keys():
            orig = factor_scorer.REGIME_FACTOR_WEIGHTS[q][f]
            measure("regime_weight", (q, f), orig,
                    lambda v, q=q, f=f: _patch_regime_weight(q, f, v))

    if include_boost:
        for axis, av, sc in _boost_keys():
            table = {"cycle": sc_mod.BOOST_BY_CYCLE, "tail": sc_mod.BOOST_BY_TAIL,
                     "kr": sc_mod.BOOST_BY_KR}[axis]
            orig = table[av][sc]
            measure("boost", (axis, av, sc), orig,
                    lambda v, axis=axis, av=av, sc=sc: _patch_boost(axis, av, sc, v))

    return rows


def format_report(rows: list[SensitivityRow]) -> str:
    sensitive = [r for r in rows if r.delta_pass != 0]
    out = []
    out.append(f"sensitivity rows: {len(rows)}, sensitive: {len(sensitive)}")
    out.append(f"")
    out.append(f"baseline pass: {rows[0].baseline_pass if rows else 0}")
    if not sensitive:
        out.append("  → 모든 weight/boost 값이 robust. anchor pass count 변동 없음.")
    else:
        out.append("\n--- 영향력 있는 perturbation (|Δpass| > 0) ---")
        sensitive.sort(key=lambda r: (-abs(r.delta_pass), r.kind))
        out.append(f"  {'kind':<14s} {'key':<50s} {'orig':>7s}  {'new':>7s}  {'Δ%':>5s}  {'Δpass':>6s}")
        for r in sensitive[:50]:
            key_str = "/".join(str(k) for k in r.key)
            out.append(f"  {r.kind:<14s} {key_str:<50s} {r.orig_value:>7.3f}  {r.new_value:>7.3f}  {r.delta_pct:>+5.0f}  {r.delta_pass:>+6d}")
        if len(sensitive) > 50:
            out.append(f"  ... ({len(sensitive) - 50} more)")
    return "\n".join(out)
