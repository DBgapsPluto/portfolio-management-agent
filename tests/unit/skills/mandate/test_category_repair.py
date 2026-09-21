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


def test_recipient_ok_restricts_water_fill():
    # F1 (통합 레벨, MF-8): recipient_ok 지정 시 헤드룸이 있어도 predicate 를 만족하지 않는
    # 종목은 물채움을 받지 않고 원 비중을 유지한다(risk-blind 물채움 방지).
    w = {"F1": 0.14, "F2": 0.13, "B1": 0.18, "B2": 0.18, "B3": 0.17, "S1": 0.15, "CASH": 0.05}
    out = repair_category_caps(w, CATMAP, CAPS, recipient_ok=lambda t: t == "CASH")
    assert out["B1"] == pytest.approx(0.18, abs=1e-9)    # 비허용 목적지 — 원 비중 유지
    assert out["B2"] == pytest.approx(0.18, abs=1e-9)
    assert out["B3"] == pytest.approx(0.17, abs=1e-9)
    assert out["CASH"] > 0.05 + 1e-9                      # 허용 목적지만 물채움 수혜
    cs = _cat_sums(out, CATMAP)
    assert cs["fx"] == pytest.approx(0.20, abs=1e-6)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)


def test_recipient_ok_default_none_is_unrestricted():
    # recipient_ok 미지정(기본 None) → 기존 동작과 동치(하위 호환).
    w = {"F1": 0.14, "F2": 0.13, "B1": 0.18, "B2": 0.18, "B3": 0.17, "CASH": 0.20}
    assert repair_category_caps(w, CATMAP, CAPS) == repair_category_caps(
        w, CATMAP, CAPS, recipient_ok=None)


def test_recipient_ok_saturated_residual_lands_in_cash():
    # F1/B4 리뷰 회귀: recipient_ok 가 water-fill 루프는 막지만(허용 목적지 R1 만 물채움)
    # 헤드룸 0.15 로 freed 0.40 을 다 못 받으면, 예전 코드는 남은 0.25 를 터미널
    # renormalize(`s = sum(out.values()); {t: w/s}`) 에 맡겨 recipient_ok=False 인 X1
    # (정책 배제 목적지)에까지 비례로 되돌려줬다 — overlay._water_fill 이 이미 고친
    # (33ba11d) 오버플로 유실과 동형의 누수. 물채움 루프가 막은 대상은 renormalize 도
    # 건드리면 안 된다 — 잔여는 CASH 로.
    w = {"F1": 0.30, "F2": 0.30, "R1": 0.05, "X1": 0.35}
    out = repair_category_caps(w, CATMAP, CAPS, recipient_ok=lambda t: t == "R1")
    assert out["X1"] == pytest.approx(0.35, abs=1e-9)     # 비허용 목적지 — 누수로 인한 증가 없음
    assert out["R1"] <= 0.20 + 1e-9                        # single-cap 포화
    assert out.get("CASH", 0.0) > 1e-9                     # 미분배 잔여는 CASH 로
    cs = _cat_sums(out, CATMAP)
    assert cs["fx"] <= 0.20 + 1e-6
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)
