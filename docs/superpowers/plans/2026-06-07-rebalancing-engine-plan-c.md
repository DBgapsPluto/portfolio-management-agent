# 리밸런싱 엔진 Plan C — 운영 자동화 (GitHub Actions cron + 슬랙 알림)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** daily 감시를 매 영업일 GitHub Actions cron(KST 07:00, 미국장 마감 후)으로 자동 실행하고, 트리거 발화 시 슬랙 알림을 보내며, 직전 산출물을 repo commit으로 보존해 다음 실행이 읽게 한다. 실제 주문은 운영자 수동(자동 집행 없음).

**Architecture:** (1) `notify.py` — 발화 시 슬랙 webhook 알림(env `SLACK_WEBHOOK_URL`, 미설정 시 로그). LLM 0, 표준 urllib. (2) daily 오케스트레이션이 거래 발생 tier에서 notify 호출. (3) `.github/workflows/rebalance-daily.yml` — cron `0 22 * * 0-4`(=KST 07:00), checkout→`gaps rebalance daily`→artifacts commit&push. concurrency 직렬화.

**Tech Stack:** Python stdlib(urllib), GitHub Actions, 기존 rebalance 모듈.

**스펙:** [2026-06-07-rebalancing-engine-design.md](../specs/2026-06-07-rebalancing-engine-design.md) §13(운영 모델).

**범위:** 알림 + cron 워크플로 + daily 연결. 실제 주문 집행은 out of scope(스펙 §2).

---

## File Structure

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `tradingagents/monitor/notify.py` | 발화 알림 어댑터(슬랙 webhook; 미설정 시 로그) | 신규 |
| `tradingagents/rebalance/daily_full.py` | 거래 발생 tier에서 notify 호출 | 수정 |
| `.github/workflows/rebalance-daily.yml` | cron 자동 실행 + 상태 commit | 신규 |
| `tests/unit/rebalance/test_notify.py` | notify 단위 테스트 | 신규 |

---

## Task 1: 알림 어댑터 `notify.py`

**Files:** Create `tradingagents/monitor/notify.py`; Test `tests/unit/rebalance/test_notify.py`

- [ ] **Step 1: 테스트** (urllib.request.urlopen monkeypatch)

```python
# tests/unit/rebalance/test_notify.py
import tradingagents.monitor.notify as nt


def test_no_webhook_env_returns_false_logs(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    sent = nt.send_rebalance_alert("daily", "drift:rebalance", "turnover 12%", ["A069500 SELL 20"])
    assert sent is False        # 미설정 → 전송 안 함(graceful)


def test_webhook_posts_payload(monkeypatch):
    calls = {}
    def fake_urlopen(req, timeout=None):
        calls["url"] = req.full_url
        calls["data"] = req.data
        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            status = 200
        return R()
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/xxx")
    monkeypatch.setattr(nt.urllib.request, "urlopen", fake_urlopen)
    sent = nt.send_rebalance_alert("monthly", "monthly", "turnover 15%", ["A069500 SELL 85"])
    assert sent is True
    assert calls["url"] == "https://hooks.slack.test/xxx"
    assert b"monthly" in calls["data"]


def test_urlopen_failure_is_graceful(monkeypatch):
    def boom(req, timeout=None): raise OSError("network down")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/xxx")
    monkeypatch.setattr(nt.urllib.request, "urlopen", boom)
    assert nt.send_rebalance_alert("daily", "alert", "n/a", []) is False
```

- [ ] **Step 2:** `pytest tests/unit/rebalance/test_notify.py -v` → FAIL.

- [ ] **Step 3: 구현** — `tradingagents/monitor/notify.py`:

