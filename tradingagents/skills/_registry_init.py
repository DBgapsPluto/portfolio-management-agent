"""Side-effect import to register all skills with the global registry.

Import this module before calling get_skill() in app code.
"""
# Macro
from tradingagents.skills.macro import (  # noqa: F401
    yield_curve, inflation, employment,
    fred_fetcher, ecos_fetcher,
    divergence, calendar, regime_classifier,
)

# Risk
from tradingagents.skills.risk import (  # noqa: F401
    volatility, credit_spread, fear_greed,
    breadth, correlation_pca, systemic_score,
)

# Technical
from tradingagents.skills.technical import (  # noqa: F401
    price_batch, ta_indicators, momentum_ranker,
    trend_state, correlation_cluster,
)

# News
from tradingagents.skills.news import (  # noqa: F401
    event_calendar, news_fetcher, impact_classifier, ranker,
)

# Portfolio
from tradingagents.skills.portfolio import (  # noqa: F401
    candidate_selector, returns_matrix, optimizers, method_picker,
)

# Mandate
from tradingagents.skills.mandate import (  # noqa: F401
    universe_check, concentration_check,
    turnover_check, correlation_check,
)
