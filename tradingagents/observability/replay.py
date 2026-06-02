"""Stage-isolated replay — runs/{as_of}/*.json archive에서 state 복원하고
지정한 stage 노드 하나만 단독 실행.

목적: 한 stage를 수정한 뒤 전체 E2E를 재실행하지 않고 그 stage만 돌려서
산출물 diff를 빠르게 확인 (LLM 호출 1-2회).

흐름:
    1. TradingAgentsGraph(preset)로 노드들 빌드 (LLM 와이어링 위해).
    2. restore_state(as_of, stage) — base state + archive의 prior 산출물 overlay.
    3. run_stage(graph, stage, state) — wrapped node의 __wrapped__를 호출해
       baseline archive를 덮어쓰지 않고 raw 출력만 반환.

thin CLI는 scripts/replay_stage.py.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from tradingagents.agents.utils.agent_states import AgentState, _create_empty_state
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.schemas.mandate import ValidationReport
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet, WeightVector
from tradingagents.schemas.reports import (
    MacroReport, NewsReport, RiskReport, TechnicalReport,
)
from tradingagents.schemas.research import ResearchDecision
logger = logging.getLogger(__name__)


# 각 stage 노드가 state에서 .get()/[]로 읽는 키들 (노드 자체 출력은 제외).
# allocator/risk_debate/validator/portfolio_manager는 누적적으로 prior 산출물이 필요.
STAGE_PREREQUISITES: dict[str, list[str]] = {
    # Stage 1 analysts — base state만 있으면 됨
    "macro_quant": [],
    "market_risk": [],
    "technical": [],
    "macro_news": [],
    # Stage 2 research_debate — 4 analyst summaries + structured reports
    # (Stage 0 신호 cleaning이 macro_report.regime + risk_report.* + news_report +
    # technical_report 의 factor_panel 등 구조체 접근 필요. Sub-graph wrapper 폐기 후
    # research_manager 가 AgentState 직접 접근 — Issue A fix.)
    "research_debate": [
        "macro_summary", "risk_summary",
        "technical_summary", "news_summary",
        "macro_report", "risk_report",
        "news_report", "technical_report",
    ],
    # Stage 3 allocator (C5: technical_report.factor_panel + macro_report.regime +
    # risk_report.systemic_score 추가 — node 가 직접 접근)
    "allocator": [
        "macro_summary", "risk_summary",
        "technical_summary", "news_summary",
        "macro_report", "risk_report", "technical_report",
        "research_debate_summary", "research_decision", "bucket_target",
    ],
    # Stage 5 validator
    "validator": [
        "weight_vector", "candidate_set", "bucket_target",
    ],
    # Stage 6 portfolio_manager (전체 trace 필요)
    "portfolio_manager": [
        "macro_summary", "risk_summary",
        "technical_summary", "news_summary",
        "macro_report", "risk_report", "technical_report",
        "research_debate_summary", "research_decision", "bucket_target",
        "candidate_set", "weight_vector", "method_choice",
        "validation_report", "rebalance_mode",
    ],
}

# archive는 model_dump(mode="json")한 dict를 저장하므로, Pydantic 타입을 기대하는
# 노드를 위해 다시 model_validate로 hydrate.
SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "bucket_target": BucketTarget,
    "research_decision": ResearchDecision,
    "candidate_set": CandidateSet,
    "weight_vector": WeightVector,
    "validation_report": ValidationReport,
    "macro_report": MacroReport,
    "risk_report": RiskReport,
    "technical_report": TechnicalReport,
    "news_report": NewsReport,
}


def _archive_base(base: Path | None = None) -> Path:
    if base is not None:
        return Path(base)
    cache_dir = Path(DEFAULT_CONFIG["data_cache_dir"])
    return cache_dir.parent / "runs"


def _load_archived_key(run_dir: Path, key: str) -> Any:
    path = run_dir / f"{key}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("replay: load %s failed: %s", path, e)
        return None
    schema = SCHEMA_MAP.get(key)
    if schema is None:
        return raw
    try:
        return schema.model_validate(raw)
    except Exception as e:
        logger.warning(
            "replay: %s schema rehydrate failed (%s) — returning raw dict",
            key, e,
        )
        return raw


def restore_state(
    as_of_date: str,
    stage: str,
    universe_path: str,
    capital_krw: int = 1_000_000_000,
    preset_name: str = "db_gaps",
    base: Path | None = None,
) -> tuple[AgentState, list[str]]:
    """Base state + archive overlay. Returns (state, missing_keys)."""
    if stage not in STAGE_PREREQUISITES:
        raise ValueError(
            f"Unknown stage '{stage}'. "
            f"Known: {sorted(STAGE_PREREQUISITES)}"
        )
    state = _create_empty_state(
        as_of_date=as_of_date,
        universe_path=universe_path,
        capital_krw=capital_krw,
        preset_name=preset_name,
    )
    run_dir = _archive_base(base) / as_of_date
    if not run_dir.exists():
        raise FileNotFoundError(
            f"No archive directory: {run_dir}. "
            f"Run full pipeline once before replay."
        )

    missing: list[str] = []
    for key in STAGE_PREREQUISITES[stage]:
        value = _load_archived_key(run_dir, key)
        if value is None:
            missing.append(key)
            continue
        state[key] = value
    if missing:
        logger.warning(
            "replay: stage=%s missing prerequisites %s — node may fail",
            stage, missing,
        )
    return state, missing


def run_stage(
    graph,  # TradingAgentsGraph
    stage: str,
    state: AgentState,
    write_to_archive: bool = False,
) -> dict:
    """Invoke single stage node on the given state.

    write_to_archive=False (default): bypass archive_wrap via __wrapped__ →
    baseline runs/{as_of}/*.json 파일은 그대로. caller가 결과를 직접 저장.
    """
    if stage not in graph.nodes:
        raise KeyError(
            f"Stage '{stage}' not in graph.nodes. "
            f"Available: {sorted(graph.nodes)}"
        )
    node: Callable = graph.nodes[stage]
    if not write_to_archive:
        raw = getattr(node, "__wrapped__", None)
        if raw is None:
            logger.warning(
                "replay: stage=%s has no __wrapped__ (not archive-wrapped); "
                "calling node directly — output side-effects (files etc.) WILL fire",
                stage,
            )
            raw = node
        return raw(state)
    return node(state)
