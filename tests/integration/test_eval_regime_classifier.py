"""Eval — classify_regime accuracy across 8 historical regime cases.

Per design §15, this is the LLM eval that should be re-run when classifier
prompts change.

Skipped by default (requires API access). Run with:
    pytest -m eval tests/integration/test_eval_regime_classifier.py
"""
import pytest

from tradingagents.skills.macro.regime_classifier import RegimeClassifier


HISTORICAL_CASES = [
    ("2008-09 Lehman, deep recession", {
        "spread_10y_2y_bps": -50.0, "inverted_days_count": 200,
        "cpi_yoy": 4.5, "momentum_3mo": -2.0, "accelerating": False,
        "unemployment_rate": 6.8, "sahm_rule_triggered": True,
    }, "recession_disinflation"),
    ("2022-06 peak inflation, growth", {
        "spread_10y_2y_bps": 10.0, "inverted_days_count": 0,
        "cpi_yoy": 9.1, "momentum_3mo": 8.0, "accelerating": True,
        "unemployment_rate": 3.6, "sahm_rule_triggered": False,
    }, "growth_inflation"),
    ("2020-04 COVID recession + supply inflation", {
        "spread_10y_2y_bps": 50.0, "inverted_days_count": 0,
        "cpi_yoy": 0.3, "momentum_3mo": -1.0, "accelerating": False,
        "unemployment_rate": 14.7, "sahm_rule_triggered": True,
    }, "recession_disinflation"),
    ("2017-Q3 Goldilocks", {
        "spread_10y_2y_bps": 80.0, "inverted_days_count": 0,
        "cpi_yoy": 2.0, "momentum_3mo": 1.8, "accelerating": False,
        "unemployment_rate": 4.2, "sahm_rule_triggered": False,
    }, "growth_disinflation"),
    ("1973-12 stagflation", {
        "spread_10y_2y_bps": -20.0, "inverted_days_count": 90,
        "cpi_yoy": 8.7, "momentum_3mo": 9.0, "accelerating": True,
        "unemployment_rate": 4.9, "sahm_rule_triggered": True,
    }, "recession_inflation"),
    ("2007-12 pre-GFC late cycle", {
        "spread_10y_2y_bps": 5.0, "inverted_days_count": 30,
        "cpi_yoy": 4.1, "momentum_3mo": 4.5, "accelerating": True,
        "unemployment_rate": 5.0, "sahm_rule_triggered": False,
    }, "growth_inflation"),
    ("2014-12 disinflation expansion", {
        "spread_10y_2y_bps": 150.0, "inverted_days_count": 0,
        "cpi_yoy": 0.8, "momentum_3mo": -1.5, "accelerating": False,
        "unemployment_rate": 5.6, "sahm_rule_triggered": False,
    }, "growth_disinflation"),
    ("2026-05 (current) inverted+rising-unemployment", {
        "spread_10y_2y_bps": -10.0, "inverted_days_count": 120,
        "cpi_yoy": 2.8, "momentum_3mo": 2.0, "accelerating": False,
        "unemployment_rate": 4.5, "sahm_rule_triggered": True,
    }, "recession_disinflation"),
]


@pytest.mark.eval
@pytest.mark.parametrize("case_name,inputs,expected", HISTORICAL_CASES)
def test_regime_classifier_accuracy(case_name, inputs, expected):
    """Real-LLM eval. Skipped by default (mark `eval`)."""
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.llm_clients import create_llm_client

    quick = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["quick_think_llm"],
    ).get_llm()
    deep = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["deep_think_llm"],
    ).get_llm()

    clf = RegimeClassifier(quick, deep)
    result = clf.invoke(**inputs)
    assert result.quadrant == expected, (
        f"{case_name}: got {result.quadrant}, expected {expected}"
    )
    assert result.confidence >= 0.7, (
        f"{case_name}: confidence too low {result.confidence}"
    )
