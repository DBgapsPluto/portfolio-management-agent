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
    "quick_think_llm": "gpt-5.4-mini",
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
        "us_5y5y_breakeven": 1,
        "us_michigan_1y": 15,   # 매월 중순 preliminary, 말 final
        "us_1y_yield": 1,
        # Tier-3 확장
        "usd_krw": 1,
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
        # Tier 0 additions (2026-05-28)
        "us_indpro": 17,                # IP released ~17th of month for prior month
        "us_real_pce": 30,              # BEA quarterly + 1 month lag
        "us_acm_term_premium_10y": 5,   # NY Fed weekly update
        "kr_reer": 17,                  # BIS monthly
        "ted_spread": 1,                # daily
    },
    # Tracing / observability
    "langsmith_enabled": os.getenv("LANGSMITH_TRACING", "false").lower() == "true",
    "langsmith_project": os.getenv("LANGSMITH_PROJECT", "db-gaps-agent"),
    # Tier 0: expanding-window z-baseline (Pesaran-Timmermann 1995). Default off
    # for backward compat — opt-in per run or backtest sweep.
    "use_dynamic_baseline": False,
    # Tier 3 legacy LLM overlay (default OFF — Stage 2 narrative overlay is preferred)
    "tier3_llm_overlay_enabled": False,
    "tier3_llm_k_samples": 5,
    "tier3_band": 0.05,
    "tier3_ewma_alpha": 0.10,
    "tier3_cred_cold_start": 0.30,
    # Stage 2/3 LLM-Quant blend rollout gates.
    # Modes: disabled | shadow | low_impact.
    # Stage 2 is default-on at low impact; bounded gates keep quant as the anchor.
    "stage2_llm_overlay_mode": "low_impact",
    "stage2_llm_k_samples": 3,
    "stage2_llm_max_mix": 0.20,
    "stage2_llm_band": 0.03,
    "stage3_llm_overlay_mode": "low_impact",
    "stage3_llm_k_samples": 2,
    "stage3_llm_candidate_boost_cap": 0.08,
    "stage3_llm_longlist_max_per_bucket": 8,
    "llm_overlay_temperature": 0.1,
    # Stage 2 allocation contract (prior → investability → feasible).
    "allocation_contract_enabled": True,
    "contract_skip_allocator_retry": True,
    "contract_overlay_risk_clip": True,
    # Stage 4: lens/aggregator가 빈 overlay를 낼 때 mandate cluster cap(0.25)으로 2차 최적화.
    "mandate_cluster_overlay_repair": True,
    "mandate_cluster_overlay_cap": 0.25,
    "mandate_cluster_overlay_cap_margin": 1e-4,
    "stage2_llm_min_novelty": 0.05,
    # Stage 2 anchor+tilt: regime/scenario bucket anchor + reduced factor tilt.
    "stage2_anchor_tilt_enabled": True,
    "stage2_anchor_regime_weight": 0.45,
    "stage2_anchor_scenario_weight": 0.55,
    "stage2_regime_modifier_pp": 0.02,
    "stage2_scenario_real_cap_goldilocks_pc": 0.14,
    "contract_single_etf_cap": 0.05,
    "contract_envelope_band_pp": 0.02,
    # Phase 2 — optional overrides (only read when allocation_contract is present).
    # Contract mode defaults: spill off, scenario boost off, HRP, cov proxy blend.
    # Do not set stage3_cash_spillover_enabled / stage3_scenario_boost_enabled here:
    # global False would break the legacy (non-contract) allocator path.
    "contract_optimizer_method": "hrp",
    "cov_factor_proxy_enabled": True,
    "cov_factor_proxy_blend": 0.25,
    # Stage 3 B: post-HRP mandate QP toward feasible_weights when risk>70% or mass gap.
    "stage3_post_hrp_mandate_qp": True,
})
