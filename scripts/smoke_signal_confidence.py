"""라이브 스모크 (LLM 비용 0): 실제 매크로 fetch → compute_regime_confidence c 산출.

T5 Step 3 검증. classify_regime/narrative LLM 2곳만 스텁하고 모든 매크로 fetch는
실데이터로 구동 → fold-in 시점의 실제 snaps 캡처 → 4개 quadrant 전부에 대해 c +
축별 vote를 출력. "오늘 실데이터에서 c가 합리적 비퇴화 값을 내는가" 검증용.

Usage:
    PYTHONUTF8=1 ./.venv/Scripts/python.exe scripts/smoke_signal_confidence.py --as-of 2026-05-30
"""
from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.WARNING)


class _StubLLM:
    """narrative_prompt invoke 대체 (비용 0)."""
    def invoke(self, _prompt):
        return type("R", (), {"content": "[smoke stub narrative]"})()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-05-30")
    args = ap.parse_args()
    as_of = date.fromisoformat(args.as_of)

    from tradingagents.agents.analysts import macro_quant_analyst as mqa
    from tradingagents.skills.macro import regime_confidence as rc
    from tradingagents.schemas.macro import RegimeClassification

    captured = {}

    # classify_regime 스텁: 고정 quadrant, signal_confidence=None (fold-in이 덮어쓰는지 확인).
    def _fake_classify(quick_llm, deep_llm, **kwargs):
        return RegimeClassification(
            quadrant="growth_disinflation", confidence=0.7,
            drivers=["smoke"], reasoning="smoke stub", source_date=as_of,
            signal_confidence=None,
        )
    mqa.classify_regime = _fake_classify

    # fold-in 래핑: 실 snaps 캡처 후 진짜 fold-in 수행.
    _real_foldin = mqa._fold_in_signal_confidence
    def _wrapped_foldin(regime, snaps):
        captured["snaps"] = snaps
        return _real_foldin(regime, snaps)
    mqa._fold_in_signal_confidence = _wrapped_foldin

    node = mqa.create_macro_quant_analyst(_StubLLM(), _StubLLM())
    out = node({"as_of_date": args.as_of})

    regime = out["macro_report"].regime
    snaps = captured.get("snaps", {})

    print("=" * 64)
    print(f"LIVE SMOKE — signal_confidence (as_of={as_of})")
    print("=" * 64)

    # snapshot fetch 성공/실패(staleness) 요약
    print("\n[snapshot freshness]")
    for k in mqa._REGIME_SNAP_KEYS:
        s = snaps.get(k)
        if s is None:
            print(f"  {k:22s} = None (abstain)")
        else:
            sd = getattr(s, "staleness_days", "?")
            fresh = rc._fresh(s)
            print(f"  {k:22s} = staleness={sd!s:>4}  fresh={fresh}")

    # 축별 vote (부호 집계)
    gv = rc._growth_votes(snaps)
    iv = rc._inflation_votes(snaps)
    print(f"\n[votes] growth={gv} (n={len(gv)})  inflation={iv} (n={len(iv)})")

    # 4개 quadrant 전부에 대해 c
    print("\n[c per quadrant]")
    for q in ("growth_inflation", "growth_disinflation",
              "recession_inflation", "recession_disinflation"):
        c = rc.compute_regime_confidence(snaps, q)
        print(f"  {q:24s} c = {c:.4f}")

    print(f"\n[fold-in result] regime.quadrant={regime.quadrant}  "
          f"signal_confidence={regime.signal_confidence:.4f}  "
          f"(LLM self-reported confidence={regime.confidence})")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
