"""daily 오케스트레이션 — reprice → triggers → tier target → run_rebalance (스펙 §5).

LLM 0. correlation cluster 는 artifacts 에서 최신 영속화 값을 재사용한다.
"""
import json
import logging
from datetime import date
from pathlib import Path

from tradingagents.rebalance.pricing import fetch_current_prices  # noqa: F401 (monkeypatch)
from tradingagents.rebalance.holdings import load_prev_holdings
from tradingagents.dataflows.universe import load_universe  # noqa: F401 (monkeypatch)
from tradingagents.rebalance.engine import reprice_holdings, make_is_risk, run_rebalance
from tradingagents.rebalance import daily_triggers
from tradingagents.rebalance.triggers import evaluate_drift, route_tier
from tradingagents.rebalance.overlay import defensive_overlay, risk_on_overlay
from tradingagents.rebalance.reassess import reassess_target
from tradingagents.rebalance import crisis_policy
from tradingagents.skills.mandate.category_repair import repair_category_caps
from tradingagents.skills.mandate.risk_repair import repair_risk_cap
from tradingagents.skills.mandate.concentration_check import CATEGORY_CAPS, FLOAT_TOLERANCE
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.rebalance.types import RebalanceResult
from tradingagents.monitor.notify import send_rebalance_alert
from tradingagents.schemas.technical import Cluster

logger = logging.getLogger(__name__)

# B4: state files a daily run may read its prev_target / clusters from. The full
# pipeline writes portfolio.json; a daily run writes the slim daily_state.json so
# a chain of daily-only days does not degrade prev_target/clusters to empty.
_STATE_FILES: tuple[str, ...] = ("portfolio.json", "daily_state.json")


def _load_clusters(previous_path: str | None, artifacts_dir: str | None = None) -> list[Cluster]:
    """Return most-recent persisted Cluster list from artifact state files.

    Priority: scan artifacts/<date>/{portfolio.json,daily_state.json} newest-first
    for a non-empty correlation_clusters list; deserialize each dict → Cluster(**d).
    Falls back to [] with a warning when nothing is found.
    """
    search_dirs: list[Path] = []
    base = Path(artifacts_dir or DEFAULT_CONFIG.get("artifacts_dir", "./artifacts"))
    if base.exists():
        # date-named subdirs, sorted newest-first
        search_dirs = sorted(
            (d for d in base.iterdir() if d.is_dir()),
            key=lambda d: d.name, reverse=True,
        )
    # also check the previous_path directory itself (may hold a portfolio.json)
    if previous_path:
        prev = Path(previous_path)
        if prev not in search_dirs and prev.is_dir():
            search_dirs.insert(0, prev)

    for d in search_dirs:
        for fname in _STATE_FILES:
            pj = d / fname
            if not pj.exists():
                continue
            try:
                raw = json.loads(pj.read_text(encoding="utf-8"))
                cc = raw.get("correlation_clusters", [])
                if cc:
                    clusters = [Cluster(**item) for item in cc]
                    logger.debug("daily: clusters 재사용 ← %s (%d개)", pj, len(clusters))
                    return clusters
            except Exception as exc:  # noqa: BLE001
                logger.debug("daily: %s 읽기 실패(%s) — 건너뜀: %s", fname, pj, exc)

    logger.warning("daily: clusters 확보 실패 — correlation 검증 생략")
    return []


def _load_prev(previous_path: str | None) -> tuple[dict, int, dict]:
    """Return (prev_qty, prev_cash, prev_target_weights).

    prev_target is read from the prior run's state file 'weights' key —
    portfolio.json (full pipeline) or daily_state.json (a prior daily run, B4).
    """
    if not previous_path:
        return {}, 0, {}
    prev_qty, prev_cash = load_prev_holdings(Path(previous_path))
    prev_target: dict[str, float] = {}
    for fname in _STATE_FILES:
        pj = Path(previous_path) / fname
        if pj.exists():
            prev_target = json.loads(pj.read_text(encoding="utf-8")).get("weights", {})
            if prev_target:
                break
    return prev_qty, prev_cash, prev_target


