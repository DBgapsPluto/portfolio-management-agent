import tradingagents.monitor.notify as nt


def test_no_webhook_env_returns_false(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert nt.send_rebalance_alert("daily", "drift:rebalance", "turnover 12%",
                                   ["A069500 SELL 20"]) is False


def test_webhook_posts_payload(monkeypatch):
    calls = {}
    def fake_urlopen(req, timeout=None):
        calls["url"] = req.full_url; calls["data"] = req.data
        class R:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/xxx")
    monkeypatch.setattr(nt.urllib.request, "urlopen", fake_urlopen)
    assert nt.send_rebalance_alert("monthly", "monthly", "turnover 15%",
                                   ["A069500 SELL 85"]) is True
    assert calls["url"] == "https://hooks.slack.test/xxx"
    assert b"monthly" in calls["data"]


def test_urlopen_failure_is_graceful(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/xxx")
    monkeypatch.setattr(nt.urllib.request, "urlopen",
                        lambda req, timeout=None: (_ for _ in ()).throw(OSError("down")))
    assert nt.send_rebalance_alert("daily", "alert", "n/a", []) is False