```python
"""리밸런싱 발화 알림 — 슬랙 webhook (스펙 §13.2). 표준 urllib, LLM 0.

env SLACK_WEBHOOK_URL 미설정 시 로그만(graceful). 알림 ≠ 주문 집행.
"""
import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)


def send_rebalance_alert(tier: str, action: str, summary: str,
                         top_trades: list[str]) -> bool:
    """발화 시 슬랙 알림. 전송 성공 True, 미설정/실패 False(graceful)."""
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        logger.info("SLACK_WEBHOOK_URL 미설정 — 알림 생략 (tier=%s)", tier)
        return False
    text = (f"*리밸런싱 발화* tier=`{tier}` action=`{action}`\n"
            f"{summary}\n"
            + ("\n".join(f"• {t}" for t in top_trades[:10]) if top_trades else "(거래 없음)")
            + "\n_주문은 운영자가 plan.csv 확인 후 MTS 수동 집행_")
    data = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
        logger.info("리밸런싱 알림 전송 (tier=%s, ok=%s)", tier, ok)
        return ok
    except Exception as e:
        logger.warning("리밸런싱 알림 전송 실패: %s", e)
        return False
```

- [ ] **Step 4:** PASS (3) + `pytest tests/unit/rebalance/ -q`.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/monitor/notify.py tests/unit/rebalance/test_notify.py
git commit -m "feat(rebalance): 슬랙 발화 알림 어댑터(notify)"
```

---

## Task 2: daily 거래 발생 시 notify 호출

**Files:** Modify `tradingagents/rebalance/daily_full.py`; Test `tests/unit/rebalance/test_daily_notify.py`

- [ ] **Step 1: 테스트** — daily_full.run이 거래 발생 tier에서 `send_rebalance_alert` 호출, none-tier에선 미호출.

```python
# tests/unit/rebalance/test_daily_notify.py
import tradingagents.rebalance.daily_full as df
from tradingagents.dataflows.universe import Universe, ETFEntry


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="x", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A357870", name="y", aum_krw=1e11, underlying_index="y",
                 bucket="안전", category="금리연계형/초단기채권")])


def _common(monkeypatch, calls):
    monkeypatch.setattr(df, "fetch_current_prices",
                        lambda d: {"A069500": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    monkeypatch.setattr(df, "send_rebalance_alert",
                        lambda *a, **k: calls.setdefault("n", 0) or calls.update(n=calls.get("n", 0) + 1) or True)


def test_alert_sent_on_trade(tmp_path, monkeypatch):
    calls = {}
    _common(monkeypatch, calls)
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 60, "A357870": 40}, 0,
                                   {"A069500": 0.5, "A357870": 0.5}))
    monkeypatch.setattr(df, "_eval_triggers",
                        lambda **k: ("drift:rebalance", {"fired": ["drift:rebalance"]}, False))
    df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert calls.get("n", 0) == 1     # 거래 발생 → 알림 1회


def test_no_alert_on_none_tier(tmp_path, monkeypatch):
    calls = {}
    _common(monkeypatch, calls)
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 50, "A357870": 50}, 0,
                                   {"A069500": 0.5, "A357870": 0.5}))
    monkeypatch.setattr(df, "_eval_triggers", lambda **k: ("none", {}, False))
    df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert calls.get("n", 0) == 0     # 거래 없음 → 알림 0
```

- [ ] **Step 2:** FAIL.

- [ ] **Step 3: 구현** — `daily_full.py`:
  - 상단 import: `from tradingagents.monitor.notify import send_rebalance_alert`.
  - `run()`에서 run_rebalance 결과 `res`가 거래 있음(`res.plan` 비어있지 않음)일 때:
    ```python
    if res.plan:
        top = [f"{tl.ticker} {tl.action} {tl.delta_qty}" for tl in res.plan if tl.action != "HOLD"][:10]
        send_rebalance_alert(tier=res.tier, action=res.tier,
                             summary=f"turnover {res.turnover:.2%}, passed={res.validation.passed if res.validation else 'n/a'}",
                             top_trades=top)
    ```
  - none/alert/target-None(모니터링 only) 경로에선 호출 안 함.

- [ ] **Step 4:** PASS (2) + suite.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/rebalance/daily_full.py tests/unit/rebalance/test_daily_notify.py
git commit -m "feat(rebalance): daily 거래 발생 시 슬랙 알림 호출"
```

