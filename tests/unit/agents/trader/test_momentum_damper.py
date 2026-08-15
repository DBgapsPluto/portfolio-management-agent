"""F6 모멘텀 패닉 감쇠 — quadrant 전환/패닉 시 이종 버킷 선정을 AUM top-K 로 후퇴.

Daniel-Moskowitz(2016)·Barroso-Santa-Clara(2015): 모멘텀 크래시는 레짐 전환·변동성
패닉 국면에서 집중된다. 선정 자체(모멘텀 랭킹)를 후퇴시켜 크래시 위험을 낮춘다.
"""
import json
import types
from types import SimpleNamespace

import pytest

from tradingagents.schemas.portfolio import BucketTilt
from tradingagents.schemas.research import ResearchThesis
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS


def test_panic_thresholds_match_trigger_yaml():
    # daily_triggers는 정규식 파서 — 상수는 YAML 문자열에만 존재(감사 MF-4).
    # 단일 소스 상수 + YAML 패리티 테스트로 드리프트 차단.
    import yaml
    from tradingagents.skills.portfolio.panic_thresholds import VIX_PANIC, VKOSPI_PANIC
    cfg = yaml.safe_load(open("presets/triggers_default.yaml", encoding="utf-8"))
    conds = " ".join(t["condition"] for t in cfg["triggers"])
    assert f"vix > {VIX_PANIC:g}" in conds and f"vkospi > {VKOSPI_PANIC:g}" in conds
