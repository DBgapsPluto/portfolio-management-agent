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
