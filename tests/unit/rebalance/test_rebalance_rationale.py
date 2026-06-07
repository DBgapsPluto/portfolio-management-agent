from tradingagents.rebalance.types import TradeLine, RebalanceResult
from tradingagents.reports.rebalance_rationale import write_rebalance_rationale


class _FakeLLM:
    def invoke(self, prompt):
        class R: content = "## 리밸런싱 사유\n충분히 긴 monthly 서술 " + "x" * 200
        return R()


def _res(tier):
    r = RebalanceResult(as_of="2026-06-07", tier=tier)
    r.plan = [TradeLine("A069500", "BUY", 0, 33, 33, 990000)]
    r.trigger = {"tier": tier, "fired": ["monthly"]}
    return r


def test_monthly_uses_llm(tmp_path):
    out = tmp_path / "r.md"
    write_rebalance_rationale(_res("monthly"), out, deep_llm=_FakeLLM())
    text = out.read_text(encoding="utf-8")
    assert "리밸런싱 사유" in text
    assert len(text) > 100


def test_no_llm_falls_back_to_template(tmp_path):
    out = tmp_path / "r.md"
    write_rebalance_rationale(_res("monthly"), out, deep_llm=None)
    text = out.read_text(encoding="utf-8")
    assert "A069500" in text          # 결정론 템플릿에 매매 포함
    assert "BUY" in text
