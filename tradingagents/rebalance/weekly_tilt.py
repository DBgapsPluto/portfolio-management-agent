"""Weekly tilt — macro + risk only, ±5%p tilt around core."""
from dataclasses import dataclass, field
from datetime import date
import json
import logging
from pathlib import Path

from tradingagents.agents.analysts.macro_quant_analyst import (
    create_macro_quant_analyst,
)
from tradingagents.agents.analysts.market_risk_analyst import (
    create_market_risk_analyst,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

logger = logging.getLogger(__name__)


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
            new_quadrant = macro_result["macro_report"].regime.quadrant
            # C3: prefer the structured quadrant persisted at
            # allocation_attribution.step_a.quadrant (both BL and non-BL branches
            # set it) — the BL bucket_target.rationale never contains the quadrant
            # string, so the substring heuristic below always false-positived on
            # BL artifacts. Fall back to the substring check for pre-C3 artifacts.
            prev_quadrant = (
                (prev.get("allocation_attribution") or {}).get("step_a") or {}
            ).get("quadrant")
            if prev_quadrant:
                regime_changed = prev_quadrant != new_quadrant
            else:
                logger.warning(
                    "weekly_tilt: %s has no structured quadrant (pre-C3 artifact) "
                    "— falling back to substring heuristic", p,
                )
                prev_regime = prev.get("bucket_target", {}).get("rationale", "")
                if new_quadrant not in prev_regime:
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
