from datetime import date

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet
from tradingagents.schemas.technical import ETFRanking
from tradingagents.skills.registry import register_skill


# Map BucketTarget fields to universe categories
BUCKET_TO_CATEGORIES = {
    "kr_equity": ["국내주식_지수", "국내주식_섹터"],
    "global_equity": ["해외주식_지수", "해외주식_섹터"],
    "fx_commodity": ["FX 및 원자재"],
    "bond": [
        "국내채권_종합", "국내채권_회사채",
        "해외채권_종합", "해외채권_회사채",
    ],
    "cash_mmf": ["금리연계형/초단기채권"],
}


@register_skill(name="select_etf_candidates", category="portfolio")
def select_etf_candidates(
    universe: Universe,
    bucket_target: BucketTarget,
    momentum_rankings: dict[str, list[ETFRanking]],
    as_of: date,
    min_aum_krw: float = 1_000_000_000_000,  # 1조원 floor
    per_bucket_n: int = 5,
) -> CandidateSet:
    """Filter universe by bucket target, AUM, momentum rank.

    Per D13: applies tradable_at(as_of) FIRST to filter ETFs not yet listed.
    """
    universe = universe.tradable_at(as_of)
    bucket_to_tickers: dict[str, list[str]] = {}

    for bucket_name, weight in [
        ("kr_equity", bucket_target.kr_equity),
        ("global_equity", bucket_target.global_equity),
        ("fx_commodity", bucket_target.fx_commodity),
        ("bond", bucket_target.bond),
        ("cash_mmf", bucket_target.cash_mmf),
    ]:
        if weight <= 0:
            bucket_to_tickers[bucket_name] = []
            continue

        cats = BUCKET_TO_CATEGORIES[bucket_name]
        eligible = [
            e for e in universe.etfs
            if e.category in cats and e.aum_krw >= min_aum_krw
        ]
        # Sort: prefer momentum-ranked tickers, fallback to AUM
        candidates_sorted = []
        for cat in cats:
            for r in momentum_rankings.get(cat, []):
                if any(e.ticker == r.ticker and e.aum_krw >= min_aum_krw for e in universe.etfs):
                    candidates_sorted.append(r.ticker)
        if not candidates_sorted:
            candidates_sorted = [e.ticker for e in sorted(eligible, key=lambda x: -x.aum_krw)]
        bucket_to_tickers[bucket_name] = candidates_sorted[:per_bucket_n]

    total = sum(len(v) for v in bucket_to_tickers.values())
    return CandidateSet(
        bucket_to_tickers=bucket_to_tickers,
        selection_criteria=f"AUM ≥ {min_aum_krw / 1e12:.1f}조원, momentum rank top {per_bucket_n} per category, tradable at {as_of}",
        total_candidates=max(total, 1),
    )
