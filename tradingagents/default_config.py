import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Stage 2 (research) — Phase 1 단일 estimator 사용 (round 개념 없음).
    # 아래 키들은 legacy v0.2 upstream (graph/setup.py)에서만 참조.
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Rebalancing engine dials
    "rebalance": {
        "no_trade_band": 0.005,
        "single_etf_abs_cap": 0.19,
        "risk_asset_abs_cap": 0.68,
        "turnover_floor_monthly": 0.10,
        "single_etf_rel_band": 0.05,
        "defensive_target": 0.55,
        "reassess_tilt_step": 0.05,
    },
}

DEFAULT_CONFIG.update({
    # DB GAPS 설정
    "preset_dir": "./presets",
    "prompt_dir": "./prompts",
    "universe_path": "./data/universe.json",
    "artifacts_dir": "./artifacts",
    "default_preset": "db_gaps",
    "subagent_model_policy": {
        "classify_regime": "deep",
        "score_systemic_risk": "deep",
        "pick_optimization_method": "deep",
        "classify_event_impact": "quick",
    },
    # API 키
    "fred_api_key": os.getenv("FRED_API_KEY"),
    "ecos_api_key": os.getenv("ECOS_API_KEY"),
    "tradingeconomics_key": os.getenv("TRADINGECONOMICS_KEY"),
    # Cache
    "etf_price_cache_path": os.path.join(_TRADINGAGENTS_HOME, "cache", "etf_prices.parquet"),
    "macro_cache_dir": os.path.join(_TRADINGAGENTS_HOME, "cache", "macro"),
    "cache_staleness_d1": 1,
    "cache_staleness_d7": 7,
    "cache_staleness_d30": 30,
    # Macro data publication lag (look-ahead bias prevention)
    "publication_lag_days": {
        "us_cpi": 15,
        "us_core_cpi": 15,
        "us_pce": 30,           # PCE는 매월 마지막주 발표 (CPI보다 2주 늦음)
        "us_core_pce": 30,
        "us_unrate": 7,
        "us_payems": 7,
        "us_lfpr": 7,
        # JOLTS는 매월 첫째 주 발표 (2개월 lag — 2025년 2월 데이터가 4월 발표).
        "us_jolts_openings": 45,
        "us_jolts_quits": 45,
        "us_jolts_hires": 45,
        "us_10y": 1, "us_2y": 1, "us_3m": 1,
        # 2026-05-23 C4: Treasury 5y/30y (F4 term_premium long-end slope)
        "us_5y": 1, "us_30y": 1,
        "us_policy_rate": 1,
        "us_ig_oas": 1, "us_hy_oas": 1,
        "vix_close": 1,
        "fed_balance_sheet": 8,
        "kr_base_rate": 0,
        "kr_cpi": 5,
        "kr_m2": 60,
        "kr_export": 1,
        "kr_import": 1,
        "kr_industrial_production": 30,
        "kr_unrate": 15,
        # Tier-1 확장
        "us_cfnai": 25,         # CFNAI released ~ 4주차 (전월분)
        "us_cfnai_ma3": 25,
        "us_gdp_nowcast": 1,    # GDPNow는 거의 실시간 (주 2회 갱신)
        "kr_cli": 30,           # 선행지수 익월말 공표
        "kr_bsi_mfg": 5,        # BSI 익월초 공표
        # Tier-2 확장
        "us_nfci": 7,           # NFCI 주간 공표 (수요일, 직전 주 종가 기준)
        "us_anfci": 7,
        "us_mortgage_30y": 7,
        "us_5y5y_breakeven": 1,
        "us_michigan_1y": 15,   # 매월 중순 preliminary, 말 final
        "us_1y_yield": 1,
        # Tier-3 확장
        "usd_krw": 1,
        "usd_jpy": 1,
        "dxy": 1,
        "china_cli": 35,        # OECD CLI 익월말 공표
        # Tier-4 확장
        "us_epu": 5,            # EPU 익월초 공표
        "global_epu": 30,       # Global EPU 익월말 공표
        "vvix": 1,
        "move": 1,
        # market_risk Tier-1 확장
        "vix_3m": 1,
        "vxn": 1,
        # market_risk Tier-2 확장
        "us_tips_10y": 1,
        "us_tips_5y": 1,
        "us_sofr": 1,
        "us_3m_tbill": 1,
        "us_aaa_oas": 1,
        "us_bbb_oas": 1,
        # market_risk Tier-3 확장 (KR-specific)
        "kr_treasury_3y": 1,
        "kr_treasury_10y": 1,
        "kr_corp_aa_3y": 1,
        "kr_treasury_5y": 1,
        "kr_treasury_30y": 1,
        "kr_corp_bbb_3y": 1,
        "kr_cd91": 1,
        # Tier 0 additions (2026-05-28)
        "us_indpro": 17,                # IP released ~17th of month for prior month
        "us_real_pce": 30,              # BEA quarterly + 1 month lag
        "us_acm_term_premium_10y": 5,   # NY Fed weekly update
        "kr_reer": 17,                  # BIS monthly
        "ted_spread": 1,                # daily
        # Plan B fold-in (2026-06-09)
        "us_chip_ppi": 30,              # Semiconductor PPI (monthly)
        "kr_export_semi": 30,           # Semiconductor exports (monthly)
        "kr_export_battery": 30,        # Battery exports (monthly)
        "kr_export_display": 30,        # Display exports (monthly)
        "kr_export_chem": 30,           # Chemical exports (monthly)
        "kr_export_steel": 30,          # Steel exports (monthly)
    },
    # Tracing / observability
    "langsmith_enabled": os.getenv("LANGSMITH_TRACING", "false").lower() == "true",
    "langsmith_project": os.getenv("LANGSMITH_PROJECT", "db-gaps-agent"),
    # Tier 0: expanding-window z-baseline (Pesaran-Timmermann 1995). Default off
    # for backward compat — opt-in per run or backtest sweep.
    "use_dynamic_baseline": False,
})
