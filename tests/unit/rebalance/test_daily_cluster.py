import json

import tradingagents.rebalance.daily_full as df
from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.schemas.technical import Cluster


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="KODEX200", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A360750", name="TIGER미국S&P500", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="해외주식_지수"),
        ETFEntry(ticker="A357870", name="CD금리", aum_krw=1e11, underlying_index="x",
                 bucket="안전", category="금리연계형/초단기채권"),
    ])


def test_daily_passes_clusters_to_validation(tmp_path, monkeypatch):
    # 클러스터(A069500+A360750)가 25% 초과하도록 구성 → daily 가 검증해서 violation 을 잡아야
    monkeypatch.setattr(df, "fetch_current_prices",
                        lambda d: {"A069500": 10000.0, "A360750": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 15, "A360750": 15, "A357870": 70}, 0,
                                   {"A069500": 0.15, "A360750": 0.15, "A357870": 0.70}))
    # 클러스터 로더가 A069500+A360750 군집을 반환하도록 monkeypatch
    monkeypatch.setattr(df, "_load_clusters",
                        lambda *a, **k: [Cluster(cluster_id="c1", members=["A069500", "A360750"],
                                                 avg_internal_correlation=0.85, category_label="equity-beta")])
    # drift:rebalance 로 prev_target 복원 → realized 에 A069500+A360750≈0.30 > 0.25
    monkeypatch.setattr(df, "_eval_triggers",
                        lambda **k: ("drift:rebalance", {"fired": ["drift:rebalance"]}, False))
    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    # 클러스터 cap 위반이 validation 에 hard 로 잡혔는지 (검증이 실제로 수행됨)
    viols = (res.validation.violations if res.validation else [])
    assert any(v.rule == "correlation_concentration" for v in viols), \
        "daily 가 클러스터 cap 을 검증해야(공허 통과 아님)"


def _uni_repair():
    """Fixture for the D1-3 dial tests: cluster {A069500, A360750} plus three
    safe ETFs whose categories sit inside CATEGORY_CAPS so category/risk repair
    stay no-ops — only cluster repair (dial ON) changes the target. Prices are
    100 and weights multiples of 1e-4, so integer-qty rounding is exact."""
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="KODEX200", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A360750", name="TIGER미국S&P500", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="해외주식_지수"),
        ETFEntry(ticker="B1", name="국내회사채", aum_krw=1e11, underlying_index="x",
                 bucket="안전", category="국내채권_회사채"),
        ETFEntry(ticker="B2", name="해외회사채", aum_krw=1e11, underlying_index="x",
                 bucket="안전", category="해외채권_회사채"),
        ETFEntry(ticker="B3", name="CD금리", aum_krw=1e11, underlying_index="x",
                 bucket="안전", category="금리연계형\\초단기채권"),
    ])


def _patch_daily_repair_fixture(monkeypatch, spy=None):
    monkeypatch.setattr(df, "fetch_current_prices",
                        lambda d: {t: 100.0 for t in
                                   ("A069500", "A360750", "B1", "B2", "B3")})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni_repair())
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 2500, "A360750": 2500,
                                    "B1": 2000, "B2": 2000, "B3": 1000}, 0,
                                   {"A069500": 0.25, "A360750": 0.25,
                                    "B1": 0.20, "B2": 0.20, "B3": 0.10}))
    monkeypatch.setattr(df, "_load_clusters",
                        lambda *a, **k: [Cluster(cluster_id="c1",
                                                 members=["A069500", "A360750"],
                                                 avg_internal_correlation=0.85,
                                                 category_label="equity-beta")])
    monkeypatch.setattr(df, "_eval_triggers",
                        lambda **k: ("drift:rebalance", {"fired": ["drift:rebalance"]}, False))
    if spy is not None:
        monkeypatch.setattr(df, "repair_cluster_cap", spy)