def _persist_daily_state(out_dir: Path, res, clusters) -> None:
    """B4: persist realized weights + reused clusters so the NEXT daily run has a
    non-empty prev_target (drift evaluation, defensive-overlay anchor) and the
    correlation clusters. Without this, a chain of daily-only days degrades
    prev_target/clusters to {}/[] (the daily path never wrote portfolio.json).
    """
    try:
        state = {
            "weights": getattr(res, "realized_weights", None) or {},
            "correlation_clusters": [c.model_dump() for c in (clusters or [])],
        }
        (out_dir / "daily_state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("daily: daily_state.json 기록 실패 — 건너뜀: %s", exc)


def _eval_triggers(
    *, current: dict, prev_target: dict, dials: dict,
    as_of: str, previous_path: str | None, is_risk,
) -> tuple[str, dict, bool]:
    """Return (tier, trigger_ctx, reassess_fired)."""
    trig = daily_triggers.run(as_of=as_of, portfolio_path=previous_path, current_weights=current)
    drift = evaluate_drift(current, prev_target, dials, is_risk)
    reassess_fired = daily_triggers.evaluate_reassess(trig.context)
    tier = route_tier(trig.suggested_action, drift, reassess_fired)
    return (
        tier,
        {"fired": trig.fired, "suggested_action": trig.suggested_action, "drift": drift},
        reassess_fired,
    )


def run(as_of: str, previous_path: str | None = None, out_dir=None) -> RebalanceResult:
    """Daily orchestration entry point."""
    capital: int = DEFAULT_CONFIG.get("capital_krw", 1_000_000_000)
    dials: dict = DEFAULT_CONFIG.get("rebalance", {})

    prev_qty, prev_cash, prev_target = _load_prev(previous_path)
    prices = fetch_current_prices(date.fromisoformat(as_of))
    # 현재가 부재(KRX 데이터 미제공/휴장+지연) → 보유 재평가 불가 → 거래계획 생성 시
    # 전액현금 빈 산출물이 나오고 그게 다음 seed 를 오염시킨다. 산출물을 만들지 말고 skip.
    if not prices:
        logger.warning(
            "daily: 현재가 fetch 실패(KRX 데이터 부재) — 리밸런싱 skip, 산출물 미생성 (as_of=%s)",
            as_of,
        )
        return RebalanceResult(
            as_of=as_of, tier="skipped",
            trigger={"reason": "no_current_prices"},
        )
    universe = load_universe(Path(DEFAULT_CONFIG.get("universe_path", "./data/universe.json")))
    is_risk = make_is_risk(universe)
    # F1: 위기 전용 sell/dest 적격성(crisis_policy) — is_risk(공식 8-bucket) 는 불변, 이 안에서만
    # 개별 티커의 매도/목적지 적격성을 좁힌다. overlay·reassess·수선 루프가 공유.
    sell_ok = crisis_policy.make_sell_ok(universe)
    dest_ok = crisis_policy.make_dest_ok(universe)
    current = reprice_holdings(prev_qty, prev_cash, prices)

    tier, trig_ctx, reassess_fired = _eval_triggers(
        current=current, prev_target=prev_target, dials=dials,
        as_of=as_of, previous_path=previous_path, is_risk=is_risk,
    )

    # Determine target weights per tier
    defensive_target: float = dials.get("defensive_target", 0.55)
    step: float = dials.get("reassess_tilt_step", 0.05)
    target: dict | None = None

    if tier in ("event:emergency_defensive", "drift:defensive"):
        target = defensive_overlay(prev_target or current, is_risk, defensive_target,
                                   sell_ok=sell_ok, dest_ok=dest_ok)
    elif tier == "event:risk_on":
        target = risk_on_overlay(prev_target or current, is_risk, step)
    elif tier == "drift:rebalance":
        target = prev_target or current     # restore previous target
    elif tier == "reassess":
        target = reassess_target(current, is_risk, as_of, previous_path, sell_ok=sell_ok)

    # Monitoring-only tiers or no actionable target
    if tier in ("none", "alert") or target is None:
        return RebalanceResult(
            as_of=as_of,
            tier="none" if target is None else tier,
            current_weights=current,
            trigger=trig_ctx,
        )

    # 세부자산(category)+위험자산 cap 강제 (대회 §2.2) — overlay/reassess 는 category 무인지.
    # category↔risk 교대 3회 수렴. 정수 qty 반올림 후 realized 는 engine 이 재검증.
    _cat_of = {e.ticker: e.category for e in universe.etfs}
    _is_defensive_tier = tier in ("event:emergency_defensive", "drift:defensive")
    # F1/B4(다운스트림 수선 간섭 방어, MF-8): defensive 경로에서 category 수선의 물채움을
    # (안전자산 ∩ 정책 목적지)로 한정한다. 제한 없이 두면 category 수선이 위험자산의
    # single-cap 헤드룸에도 자유롭게 물을 채워(risk-blind) defensive_overlay 가 방금 확보한
    # defensive_target 을 되돌린다(실측: overlay 직후 risk=0.30 → 수선 후 risk=0.375).
    _recipient_ok = (lambda t: not is_risk(t) and dest_ok(t)) if _is_defensive_tier else None
    for _ in range(3):
        target = repair_category_caps(target, _cat_of, CATEGORY_CAPS, recipient_ok=_recipient_ok)
        target = repair_risk_cap(target, is_risk)

    if _is_defensive_tier:
        risk_after_repair = sum(w for t, w in target.items() if is_risk(t))
        if risk_after_repair > defensive_target + FLOAT_TOLERANCE:
            # 수렴 가드(overlay 재적용 상한 1회, 총 2회): recipient_ok 로도 못 막은 잔여
            # 초과(예: 정책 목적지 자체가 포화)를 overlay 로 한 번 더 정리한다.
            target = defensive_overlay(target, is_risk, defensive_target,
                                       sell_ok=sell_ok, dest_ok=dest_ok)
            target = repair_category_caps(target, _cat_of, CATEGORY_CAPS,
                                          recipient_ok=_recipient_ok)
            target = repair_risk_cap(target, is_risk)

    resolved_out = (
        Path(out_dir)
        if out_dir
        else Path(DEFAULT_CONFIG.get("artifacts_dir", "./artifacts")) / as_of
    )
    resolved_out.mkdir(parents=True, exist_ok=True)

    clusters = _load_clusters(previous_path)

    res = run_rebalance(
        as_of=as_of, tier=tier, capital=capital,
        prev_qty=prev_qty, prev_cash=prev_cash,
        target_weights=target, prices=prices, universe=universe,
        clusters=clusters, previous_weights=prev_target, dials=dials,
        out_dir=resolved_out, previous_path=previous_path or "",
        deep_llm=None,
    )
    res.trigger = trig_ctx
    _persist_daily_state(resolved_out, res, clusters)
    if res.plan:
        top = [f"{tl.ticker} {tl.action} {tl.delta_qty}"
               for tl in res.plan if tl.action != "HOLD"][:10]
        passed = res.validation.passed if res.validation else "n/a"
        send_rebalance_alert(tier=res.tier, action=res.tier,
                             summary=f"turnover {res.turnover:.2%}, passed={passed}",
                             top_trades=top)
    return res
