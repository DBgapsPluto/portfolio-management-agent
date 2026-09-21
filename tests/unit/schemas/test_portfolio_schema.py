from tradingagents.schemas.portfolio import BucketTilt


def test_bucket_tilt_default_sub_category_views_empty():
    bt = BucketTilt()
    assert bt.sub_category_views == {}          # backward-compat: default empty dict


def test_bucket_tilt_accepts_sub_category_views():
    bt = BucketTilt(tilts={"b3_global_tech": 0.0},
                    sub_category_views={"b3_global_tech": {"semiconductor": 0.8, "battery_ev": -0.4}})
    assert bt.sub_category_views["b3_global_tech"]["semiconductor"] == 0.8