def test_daily_dial_off_no_cluster_repair(tmp_path, monkeypatch):
    """D1-3 byte-identical guard: dial OFF (default) — the repair loop never
    calls repair_cluster_cap, so the over-cap cluster (0.50 > 0.35) reaches
    engine validation as a hard violation, exactly as today."""
    calls = []
    real = df.repair_cluster_cap

    def spy(weights, clusters, *a, **k):
        calls.append(1)
        return real(weights, clusters, *a, **k)

    _patch_daily_repair_fixture(monkeypatch, spy=spy)
    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert calls == []                                    # dial OFF -> never invoked
    viols = (res.validation.violations if res.validation else [])
    assert any(v.rule == "correlation_concentration" for v in viols)


def test_daily_dial_on_repairs_cluster_cap(tmp_path, monkeypatch):
    """D1-3 (MF-1 chain (4)): dial ON — the daily repair loop applies
    repair_cluster_cap with the loaded clusters, so realized weights respect
    the 0.35 cap and validation carries no correlation_concentration hard
    violation (previously the daily path had NO cluster repair at all)."""
    calls = []
    real = df.repair_cluster_cap

    def spy(weights, clusters, *a, **k):
        calls.append(1)
        return real(weights, clusters, *a, **k)

    _patch_daily_repair_fixture(monkeypatch, spy=spy)
    monkeypatch.setitem(df.DEFAULT_CONFIG["rebalance"], "cluster_full_universe", True)
    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert calls                                          # dial ON -> invoked in loop
    viols = (res.validation.violations if res.validation else [])
    assert not any(v.rule == "correlation_concentration" for v in viols)
    cluster_w = sum(res.realized_weights.get(t, 0.0) for t in ("A069500", "A360750"))
    assert cluster_w <= 0.35 + 1e-6
    # freed mass: B3 water-filled to SINGLE_CAP, saturated residual parked in CASH
    assert res.realized_weights.get("CASH", 0.0) > 0.0


def test_daily_empty_clusters_no_crash(tmp_path, monkeypatch):
    """클러스터 로더가 [] 를 반환해도 daily run 이 정상 종료해야."""
    monkeypatch.setattr(df, "fetch_current_prices",
                        lambda d: {"A069500": 10000.0, "A360750": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 15, "A360750": 15, "A357870": 70}, 0,
                                   {"A069500": 0.15, "A360750": 0.15, "A357870": 0.70}))
    monkeypatch.setattr(df, "_load_clusters", lambda *a, **k: [])
    monkeypatch.setattr(df, "_eval_triggers",
                        lambda **k: ("drift:rebalance", {"fired": ["drift:rebalance"]}, False))
    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    # no crash; correlation_concentration violation absent (no clusters to check)
    assert res.tier == "drift:rebalance"
    viols = (res.validation.violations if res.validation else [])
    assert not any(v.rule == "correlation_concentration" for v in viols)


def test_load_clusters_reads_persisted(tmp_path):
    """_load_clusters 가 artifacts 디렉토리의 portfolio.json 에서 clusters 를 로드해야."""
    artifact_dir = tmp_path / "2026-06-01"
    artifact_dir.mkdir()
    cluster_data = [
        {"cluster_id": "c1", "members": ["A069500", "A360750"],
         "avg_internal_correlation": 0.85, "category_label": "equity-beta"}
    ]
    (artifact_dir / "portfolio.json").write_text(
        json.dumps({"correlation_clusters": cluster_data}), encoding="utf-8"
    )
    clusters = df._load_clusters(previous_path=None, artifacts_dir=str(tmp_path))
    assert len(clusters) == 1
    assert clusters[0].cluster_id == "c1"
    assert clusters[0].members == ["A069500", "A360750"]


def test_load_clusters_returns_empty_when_none(tmp_path):
    """artifacts 에 clusters 가 없으면 [] 를 반환해야."""
    clusters = df._load_clusters(previous_path=None, artifacts_dir=str(tmp_path))
    assert clusters == []
