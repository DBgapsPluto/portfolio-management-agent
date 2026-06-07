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
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        logger.info("SLACK_WEBHOOK_URL 미설정 — 알림 생략 (tier=%s)", tier)
        return False
    text = (f"*리밸런싱 발화* tier=`{tier}` action=`{action}`\n{summary}\n"
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
