"""Side-effect import to register all skills with the global registry.

Import this module before calling get_skill() in app code.
"""
# Macro
from tradingagents.skills.macro import yield_curve  # noqa: F401
from tradingagents.skills.macro import inflation  # noqa: F401
from tradingagents.skills.macro import employment  # noqa: F401
from tradingagents.skills.macro import fred_fetcher  # noqa: F401
from tradingagents.skills.macro import ecos_fetcher  # noqa: F401
from tradingagents.skills.macro import divergence  # noqa: F401
from tradingagents.skills.macro import calendar  # noqa: F401
from tradingagents.skills.macro import regime_classifier  # noqa: F401

# Risk
from tradingagents.skills.risk import volatility  # noqa: F401
from tradingagents.skills.risk import credit_spread  # noqa: F401
from tradingagents.skills.risk import fear_greed  # noqa: F401
from tradingagents.skills.risk import breadth  # noqa: F401
from tradingagents.skills.risk import correlation_pca  # noqa: F401
from tradingagents.skills.risk import systemic_score  # noqa: F401

# Technical
from tradingagents.skills.technical import price_batch  # noqa: F401
from tradingagents.skills.technical import ta_indicators  # noqa: F401
from tradingagents.skills.technical import momentum_ranker  # noqa: F401
from tradingagents.skills.technical import trend_state  # noqa: F401
from tradingagents.skills.technical import correlation_cluster  # noqa: F401

# News
from tradingagents.skills.news import event_calendar  # noqa: F401
from tradingagents.skills.news import news_fetcher  # noqa: F401
from tradingagents.skills.news import impact_classifier  # noqa: F401
from tradingagents.skills.news import ranker  # noqa: F401

# Portfolio
from tradingagents.skills.portfolio import returns_matrix  # noqa: F401

# Mandate
from tradingagents.skills.mandate import universe_check  # noqa: F401
from tradingagents.skills.mandate import concentration_check  # noqa: F401
from tradingagents.skills.mandate import turnover_check  # noqa: F401
from tradingagents.skills.mandate import correlation_check  # noqa: F401
