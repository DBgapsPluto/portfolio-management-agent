"""24-cell scenario framework — axis-driven algorithmic playbook.

7-scenario hand-coded dict → 3-axis 함수로 대체. 24 cell의 playbook을
(equity_base, kr_share, fx_commodity, bond, cash_residual) 5개 파라미터에서
산출하므로 24×5=120개 숫자 하드코딩 X.

Cell key 형식: {cycle}_{tail}_{kr}, 예 "A_N_F" = goldilocks classic.
"""
from tradingagents.schemas.research import (
    ALL_CELLS, CYCLE_CODES, CycleQuadrant, KRDirection, TAIL_CODES, TRANSIENT_CELLS,
    TailState, cell_key, parse_cell_key,
)


# === Cycle 정의 텍스트 (LLM prompt 주입용) ===
CYCLE_DEFINITIONS: dict[CycleQuadrant, str] = {
    "A": (
        "growth + disinflation. macro_quant regime=growth_disinflation, "
        "CPI disinflation, GDPNow positive, broad equity risk-on. "
        "참고: 1995, 2017, 2024H1"
    ),
    "B": (
        "growth + inflation. macro_quant regime=growth_inflation, "
        "CPI persistent/accelerating, real_yields tight, but GDP positive. "
        "참고: 1972, 2021H2"
    ),
    "C": (
        "recession + disinflation. macro_quant regime=recession_disinflation, "
        "Sahm rule trigger, CFNAI weak, CPI cooling. credit은 stable이면 C-N. "
        "참고: 1990-91, 2001"
    ),
    "D": (
        "recession + inflation (classic stagflation). regime=recession_inflation, "
        "growth slowing while inflation sticky. real_yields very_tight. "
        "참고: 1973-80, 2022-23 일부"
    ),
}

TAIL_DEFINITIONS: dict[TailState, str] = {
    "N": (
        "normal — Conditional Stress Surprise aggregate_z < +1.0. "
        "D1 baseline 대비 평소 수준."
    ),
    "T": (
        "tail — Conditional Stress Surprise aggregate_z ≥ +1.0 (D1 conditional "
        "surprise). 절대값 HY OAS가 아니라 cycle-baseline 대비 추가 widening. "
        "참고: 2008 Q4 (C-T), 1998 LTCM (A-T), late 1970s 일부 (D-T)"
    ),
}

KR_DEFINITIONS: dict[KRDirection, str] = {
    "F": "follow — KR가 글로벌 cycle을 따라감 (default).",
    "boom": (
        "KR boom decoupling — KR Residual Signals의 kr_boom_score ≥ +1.0. "
        "kr_corp_spread_residual < -30bps (KR 신용 양호), foreign flow z>+1, "
        "kr_export accelerating. cycle 신호가 아니라 KR-specific residual만 사용."
    ),
    "stress": (
        "KR stress decoupling — kr_stress_score ≥ +1.0. "
        "kr_corp_spread_residual > +50bps (KR 자체 widening), margin_z<-1, "
        "foreign flow z<-1. kr_yield_curve inversion은 cycle proxy라 미사용."
    ),
}


# === Playbook 함수 (axes → 5-bucket dict) ===

# equity_total: (cycle, tail) → equity 총량.
# 값들은 1991-2024 backtest로 informed: A_T eq 0.30→0.40 (Sharpe 1.74 backtest).
# 나머지 cell은 backtest sample 부족/recency bias로 hand judgment 유지.
_EQUITY_TOTAL: dict[tuple[CycleQuadrant, TailState], float] = {
    ("A", "N"): 0.65,  # goldilocks classic (backtest n=42 confirmed)
    ("A", "T"): 0.40,  # ↑ 1998 LTCM recovery; backtest n=16 Sharpe 1.74
    ("B", "N"): 0.30,  # overheating; backtest recency-biased (2022) ignored
    ("B", "T"): 0.15,  # transient
    ("C", "N"): 0.20,  # mild recession
    ("C", "T"): 0.10,  # 2008 Q4-like
    ("D", "N"): 0.15,  # stagflation classic (backtest n=2 numerical artifact)
    ("D", "T"): 0.10,  # severe stagflation + credit
}

# KR vs Global split. Backtest gave 0/100 corners (overfit); informed compromise.
_KR_SHARE: dict[KRDirection, tuple[float, float]] = {
    "F":      (0.30, 0.70),  # was 0.35/0.65; backtest 0/100 무시, soft nudge
    "boom":   (0.65, 0.35),  # was 0.70; 집중 risk 완화
    "stress": (0.10, 0.90),  # 유지 (backtest 동의)
}

# fx_commodity (inflation flag → tail level). backtest는 fx 빼는 corner solution
# 자주 도출 (Sharpe 단기 최대화 vs 다양화 우선 충돌) → hand judgment 유지.
_FX_COMMODITY: dict[tuple[str, TailState], float] = {
    ("disinflation", "N"): 0.05,
    ("disinflation", "T"): 0.10,  # gold flight
    ("inflation",    "N"): 0.30,
    ("inflation",    "T"): 0.35,  # commodity + gold
}

