from tradingagents.skills.portfolio import gaps_buckets as gb


def test_14_keys_and_camps():
    assert len(gb.GAPS_BUCKET_KEYS) == 14
    assert len(gb.DEFENSIVE_KEYS) == 5
    assert len(gb.GROWTH_KEYS) == 9
    assert set(gb.DEFENSIVE_KEYS) | set(gb.GROWTH_KEYS) == set(gb.GAPS_BUCKET_KEYS)


def test_code_to_key_roundtrip():
    assert gb.CODE_TO_KEY["A1"] == "a1_cash"
    assert gb.CODE_TO_KEY["B9"] == "b9_risk_credit"
    assert len(gb.CODE_TO_KEY) == 14
    for key in gb.GAPS_BUCKET_KEYS:
        assert key in gb.BUCKET_KR_NAME
        assert gb.BUCKET_CAMP[key] in ("방어", "성장")


def test_growth_keys_are_b_series():
    assert all(gb.BUCKET_CODE[k].startswith("B") for k in gb.GROWTH_KEYS)
    assert all(gb.BUCKET_CODE[k].startswith("A") for k in gb.DEFENSIVE_KEYS)
