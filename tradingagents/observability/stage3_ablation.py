"""Stage 3 ablation harness — 같은 state에 input 변형 후 ranking 차이 측정.

Variants (4개):
    baseline       — 현재 설정 그대로
    no_regime      — regime_confidence=0.0 → equal factor weights
    no_boost       — dominant_scenario=None → log_boost=0
    raw_factors    — 둘 다 off (factor z-score 합만)

Optimization은 돌리지 않음 (cap/bucket constraint 무시). candidate ranking 비교만:
    - Spearman: 같은 ticker pool 내 ranking 순위 상관
    - Jaccard:  선정된 ticker set의 교집합 / 합집합
    - top-N overlap: top per_bucket_n 안에 공통 ticker 수

이걸 보면 각 변형이 ranking에 얼마나 영향 미쳤는지 정량적으로 알 수 있음.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any

import pandas as pd

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import (
    BUCKET_TO_CATEGORIES, select_etf_candidates,
)
from tradingagents.skills.portfolio.factor_scorer import FactorPanel

logger = logging.getLogger(__name__)


# 변형별 input 오버라이드 정의. 각 변형은 baseline kwargs에서 일부를 덮음.
VARIANT_OVERRIDES: dict[str, dict[str, Any]] = {
    "baseline":    {},
    "no_regime":   {"regime_confidence": 0.0},
    "no_boost":    {"dominant_scenario": None},
    "raw_factors": {"regime_confidence": 0.0, "dominant_scenario": None},
}


@dataclass
class BucketComparison:
    bucket: str
    baseline_top_n: list[str]
    variant_top_n: list[str]
    common: list[str]
    only_baseline: list[str]
    only_variant: list[str]
    jaccard: float
    spearman: float | None
    # ranked_order 전체 비교 (선정 안 된 ticker 포함)
    baseline_ranked: list[str] = field(default_factory=list)
    variant_ranked: list[str] = field(default_factory=list)


@dataclass
class AblationReport:
    as_of_date: str
    variants: list[str]
    bucket_comparisons: dict[str, dict[str, BucketComparison]]  # variant → bucket → cmp
    method_comparison: dict[str, str]                            # variant → method
    summary: dict[str, dict[str, float]]                         # variant → metric → value

    def to_dict(self) -> dict:
        return {
            "as_of_date": self.as_of_date,
            "variants": self.variants,
            "method_comparison": self.method_comparison,
            "summary": self.summary,
            "bucket_comparisons": {
                v: {b: asdict(c) for b, c in buckets.items()}
                for v, buckets in self.bucket_comparisons.items()
            },
        }


def _spearman(a_ranks: list[str], b_ranks: list[str]) -> float | None:
    """Spearman rank correlation between two orderings over common tickers."""
    common = [t for t in a_ranks if t in b_ranks]
    if len(common) < 2:
        return None
    a_pos = {t: i for i, t in enumerate(a_ranks)}
    b_pos = {t: i for i, t in enumerate(b_ranks)}
    a_vec = pd.Series([a_pos[t] for t in common])
    b_vec = pd.Series([b_pos[t] for t in common])
    return float(a_vec.corr(b_vec, method="spearman"))


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def _extract_ranked(attribution: dict, bucket: str) -> list[str]:
    """attribution에서 해당 bucket의 ranked_order 추출.

    bond bucket은 bond_split 케이스에서 ranked_order가 sub_pools 안에 있음.
    """
    b = attribution.get("buckets", {}).get(bucket, {})
    if b.get("ranked_order"):
        return list(b["ranked_order"])
    # bond_split case
    sub_pools = b.get("sub_pools", {})
    out: list[str] = []
    for label in ("tips", "nominal"):
        sub = sub_pools.get(label, {})
        out.extend(sub.get("ranked_order", []) or [])
    return out


def run_ablation(
    *,
    universe: Universe,
    bucket_target: BucketTarget,
    as_of: date,
    returns: pd.DataFrame,
    factor_panel: dict[str, FactorPanel],
    baseline_kwargs: dict,
    variants: list[str] | None = None,
) -> AblationReport:
    """Run candidate selection for each variant, compare rankings.

    baseline_kwargs: select_etf_candidates에 그대로 넘길 kwargs (universe, bucket_target,
        as_of, returns, factor_panel은 별도 인자). 보통 dict(regime_quadrant=...,
        regime_confidence=..., dominant_scenario=..., per_bucket_n=..., ...).
    """
    if variants is None:
        variants = list(VARIANT_OVERRIDES.keys())
    unknown = set(variants) - set(VARIANT_OVERRIDES)
    if unknown:
        raise ValueError(f"Unknown variants: {sorted(unknown)}")

    # 각 변형마다 candidate 선정 실행
    results: dict[str, tuple[Any, dict]] = {}  # variant → (candidate_set, attribution)
    for v in variants:
        kwargs = dict(baseline_kwargs)
        kwargs.update(VARIANT_OVERRIDES[v])
        attr: dict = {}
        cs = select_etf_candidates(
            universe, bucket_target,
            as_of=as_of,
            returns=returns,
            factor_panel=factor_panel,
            attribution=attr,
            **kwargs,
        )
        results[v] = (cs, attr)

    # baseline 기준으로 변형별 bucket 비교
    if "baseline" not in results:
        raise ValueError("variants must include 'baseline' (anchor for comparison)")
    base_cs, base_attr = results["baseline"]

    bucket_comparisons: dict[str, dict[str, BucketComparison]] = {}
    summary: dict[str, dict[str, float]] = {}
    for v, (cs, attr) in results.items():
        if v == "baseline":
            continue
        per_bucket: dict[str, BucketComparison] = {}
        jaccards = []
        spearmans = []
        n_diff_picks_total = 0
        for bucket in BUCKET_TO_CATEGORIES.keys():
            base_picks = base_cs.bucket_to_tickers.get(bucket, [])
            var_picks = cs.bucket_to_tickers.get(bucket, [])
            base_ranked = _extract_ranked(base_attr, bucket)
            var_ranked = _extract_ranked(attr, bucket)
            common = sorted(set(base_picks) & set(var_picks))
            only_b = sorted(set(base_picks) - set(var_picks))
            only_v = sorted(set(var_picks) - set(base_picks))
            j = _jaccard(base_picks, var_picks)
            s = _spearman(base_ranked, var_ranked)
            per_bucket[bucket] = BucketComparison(
                bucket=bucket,
                baseline_top_n=list(base_picks),
                variant_top_n=list(var_picks),
                common=common,
                only_baseline=only_b,
                only_variant=only_v,
                jaccard=j,
                spearman=s,
                baseline_ranked=base_ranked,
                variant_ranked=var_ranked,
            )
            jaccards.append(j)
            if s is not None:
                spearmans.append(s)
            n_diff_picks_total += len(only_v) + len(only_b)
        bucket_comparisons[v] = per_bucket
        summary[v] = {
            "mean_jaccard":     float(pd.Series(jaccards).mean()) if jaccards else 1.0,
            "mean_spearman":    float(pd.Series(spearmans).mean()) if spearmans else 1.0,
            "total_diff_picks": n_diff_picks_total,
        }

    method_comparison = {v: "n/a — ranking only" for v in variants}

    return AblationReport(
        as_of_date=as_of.isoformat(),
        variants=variants,
        bucket_comparisons=bucket_comparisons,
        method_comparison=method_comparison,
        summary=summary,
    )