# bond: (cycle, tail) → bond total. backtest 방향 신호 수용 (A_N/A_T/C_N/C_T 모두 +5pt).
_BOND_TOTAL: dict[tuple[CycleQuadrant, TailState], float] = {
    ("A", "N"): 0.30,  # ↑ was 0.25; backtest n=42 0.35
    ("A", "T"): 0.45,  # ↑ was 0.40; backtest n=16 0.55
    ("B", "N"): 0.20,  # B는 backtest 신뢰 X
    ("B", "T"): 0.30,
    ("C", "N"): 0.60,  # ↑ was 0.55; backtest n=3 0.70
    ("C", "T"): 0.55,  # ↑ was 0.40; backtest n=2 0.75 — 2008Q4 lesson
    ("D", "N"): 0.20,
    ("D", "T"): 0.35,
}

# bond_tips_share: backtest는 TIPS-heavy 일관 산출(2004+ 단기 sample 한계).
# disinflation에서 0.05→0.15로 다양화 차원 소폭 ↑. inflation은 거의 그대로.
_BOND_TIPS_SHARE: dict[str, float] = {
    "disinflation": 0.15,  # was 0.05
    "inflation":    0.80,  # was 0.75
}


def _inflation_flag(cycle: CycleQuadrant) -> str:
    return "inflation" if cycle in ("B", "D") else "disinflation"


def make_playbook(cycle: CycleQuadrant, tail: TailState, kr: KRDirection) -> dict[str, float]:
    """24-cell의 한 cell에 대한 5-bucket playbook 산출.

    Invariant: sum = 1.0, risk_asset (kr+gl+fx) ≤ 0.70.
    """
    equity_total = _EQUITY_TOTAL[(cycle, tail)]
    kr_share, gl_share = _KR_SHARE[kr]
    kr_eq = equity_total * kr_share
    gl_eq = equity_total * gl_share

    infl = _inflation_flag(cycle)
    fx_commodity = _FX_COMMODITY[(infl, tail)]
    bond = _BOND_TOTAL[(cycle, tail)]

    cash = 1.0 - kr_eq - gl_eq - fx_commodity - bond
    # 부동소수 음수 방어 (이론적으로 발생 안 함)
    if cash < 0:
        cash = 0.0
    return {
        "kr_equity": kr_eq,
        "global_equity": gl_eq,
        "fx_commodity": fx_commodity,
        "bond": bond,
        "cash_mmf": cash,
    }


def make_bond_tips_share(cycle: CycleQuadrant, tail: TailState, kr: KRDirection) -> float:
    """Bond bucket 내부 inflation_linked 비율 — inflation cell만 높음."""
    return _BOND_TIPS_SHARE[_inflation_flag(cycle)]


def make_cell_definition(cycle: CycleQuadrant, tail: TailState, kr: KRDirection) -> str:
    """LLM prompt 주입용 cell 설명 (1줄)."""
    key = cell_key(cycle, tail, kr)
    cycle_short = {"A": "growth+disinfl", "B": "growth+inflation",
                   "C": "recession+disinfl", "D": "stagflation"}[cycle]
    tail_short = {"N": "normal", "T": "TAIL"}[tail]
    kr_short = {"F": "KR-follow", "boom": "KR-boom", "stress": "KR-stress"}[kr]
    transient_note = " [TRANSIENT, expect very low P]" if key in TRANSIENT_CELLS else ""
    return f"{key}: {cycle_short} × {tail_short} × {kr_short}{transient_note}"


def all_cells_definition_block() -> str:
    """24 cell 전체를 한 텍스트 블록으로 — prompt 주입용."""
    lines = []
    for c in CYCLE_CODES:
        lines.append(f"=== Cycle {c} ({CYCLE_DEFINITIONS[c]}) ===")
        for t in TAIL_CODES:
            for k in ("F", "boom", "stress"):
                lines.append("  " + make_cell_definition(c, t, k))
    return "\n".join(lines)


# === Self-validation (모듈 import 시 보장) ===
_BUCKET_KEYS = ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf")


def _validate() -> None:
    for key in ALL_CELLS:
        c, t, k = parse_cell_key(key)
        pb = make_playbook(c, t, k)
        if set(pb.keys()) != set(_BUCKET_KEYS):
            raise ValueError(f"{key}: bucket keys mismatch")
        total = sum(pb.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"{key}: weights sum {total} != 1.0")
        risk = pb["kr_equity"] + pb["global_equity"] + pb["fx_commodity"]
        if risk > 0.70 + 1e-6:
            raise ValueError(f"{key}: 위험자산 {risk:.3f} > 0.70 (mandate §2.2)")
        tips = make_bond_tips_share(c, t, k)
        if not (0.0 <= tips <= 1.0):
            raise ValueError(f"{key}: bond_tips_share {tips} not in [0,1]")


_validate()
