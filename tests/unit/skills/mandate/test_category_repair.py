import pytest

from tradingagents.skills.mandate.category_repair import repair_category_caps

# 테스트용 caps (실제 CATEGORY_CAPS 와 무관 — 함수가 caps 를 인자로 받음)
CAPS = {"fx": 0.20, "sector": 0.15, "bond": 0.60}
CATMAP = {"F1": "fx", "F2": "fx", "S1": "sector",
          "B1": "bond", "B2": "bond", "B3": "bond"}


def _cat_sums(w, catmap):
    out: dict[str, float] = {}
    for k, v in w.items():
        c = catmap.get(k)
        if c:
            out[c] = out.get(c, 0.0) + v
    return out


def test_no_change_when_under_cap():
    w = {"F1": 0.10, "F2": 0.08, "S1": 0.12, "B1": 0.20, "B2": 0.20, "CASH": 0.30}
    out = repair_category_caps(w, CATMAP, CAPS)
    assert out == pytest.approx(w)


def test_scales_category_to_cap_and_water_fills():
    # fx 0.27 > 0.20; freed 0.07 → bond 종목에 water-fill, 단일 ≤0.20 유지
    w = {"F1": 0.14, "F2": 0.13, "B1": 0.18, "B2": 0.18, "B3": 0.17, "CASH": 0.20}
    out = repair_category_caps(w, CATMAP, CAPS)
    cs = _cat_sums(out, CATMAP)
    assert cs["fx"] == pytest.approx(0.20, abs=1e-6)
    assert all(cs.get(c, 0.0) <= cap + 1e-6 for c, cap in CAPS.items())
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(v <= 0.20 + 1e-9 for k, v in out.items() if k != "CASH")
    # fx 비례 축소 (상대비 보존)
    assert out["F1"] / out["F2"] == pytest.approx(0.14 / 0.13, rel=1e-6)


def test_category_tighter_than_single():
    # sector cap 0.15 < single 0.20; S1 0.18 단독 → sector 0.18>0.15 축소
    w = {"S1": 0.18, "B1": 0.10, "B2": 0.10, "CASH": 0.62}
    out = repair_category_caps(w, CATMAP, CAPS)
    cs = _cat_sums(out, CATMAP)
    assert cs["sector"] <= 0.15 + 1e-6
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)


def test_infeasible_returns_best_effort():
    # 전 비중이 fx 한 category → freed 분배처 없음. raise 없이 dict 반환.
    w = {"F1": 0.60, "F2": 0.40}
    out = repair_category_caps(w, CATMAP, CAPS)
    assert isinstance(out, dict)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)


def test_empty_returns_empty():
    assert repair_category_caps({}, CATMAP, CAPS) == {}


def test_deterministic():
    w = {"F1": 0.14, "F2": 0.13, "B1": 0.18, "B2": 0.18, "B3": 0.17, "CASH": 0.20}
    assert repair_category_caps(w, CATMAP, CAPS) == repair_category_caps(w, CATMAP, CAPS)
