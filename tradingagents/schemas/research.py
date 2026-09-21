"""Stage 2 (Research) 스키마.

C5 (2026-05-23) 에서 24-cell Cartesian product framework 완전 제거.
- Phase 3 (2026-06-09): InvestmentThesis·ResearchThesis 의 dominant_scenario·conviction 제거
  → risk_tilt(5단) 단일화. fx/credit 정량 신호는 Stage 1 macro_report(fx.regime/
  financial_conditions.regime)가 담당.
- W3 (2026-08): legacy ResearchDecision(factor model)·ConvictionLevel 삭제 —
  producer/consumer 전무 (live node 는 ResearchThesis 반환, replay 도
  ResearchThesis 로 deserialize).
"""
from typing import Literal

from pydantic import BaseModel, Field


class InvestmentThesis(BaseModel):
    """Research Manager(Stage 2) 출력 — bull/bear 종합. structured LLM 타깃."""
    thesis_md: str = Field(max_length=20000)
    risk_tilt: Literal["strong_offensive", "offensive", "neutral", "defensive", "strong_defensive"] = "neutral"
    key_risks: list[str] = Field(default_factory=list)


class ResearchThesis(BaseModel):
    """Stage 2 종합 state 객체 (state['research_decision']).

    factor model 제거 후 legacy ResearchDecision 을 대체(클래스 자체는 W3 에서
    삭제). Stage 3 trader 가 getattr(rd, 'risk_tilt')
    로 읽어 비중 modifier 에 반영한다(fx/credit 정량 신호는 Stage 1 macro_report 가 별도 제공).
    """
    risk_tilt: Literal["strong_offensive", "offensive", "neutral", "defensive", "strong_defensive"] = "neutral"
    thesis_md: str = Field(default="", max_length=20000)
    bull_view: str = Field(default="", max_length=20000)
    bear_view: str = Field(default="", max_length=20000)
    key_risks: list[str] = Field(default_factory=list)
    model_config = {"extra": "ignore"}
