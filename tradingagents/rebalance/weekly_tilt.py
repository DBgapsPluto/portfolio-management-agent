"""Weekly tilt — macro + risk only, ±5%p tilt around core."""
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path

from tradingagents.agents.analysts.macro_quant_analyst import (
    create_macro_quant_analyst,
)
from tradingagents.agents.analysts.market_risk_analyst import (
    create_market_risk_analyst,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client


@dataclass
class WeeklyResult:
    regime_changed: bool
    tilt_proposed: dict[str, float] = field(default_factory=dict)
    summary: str = ""

    def __str__(self):
        return self.summary


def run(as_of: str | None = None,
        previous_path: str | None = None) -> WeeklyResult:
    deep = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["deep_think_llm"],
    ).get_llm()
    quick = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["quick_think_llm"],
    ).get_llm()

    target = as_of or date.today().isoformat()
    state = {"as_of_date": target}
    macro_node = create_macro_quant_analyst(quick, deep)
    risk_node = create_market_risk_analyst(quick, deep)

    macro_result = macro_node(state)
    risk_result = risk_node(state)

    regime_changed = False
    if previous_path:
        # B3 fix: callers pass `previous_path` as a directory (the seed artifact
        # dir, mirroring holdings._load_prev), but this read expects portfolio.json.
        # Resolve dir→portfolio.json and guard non-existence so the reassess tier
        # cannot crash with IsADirectoryError when it actually fires.
        p = Path(previous_path)
        if p.is_dir():
            p = p / "portfolio.json"
        if p.exists():
            prev = json.loads(p.read_text(encoding="utf-8"))
            prev_regime = prev.get("bucket_target", {}).get("rationale", "")
            if macro_result["macro_report"].regime.quadrant not in prev_regime:
                regime_changed = True

    tilt: dict[str, float] = {}
    if regime_changed:
        if "recession" in macro_result["macro_report"].regime.quadrant:
            tilt = {"risk_asset_delta": -0.05, "bond_delta": +0.05}
        else:
            tilt = {"risk_asset_delta": +0.05, "bond_delta": -0.05}

    summary = (
        f"[{target}] Regime: {macro_result['macro_report'].regime.quadrant} | "
        f"Risk score: {risk_result['risk_report'].systemic_score.score:.1f}/10 | "
        f"Regime changed: {regime_changed} | "
        f"Tilt: {tilt or '(none)'}"
    )
    return WeeklyResult(
        regime_changed=regime_changed, tilt_proposed=tilt, summary=summary,
    )