---

## Task 3: GitHub Actions cron 워크플로

테스트 불가(GitHub 환경)라 yaml 작성 + lint 수준 검증. 상태 보존(commit&push) + secrets + concurrency.

**Files:** Create `.github/workflows/rebalance-daily.yml`

- [ ] **Step 1: 작성** — `.github/workflows/rebalance-daily.yml`:

```yaml
name: rebalance-daily
# 매 한국 영업일(월~금) 아침 07:00 KST = UTC 전날 22:00 — 미국장 마감 후, 한국장 개장 전 (스펙 §13.1)
on:
  schedule:
    - cron: "0 22 * * 0-4"   # UTC 일~목 22:00 = KST 월~금 07:00
  workflow_dispatch: {}       # 수동 트리거 허용

concurrency:
  group: rebalance-daily      # 운영자 수동 실행/커밋과 push 충돌 직렬화
  cancel-in-progress: false

permissions:
  contents: write             # artifacts commit & push

jobs:
  daily:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test]"
      - name: Run daily rebalance
        env:
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          ECOS_API_KEY: ${{ secrets.ECOS_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          KRX_API_KEY: ${{ secrets.KRX_API_KEY }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        run: |
          LATEST=$(ls -d artifacts/*/ 2>/dev/null | grep -E '[0-9]{4}-[0-9]{2}-[0-9]{2}' | sort | tail -1)
          gaps rebalance daily --from "${LATEST%/}" || gaps rebalance daily
      - name: Commit artifacts (상태 보존)
        run: |
          git config user.name "rebalance-bot"
          git config user.email "rebalance-bot@users.noreply.github.com"
          git add artifacts/
          git diff --cached --quiet || git commit -m "chore(rebalance): daily artifacts $(date -u +%F)"
          git push
```

> 주의: `${{ }}`/`$(...)` 혼용은 GitHub Actions에서 정상. `--from`은 직전 산출물 디렉토리(as_of 이전) — 같은 날 재실행 시 §10 auto-discovery가 당일 plan을 previous로 오선택하지 않도록 엔진 측 가드가 처리(Plan A §10). monthly는 이 워크플로에 포함하지 않음(운영자 수동 — philosophy 검토 필요).

- [ ] **Step 2: 검증** — yaml 문법 확인:

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/rebalance-daily.yml'))" && echo "yaml OK"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/rebalance-daily.yml
git commit -m "feat(rebalance): GitHub Actions cron 워크플로(KST 07:00 daily + 상태 commit)"
```

---

## 최종 검증
- [ ] `pytest tests/unit/rebalance/ tests/integration/ -q` → PASS
- [ ] `python -c "import yaml; yaml.safe_load(open('.github/workflows/rebalance-daily.yml'))"` → OK
- [ ] 회귀 `pytest tests/ -m 'not slow and not eval' -q`

## Plan C 자체 검토 노트
- **스펙 커버리지:** §13.1 cron(0 22 * * 0-4=KST07:00)·상태 commit·concurrency·secrets=T3 · §13.2 슬랙 알림=T1/T2 · §13.3 안전(주문 수동)=알림 문구 + monthly 제외.
- **한계:** ① 워크플로는 단위 테스트 불가(GitHub 환경) — yaml lint + 수동 첫 실행으로 검증. ② 알림은 슬랙만(이메일 SMTP는 후속). ③ `pip install -e ".[test]"`·`gaps` 엔트리포인트가 CI에서 동작하는지 첫 실행 확인 필요. ④ 상태 commit이 매일 artifacts를 repo에 쌓음 — 용량/노이즈는 .gitignore 정책으로 후속 관리 가능.
