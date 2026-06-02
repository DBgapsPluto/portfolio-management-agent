# Stage 2/3 통합 — LLM 기반 Research Debate + Trader 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** factor model 기반 Stage 2(research_manager) + Stage 3(allocator)를 bull/bear/manager/trader LLM 클러스터로 교체하고, 14-bucket(xlsx) 배분 + per-ETF 위험/안전 검사를 분리한다.

**Architecture:** LangGraph 토폴로지는 그대로 유지한다. `research_debate` 노드 = bull→bear→manager(InvestmentThesis 종합), `allocator` 노드 = trader 2-step(14-bucket 비중 → 종목 선정) + 결정적 AUM 종목내 배분. D4 retry는 기존대로 `allocator`로 루프백하므로 trader만 재실행된다. `BucketTarget.weights`는 이미 임의 key + sum=1만 검증하므로 14-key를 스키마 변경 없이 담는다. 위험자산(≤70%)은 최종 weight_vector에 per-ETF 위험/안전(universe.json `bucket`)을 적용해 계산한다.

**Tech Stack:** Python 3.12, LangGraph, Pydantic v2, pytest, openpyxl, pandas. LLM은 `tradingagents.llm_clients.create_llm_client(provider, model).get_llm()`로 생성한 deep/quick 인스턴스. structured output은 `tradingagents/agents/utils/structured.py`.

**설계 문서:** `docs/superpowers/specs/2026-06-02-stage2-3-merge-llm-research-trader-design.md`

**구현 중 spec 대비 정제 사항(의도 동일):**
- spec의 "단일 `research_trade` 노드"는 **2-노드 유지**(research_debate=클러스터, allocator=trader)로 구현 → builder.py 무수정 + retry가 trader만 재실행. spec의 "retry → trader step A" 동작과 동일.
- `ResearchThesis`에서 `bucket_target` 필드 제거 → `bucket_target`은 별도 state 키(trader가 생성), 기존 AgentState 레이아웃과 일치. Stage 4 macro_conditional 호환 위해 `dominant_scenario` 필드명 사용.

---

## 파일 구조

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `tradingagents/skills/portfolio/gaps_buckets.py` | 14-bucket 상수·code↔key 매핑·진영 분류·universe→bucket_key 로더 | 신규 |
| `tradingagents/skills/portfolio/within_bucket.py` | AUM 가중 종목내 배분 + 단일 20% cap water-filling + 위험자산% 계산 | 신규 |
| `scripts/enrich_universe_gaps_bucket.py` | xlsx→universe.json `gaps_bucket` 1회 병합 | 신규 |
| `tradingagents/dataflows/universe.py` | `ETFEntry.gaps_bucket` optional 필드 추가 | 수정 |
| `tradingagents/schemas/research.py` | `InvestmentThesis`, `ResearchThesis` 추가 (`ResearchDecision`은 Phase 4까지 보존) | 수정 |
| `tradingagents/schemas/portfolio.py` | `OptimizationMethod.AUM_WEIGHTED` 추가 | 수정 |
| `tradingagents/agents/utils/structured.py` | `invoke_structured_obj` 헬퍼 추가 | 수정 |
| `tradingagents/agents/researchers/bull_researcher.py` | 강세 에이전트 | 신규 |
| `tradingagents/agents/researchers/bear_researcher.py` | 약세 에이전트 | 신규 |
| `tradingagents/agents/researchers/research_cluster.py` | bull→bear→manager 종합 노드 (`create_research_cluster`) | 신규 |
| `tradingagents/agents/trader/trader_allocator.py` | trader 2-step + AUM 배분 노드 (`create_trader_allocator`) | 신규 |
| `tradingagents/agents/allocator/overlay_apply.py` | Stage 4 재최적화 → 비중보존 shrink/clip 교체 | 수정 |
| `tradingagents/agents/managers/risk_judge.py` | risk_flags 구성 후 overlay에 전달 | 수정 |
| `tradingagents/agents/managers/portfolio_manager.py` 또는 `reports/philosophy.py` | 14-bucket 포맷터 | 수정 |
| `tradingagents/graph/trading_graph.py` | 새 노드 배선 | 수정 |
| (Phase 4) factor model / candidate_selector / optimizer 모듈 | 삭제 | 삭제 |

---

## Phase 0 — 데이터 & 스키마

### Task 0.1: 14-bucket 상수 모듈

**Files:**
- Create: `tradingagents/skills/portfolio/gaps_buckets.py`
- Test: `tests/unit/skills/portfolio/test_gaps_buckets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/skills/portfolio/test_gaps_buckets.py
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
    # every key has a korean name + camp
    for key in gb.GAPS_BUCKET_KEYS:
        assert key in gb.BUCKET_KR_NAME
        assert gb.BUCKET_CAMP[key] in ("방어", "성장")


def test_growth_keys_are_b_series():
    assert all(gb.BUCKET_CODE[k].startswith("B") for k in gb.GROWTH_KEYS)
    assert all(gb.BUCKET_CODE[k].startswith("A") for k in gb.DEFENSIVE_KEYS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_gaps_buckets.py -v`
Expected: FAIL — `ModuleNotFoundError: tradingagents.skills.portfolio.gaps_buckets`

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/skills/portfolio/gaps_buckets.py
"""14-bucket 분류 (docs/GAPS_ETF_버킷분류_14.xlsx 기준).

방어 5 (A1~A5) + 성장 9 (B1~B9). trader 배분 어휘.
위험/안전(mandate) 정의와는 별개 — 그건 universe.json `bucket` per-ETF.
"""
from __future__ import annotations
from typing import Final

# key → (code, 한글명, 진영)
_SPEC: Final[list[tuple[str, str, str, str]]] = [
    ("a1_cash",             "A1", "현금성",                "방어"),
    ("a2_kr_rates",         "A2", "국내 금리(국채·IG)",     "방어"),
    ("a3_us_rates",         "A3", "미국 금리(국채·IG)",     "방어"),
    ("a4_safe_fx",          "A4", "안전통화",              "방어"),
    ("a5_gold_infl",        "A5", "금·인플레헤지",          "방어"),
    ("b1_kr_equity",        "B1", "한국주식(브로드·시클리컬·테마)", "성장"),
    ("b2_dm_core",          "B2", "미국·선진 코어주식",      "성장"),
    ("b3_global_tech",      "B3", "글로벌 테크·반도체·성장테마", "성장"),
    ("b4_china",            "B4", "중국주식",              "성장"),
    ("b5_other_intl",       "B5", "기타 해외주식",          "성장"),
    ("b6_defensive_equity", "B6", "방어적 주식(배당·저변동)", "성장"),
    ("b7_reits",            "B7", "리츠(부동산)",          "성장"),
    ("b8_cyclical_commodity","B8", "경기민감 원자재·에너지",  "성장"),
    ("b9_risk_credit",      "B9", "위험 크레딧(하이일드)",   "성장"),
]

GAPS_BUCKET_KEYS: Final[tuple[str, ...]] = tuple(s[0] for s in _SPEC)
BUCKET_CODE: Final[dict[str, str]] = {s[0]: s[1] for s in _SPEC}
CODE_TO_KEY: Final[dict[str, str]] = {s[1]: s[0] for s in _SPEC}
BUCKET_KR_NAME: Final[dict[str, str]] = {s[0]: s[2] for s in _SPEC}
BUCKET_CAMP: Final[dict[str, str]] = {s[0]: s[3] for s in _SPEC}
DEFENSIVE_KEYS: Final[tuple[str, ...]] = tuple(s[0] for s in _SPEC if s[3] == "방어")
GROWTH_KEYS: Final[tuple[str, ...]] = tuple(s[0] for s in _SPEC if s[3] == "성장")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_gaps_buckets.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/gaps_buckets.py tests/unit/skills/portfolio/test_gaps_buckets.py
git commit -m "feat(buckets): 14-bucket 상수 모듈 (gaps_buckets)"
```

### Task 0.2: universe.json `gaps_bucket` 병합

**Files:**
- Modify: `tradingagents/dataflows/universe.py` (`ETFEntry` 클래스)
- Create: `scripts/enrich_universe_gaps_bucket.py`
- Modify: `data/universe.json` (스크립트 실행 산출)
- Test: `tests/unit/dataflows/test_gaps_bucket_enrichment.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/dataflows/test_gaps_bucket_enrichment.py
import json
from pathlib import Path
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS


def test_every_etf_has_valid_gaps_bucket():
    u = json.loads(Path("data/universe.json").read_text())
    etfs = u["etfs"]
    assert len(etfs) == 188
    for e in etfs:
        assert "gaps_bucket" in e, f"{e['ticker']} missing gaps_bucket"
        assert e["gaps_bucket"] in GAPS_BUCKET_KEYS, \
            f"{e['ticker']} bad gaps_bucket {e['gaps_bucket']}"


def test_etfentry_roundtrips_gaps_bucket():
    from tradingagents.dataflows.universe import ETFEntry
    e = ETFEntry(
        ticker="A459580", name="x", aum_krw=1.0, underlying_index="i",
        bucket="안전", category="c", gaps_bucket="a1_cash",
    )
    assert e.gaps_bucket == "a1_cash"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_gaps_bucket_enrichment.py -v`
Expected: FAIL — `gaps_bucket` 필드 없음 / universe.json에 키 없음.

- [ ] **Step 3a: Add `gaps_bucket` field to `ETFEntry`**

`tradingagents/dataflows/universe.py`의 `ETFEntry`에 `sub_category` 필드 바로 아래 추가:

```python
    gaps_bucket: Optional[str] = Field(
        default=None,
        description="14-bucket key (a1_cash..b9_risk_credit). "
                    "scripts/enrich_universe_gaps_bucket.py 가 xlsx에서 1회 병합.",
    )
```

- [ ] **Step 3b: Write the enrichment script**

```python
# scripts/enrich_universe_gaps_bucket.py
"""xlsx 14-bucket 분류를 data/universe.json 에 gaps_bucket 으로 병합 (1회).

Usage: .venv/bin/python scripts/enrich_universe_gaps_bucket.py
"""
import json
from pathlib import Path

import pandas as pd

from tradingagents.skills.portfolio.gaps_buckets import CODE_TO_KEY

XLSX = Path("docs/GAPS_ETF_버킷분류_14.xlsx")
UNIVERSE = Path("data/universe.json")


def main() -> None:
    df = pd.read_excel(XLSX, sheet_name="버킷분류")
    code_by_ticker = {
        str(t): str(b) for t, b in zip(df["티커"], df["버킷"])
    }
    u = json.loads(UNIVERSE.read_text())
    missing = []
    for e in u["etfs"]:
        code = code_by_ticker.get(e["ticker"])
        if code is None or code not in CODE_TO_KEY:
            missing.append(e["ticker"])
            continue
        e["gaps_bucket"] = CODE_TO_KEY[code]
    if missing:
        raise SystemExit(f"매핑 실패 {len(missing)}종목: {missing[:10]}")
    UNIVERSE.write_text(json.dumps(u, ensure_ascii=False, indent=2))
    print(f"OK — {len(u['etfs'])}종목 gaps_bucket 병합 완료")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3c: Run the script**

Run: `.venv/bin/python scripts/enrich_universe_gaps_bucket.py`
Expected: `OK — 188종목 gaps_bucket 병합 완료`

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_gaps_bucket_enrichment.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/universe.py scripts/enrich_universe_gaps_bucket.py data/universe.json tests/unit/dataflows/test_gaps_bucket_enrichment.py
git commit -m "feat(universe): gaps_bucket(14) 병합 + ETFEntry 필드"
```

### Task 0.3: 신규 스키마 (InvestmentThesis, ResearchThesis, BucketAllocation, StockSelection, enum)

**Files:**
- Modify: `tradingagents/schemas/research.py`
- Modify: `tradingagents/schemas/portfolio.py`
- Test: `tests/unit/schemas/test_research_trade_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/schemas/test_research_trade_schemas.py
import pytest
from tradingagents.schemas.research import InvestmentThesis, ResearchThesis
from tradingagents.schemas.portfolio import (
    OptimizationMethod, BucketAllocation, StockSelection,
)


def test_investment_thesis_defaults():
    t = InvestmentThesis(thesis_md="bull은 X, bear는 Y, 종합하면 Z")
    assert t.conviction == "medium"
    assert t.dominant_scenario == "neutral"
    assert t.key_risks == []


def test_research_thesis_compat_fields():
    t = ResearchThesis(conviction="high", dominant_scenario="goldilocks",
                       thesis_md="t", bull_view="b", bear_view="r")
    # Stage 4 macro_conditional 는 getattr(rd, "dominant_scenario") / "conviction"
    assert getattr(t, "dominant_scenario") == "goldilocks"
    assert getattr(t, "conviction") == "high"
    # factor_scores 부재 → graceful None
    assert getattr(t, "factor_scores", None) is None


def test_aum_weighted_enum():
    assert OptimizationMethod.AUM_WEIGHTED.value == "aum_weighted"


def test_bucket_allocation_and_stock_selection():
    ba = BucketAllocation(weights={"a1_cash": 0.3, "b1_kr_equity": 0.7})
    assert ba.weights["b1_kr_equity"] == 0.7
    ss = StockSelection(selections={"b1_kr_equity": ["A069500", "A102110"]})
    assert ss.selections["b1_kr_equity"] == ["A069500", "A102110"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/schemas/test_research_trade_schemas.py -v`
Expected: FAIL — ImportError (새 클래스/enum 없음).

- [ ] **Step 3a: Add enum value** — `tradingagents/schemas/portfolio.py` `OptimizationMethod`에 추가:

```python
    AUM_WEIGHTED = "aum_weighted"   # Stage 2/3 merge (2026-06-02): trader bucket + AUM within-bucket
```

- [ ] **Step 3b: Add trader schemas** — `tradingagents/schemas/portfolio.py` 끝에 추가:

```python
class BucketAllocation(BaseModel):
    """Trader step A 출력 — 14-bucket 비중 (정규화 전 raw 허용)."""
    weights: dict[str, float] = Field(description="14-bucket key → weight")
    rationale: str = Field(default="", max_length=500)


class StockSelection(BaseModel):
    """Trader step B 출력 — bucket key → 선정 ticker 리스트."""
    selections: dict[str, list[str]] = Field(description="bucket key → [ticker]")
    rationale: str = Field(default="", max_length=500)
```

- [ ] **Step 3c: Add research schemas** — `tradingagents/schemas/research.py` 끝에 추가 (`ResearchDecision`은 유지):

```python
class InvestmentThesis(BaseModel):
    """Research Manager(Stage 2) 출력 — bull/bear 종합. structured LLM 타깃."""
    thesis_md: str = Field(max_length=4000)
    conviction: ConvictionLevel = "medium"
    dominant_scenario: str = Field(default="neutral", max_length=40)
    key_risks: list[str] = Field(default_factory=list)


class ResearchThesis(BaseModel):
    """Stage 2 종합 state 객체 (state['research_decision']).

    factor model 제거 후 ResearchDecision 을 대체. Stage 4 macro_conditional 이
    getattr(rd, 'dominant_scenario'|'conviction') 로 읽으므로 동일 필드명 유지.
    factor_scores 는 없음 → macro_conditional 의 valuation trigger graceful 비활성.
    """
    conviction: ConvictionLevel = "medium"
    dominant_scenario: str = Field(default="neutral", max_length=40)
    thesis_md: str = Field(default="", max_length=4000)
    bull_view: str = Field(default="", max_length=4000)
    bear_view: str = Field(default="", max_length=4000)
    key_risks: list[str] = Field(default_factory=list)
    model_config = {"extra": "ignore"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/schemas/test_research_trade_schemas.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/research.py tradingagents/schemas/portfolio.py tests/unit/schemas/test_research_trade_schemas.py
git commit -m "feat(schemas): InvestmentThesis/ResearchThesis/BucketAllocation/StockSelection + AUM_WEIGHTED"
```

### Task 0.4: structured 헬퍼 `invoke_structured_obj`

**Files:**
- Modify: `tradingagents/agents/utils/structured.py`
- Test: `tests/unit/agents/utils/test_invoke_structured_obj.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/agents/utils/test_invoke_structured_obj.py
from pydantic import BaseModel
from tradingagents.agents.utils.structured import invoke_structured_obj


class _S(BaseModel):
    x: int


class _Good:
    def invoke(self, prompt):
        return _S(x=42)


class _Bad:
    def invoke(self, prompt):
        raise RuntimeError("boom")


def test_returns_object_on_success():
    out = invoke_structured_obj(_Good(), "p", _S(x=0), "T")
    assert out.x == 42


def test_returns_fallback_on_failure():
    out = invoke_structured_obj(_Bad(), "p", _S(x=7), "T")
    assert out.x == 7


def test_none_llm_returns_fallback():
    out = invoke_structured_obj(None, "p", _S(x=9), "T")
    assert out.x == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/agents/utils/test_invoke_structured_obj.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement** — `tradingagents/agents/utils/structured.py` 끝에 추가:

```python
def invoke_structured_obj(
    structured_llm: Optional[Any],
    prompt: Any,
    fallback: T,
    agent_name: str,
) -> T:
    """structured 호출로 typed 객체를 받되, 실패/미지원 시 fallback 반환.

    markdown 이 아니라 Pydantic 객체 자체가 필요한 에이전트(manager/trader)용.
    파이프라인이 절대 막히지 않도록 모든 예외를 삼키고 fallback 으로 진행.
    """
    if structured_llm is None:
        return fallback
    try:
        return structured_llm.invoke(prompt)
    except Exception as exc:
        logger.warning(
            "%s: structured-object invocation failed (%s); using fallback",
            agent_name, exc,
        )
        return fallback
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/agents/utils/test_invoke_structured_obj.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/utils/structured.py tests/unit/agents/utils/test_invoke_structured_obj.py
git commit -m "feat(utils): invoke_structured_obj 헬퍼 (typed 객체 + graceful fallback)"
```

---

## Phase 1 — Research 클러스터 (bull / bear / manager)

공통: 노드는 `state.get("macro_summary"|"risk_summary"|"technical_summary"|"news_summary")`(Stage 1 핸드오프 ≤2KB markdown)를 전부 받는다. 테스트는 가짜 LLM으로 경로/계약만 검증.

### Task 1.1: Bull researcher

**Files:**
- Create: `tradingagents/agents/researchers/bull_researcher.py`
- Test: `tests/unit/agents/researchers/test_bull_researcher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/agents/researchers/test_bull_researcher.py
from langchain_core.messages import AIMessage
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher


class _FakeLLM:
    def __init__(self, content):
        self._c = content
    def invoke(self, prompt):
        return AIMessage(content=self._c)


def _state():
    return {
        "macro_summary": "성장 둔화 신호 약함, 디스인플레 진행",
        "risk_summary": "systemic 3/10, risk-on",
        "technical_summary": "코스피 모멘텀 +",
        "news_summary": "반도체 업황 개선 뉴스",
    }


def test_bull_returns_markdown_view():
    node = create_bull_researcher(_FakeLLM("강세 논리: 위험자산 비중 확대"))
    out = node(_state())
    assert "bull_view" in out
    assert "강세" in out["bull_view"]


def test_bull_handles_missing_summaries():
    node = create_bull_researcher(_FakeLLM("ok"))
    out = node({})   # empty state — 빈 summary 로도 안 죽음
    assert isinstance(out["bull_view"], str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/agents/researchers/test_bull_researcher.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

```python
# tradingagents/agents/researchers/bull_researcher.py
"""Bull researcher (Stage 2) — Stage 1 분석을 강세 관점으로 해석."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "당신은 자산배분 팀의 강세(bull) 리서처다. 주어진 매크로/리스크/기술적/뉴스 "
    "분석을 '위험자산 비중을 늘려야 하는 근거' 관점에서 해석한다. 낙관론을 위한 "
    "낙관이 아니라, 데이터에서 상방 시나리오를 뒷받침하는 신호를 찾아 논리적으로 "
    "제시한다. 반대 진영을 반박하지 말고 너의 논거만 한국어 markdown 으로 써라."
)


def _build_prompt(state) -> list[dict]:
    g = state.get
    body = (
        f"## 매크로\n{g('macro_summary', '(없음)')}\n\n"
        f"## 리스크\n{g('risk_summary', '(없음)')}\n\n"
        f"## 기술적\n{g('technical_summary', '(없음)')}\n\n"
        f"## 뉴스\n{g('news_summary', '(없음)')}\n"
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": body},
    ]


def create_bull_researcher(llm):
    def node(state):
        try:
            resp = llm.invoke(_build_prompt(state))
            view = resp.content
        except Exception as exc:
            logger.warning("bull_researcher failed: %s", exc)
            view = "(bull view 생성 실패)"
        return {"bull_view": view}
    return node
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/agents/researchers/test_bull_researcher.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/researchers/bull_researcher.py tests/unit/agents/researchers/test_bull_researcher.py
git commit -m "feat(stage2): bull researcher"
```

### Task 1.2: Bear researcher

**Files:**
- Create: `tradingagents/agents/researchers/bear_researcher.py`
- Test: `tests/unit/agents/researchers/test_bear_researcher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/agents/researchers/test_bear_researcher.py
from langchain_core.messages import AIMessage
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher


class _FakeLLM:
    def __init__(self, content):
        self._c = content
    def invoke(self, prompt):
        return AIMessage(content=self._c)


def test_bear_returns_markdown_view():
    node = create_bear_researcher(_FakeLLM("약세 논리: 안전자산 비중 확대"))
    out = node({"macro_summary": "x", "risk_summary": "y",
                "technical_summary": "z", "news_summary": "w"})
    assert "bear_view" in out
    assert "약세" in out["bear_view"]


def test_bear_handles_missing_summaries():
    node = create_bear_researcher(_FakeLLM("ok"))
    out = node({})
    assert isinstance(out["bear_view"], str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/agents/researchers/test_bear_researcher.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement** (bull과 대칭, system 프롬프트만 약세)

```python
# tradingagents/agents/researchers/bear_researcher.py
"""Bear researcher (Stage 2) — Stage 1 분석을 약세 관점으로 해석."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "당신은 자산배분 팀의 약세(bear) 리서처다. 주어진 매크로/리스크/기술적/뉴스 "
    "분석을 '위험자산을 줄이고 방어자산을 늘려야 하는 근거' 관점에서 해석한다. "
    "비관을 위한 비관이 아니라, 데이터에서 하방·꼬리 위험 시나리오를 뒷받침하는 "
    "신호를 찾아 논리적으로 제시한다. 상대를 반박하지 말고 너의 논거만 한국어 "
    "markdown 으로 써라."
)


def _build_prompt(state) -> list[dict]:
    g = state.get
    body = (
        f"## 매크로\n{g('macro_summary', '(없음)')}\n\n"
        f"## 리스크\n{g('risk_summary', '(없음)')}\n\n"
        f"## 기술적\n{g('technical_summary', '(없음)')}\n\n"
        f"## 뉴스\n{g('news_summary', '(없음)')}\n"
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": body},
    ]


def create_bear_researcher(llm):
    def node(state):
        try:
            resp = llm.invoke(_build_prompt(state))
            view = resp.content
        except Exception as exc:
            logger.warning("bear_researcher failed: %s", exc)
            view = "(bear view 생성 실패)"
        return {"bear_view": view}
    return node
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/agents/researchers/test_bear_researcher.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/researchers/bear_researcher.py tests/unit/agents/researchers/test_bear_researcher.py
git commit -m "feat(stage2): bear researcher"
```

### Task 1.3: Research cluster 노드 (manager 종합)

**Files:**
- Create: `tradingagents/agents/researchers/research_cluster.py`
- Test: `tests/unit/agents/researchers/test_research_cluster.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/agents/researchers/test_research_cluster.py
from langchain_core.messages import AIMessage
from tradingagents.schemas.research import InvestmentThesis, ResearchThesis
from tradingagents.agents.researchers.research_cluster import create_research_cluster


class _FakeBullBear:
    def __init__(self, content):
        self._c = content
    def invoke(self, prompt):
        return AIMessage(content=self._c)


class _FakeManager:
    """with_structured_output(InvestmentThesis) → .invoke → InvestmentThesis."""
    def __init__(self, thesis):
        self._t = thesis
    def with_structured_output(self, schema):
        return self
    def invoke(self, prompt):
        return self._t


def _state():
    return {"macro_summary": "m", "risk_summary": "r",
            "technical_summary": "t", "news_summary": "n"}


def test_cluster_synthesizes_research_thesis():
    thesis = InvestmentThesis(thesis_md="종합", conviction="high",
                              dominant_scenario="goldilocks",
                              key_risks=["인플레 재점화"])
    node = create_research_cluster(
        bull_llm=_FakeBullBear("강세"),
        bear_llm=_FakeBullBear("약세"),
        manager_llm=_FakeManager(thesis),
    )
    out = node(_state())
    rd = out["research_decision"]
    assert isinstance(rd, ResearchThesis)
    assert rd.conviction == "high"
    assert rd.dominant_scenario == "goldilocks"
    assert rd.bull_view == "강세"
    assert rd.bear_view == "약세"
    assert "research_debate_summary" in out


def test_cluster_manager_failure_falls_back():
    class _BadManager:
        def with_structured_output(self, schema):
            return self
        def invoke(self, prompt):
            raise RuntimeError("boom")
    node = create_research_cluster(
        bull_llm=_FakeBullBear("강세"), bear_llm=_FakeBullBear("약세"),
        manager_llm=_BadManager(),
    )
    out = node(_state())
    rd = out["research_decision"]
    assert rd.conviction == "medium"   # fallback neutral
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/agents/researchers/test_research_cluster.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

```python
# tradingagents/agents/researchers/research_cluster.py
"""Stage 2 research 클러스터 — bull → bear → manager 종합 (단일 패스)."""
from __future__ import annotations
import logging

from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.utils.structured import bind_structured, invoke_structured_obj
from tradingagents.schemas.research import InvestmentThesis, ResearchThesis

logger = logging.getLogger(__name__)

_MANAGER_SYSTEM = (
    "당신은 자산배분 팀의 리서치 매니저다. 강세(bull) 리서처와 약세(bear) 리서처의 "
    "주장, 그리고 Stage 1 매크로/리스크/기술적/뉴스 분석을 모두 검토해 균형 잡힌 "
    "투자 판단을 종합한다. 한쪽으로 치우치지 말고 양측 논거의 강도를 평가해 결론을 "
    "내려라. 결과는 thesis_md(한국어 종합 판단), conviction(high/medium/low), "
    "dominant_scenario(예: goldilocks/stagflation/recession/neutral 등 정성 라벨 1개), "
    "key_risks(주요 리스크 리스트)로 구조화하라."
)


def _manager_prompt(state, bull_view: str, bear_view: str) -> list[dict]:
    g = state.get
    body = (
        f"## Stage 1 요약\n매크로: {g('macro_summary','(없음)')}\n"
        f"리스크: {g('risk_summary','(없음)')}\n"
        f"기술적: {g('technical_summary','(없음)')}\n"
        f"뉴스: {g('news_summary','(없음)')}\n\n"
        f"## 강세(bull) 주장\n{bull_view}\n\n"
        f"## 약세(bear) 주장\n{bear_view}\n"
    )
    return [
        {"role": "system", "content": _MANAGER_SYSTEM},
        {"role": "user", "content": body},
    ]


def create_research_cluster(bull_llm, bear_llm, manager_llm):
    bull_node = create_bull_researcher(bull_llm)
    bear_node = create_bear_researcher(bear_llm)
    structured_mgr = bind_structured(manager_llm, InvestmentThesis, "ResearchManager")

    def node(state):
        bull_view = bull_node(state)["bull_view"]
        bear_view = bear_node(state)["bear_view"]

        fallback = InvestmentThesis(
            thesis_md="(manager 종합 실패 — 중립 유지)", conviction="medium",
            dominant_scenario="neutral", key_risks=[],
        )
        thesis = invoke_structured_obj(
            structured_mgr, _manager_prompt(state, bull_view, bear_view),
            fallback, "ResearchManager",
        )

        decision = ResearchThesis(
            conviction=thesis.conviction,
            dominant_scenario=thesis.dominant_scenario,
            thesis_md=thesis.thesis_md,
            bull_view=bull_view,
            bear_view=bear_view,
            key_risks=thesis.key_risks,
        )
        summary = (
            f"## Research Thesis\n"
            f"scenario: {decision.dominant_scenario} ({decision.conviction})\n"
            f"{decision.thesis_md[:1200]}\n"
            f"key risks: {', '.join(decision.key_risks) or '(none)'}\n"
        )[:2000]
        return {
            "research_decision": decision,
            "research_debate_summary": summary,
        }

    return node
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/agents/researchers/test_research_cluster.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/researchers/research_cluster.py tests/unit/agents/researchers/test_research_cluster.py
git commit -m "feat(stage2): research cluster (bull→bear→manager 종합)"
```

---

## Phase 2 — Trader + 종목내 배분

### Task 2.1: AUM 가중 종목내 배분 + cap water-filling

**Files:**
- Create: `tradingagents/skills/portfolio/within_bucket.py`
- Test: `tests/unit/skills/portfolio/test_within_bucket.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/skills/portfolio/test_within_bucket.py
import pytest
from tradingagents.skills.portfolio.within_bucket import (
    aum_weighted_allocation, InfeasibleBucket, SINGLE_CAP,
)


def test_single_stock_takes_full_bucket_weight():
    out = aum_weighted_allocation(
        {"b1_kr_equity": 0.10}, {"b1_kr_equity": ["A1"]}, {"A1": 1000.0},
    )
    assert out["A1"] == pytest.approx(0.10)


def test_aum_proportional_split():
    out = aum_weighted_allocation(
        {"b1_kr_equity": 0.30},
        {"b1_kr_equity": ["A1", "A2"]},
        {"A1": 300.0, "A2": 100.0},
    )
    assert out["A1"] == pytest.approx(0.30 * 0.75)
    assert out["A2"] == pytest.approx(0.30 * 0.25)


def test_cap_water_filling_redistributes_excess():
    # bucket weight 0.30, 단일 cap 0.20. AUM이 한쪽에 쏠려도 0.20 초과 불가.
    out = aum_weighted_allocation(
        {"b1_kr_equity": 0.30},
        {"b1_kr_equity": ["A1", "A2"]},
        {"A1": 900.0, "A2": 100.0},
    )
    assert out["A1"] == pytest.approx(SINGLE_CAP)        # capped 0.20
    assert out["A2"] == pytest.approx(0.10)              # 나머지
    assert sum(out.values()) == pytest.approx(0.30)


def test_multi_bucket_sums_to_one():
    out = aum_weighted_allocation(
        {"a1_cash": 0.40, "b1_kr_equity": 0.60},
        {"a1_cash": ["C1", "C2"], "b1_kr_equity": ["E1", "E2", "E3"]},
        {"C1": 1.0, "C2": 1.0, "E1": 1.0, "E2": 1.0, "E3": 1.0},
    )
    assert sum(out.values()) == pytest.approx(1.0)


def test_zero_weight_bucket_skipped():
    out = aum_weighted_allocation(
        {"a1_cash": 0.0, "b1_kr_equity": 1.0},
        {"a1_cash": ["C1"], "b1_kr_equity": ["E1"]},
        {"C1": 1.0, "E1": 1.0},
    )
    assert "C1" not in out
    assert out["E1"] == pytest.approx(1.0)


def test_infeasible_when_too_few_stocks_for_weight():
    # 0.50 bucket weight, 단일 cap 0.20 → 최소 ceil(0.5/0.2)=3 종목 필요. 2개 → infeasible.
    with pytest.raises(InfeasibleBucket):
        aum_weighted_allocation(
            {"b1_kr_equity": 0.50},
            {"b1_kr_equity": ["A1", "A2"]},
            {"A1": 1.0, "A2": 1.0},
        )


def test_infeasible_when_bucket_has_no_stocks():
    with pytest.raises(InfeasibleBucket):
        aum_weighted_allocation(
            {"b1_kr_equity": 0.10}, {"b1_kr_equity": []}, {},
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_within_bucket.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

```python
# tradingagents/skills/portfolio/within_bucket.py
"""버킷 비중을 선정 종목에 AUM 가중 배분 + 단일 20% cap water-filling.

위험자산(≤70%) 검사는 여기서 하지 않는다 — realized_risk_weight() 별도 함수가
최종 weight + per-ETF 위험/안전 으로 계산. (Stage 5 가 하드 검증.)
"""
from __future__ import annotations

SINGLE_CAP: float = 0.20
_EPS: float = 1e-9


class InfeasibleBucket(Exception):
    """버킷 비중을 단일 20% cap 안에서 배분 불가 (종목 부족)."""


def _allocate_one_bucket(weight: float, tickers: list[str],
                         aum: dict[str, float]) -> dict[str, float]:
    if weight <= _EPS:
        return {}
    if not tickers:
        raise InfeasibleBucket(f"bucket weight {weight} 인데 종목 0개")
    # 최소 종목 수: ceil(weight / cap)
    import math
    need = math.ceil(weight / SINGLE_CAP - _EPS)
    if len(tickers) < need:
        raise InfeasibleBucket(
            f"weight {weight} 에 최소 {need}종목 필요, {len(tickers)}개뿐")

    remaining = set(tickers)
    out: dict[str, float] = {}
    budget = weight
    # iterative water-filling: capped 확정 → 남은 예산을 잔여 AUM 비례 재분배
    while remaining:
        total_aum = sum(max(aum.get(t, 0.0), 0.0) for t in remaining)
        if total_aum <= _EPS:
            # AUM 정보 없음 → 균등 분배
            share = budget / len(remaining)
            raw = {t: share for t in remaining}
        else:
            raw = {t: budget * max(aum.get(t, 0.0), 0.0) / total_aum
                   for t in remaining}
        newly_capped = {t for t, w in raw.items() if w > SINGLE_CAP + _EPS}
        if not newly_capped:
            out.update(raw)
            break
        for t in newly_capped:
            out[t] = SINGLE_CAP
            budget -= SINGLE_CAP
            remaining.discard(t)
        if not remaining and budget > _EPS:
            raise InfeasibleBucket(f"잔여 예산 {budget} 배분 불가 (전부 capped)")
    return out


def aum_weighted_allocation(
    bucket_weights: dict[str, float],
    selections: dict[str, list[str]],
    aum: dict[str, float],
) -> dict[str, float]:
    """14-bucket 비중 + 버킷별 선정 종목 + ticker→AUM → ticker→최종 weight."""
    final: dict[str, float] = {}
    for bkey, w in bucket_weights.items():
        part = _allocate_one_bucket(w, selections.get(bkey, []), aum)
        for t, wt in part.items():
            final[t] = final.get(t, 0.0) + wt
    return final
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_within_bucket.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/within_bucket.py tests/unit/skills/portfolio/test_within_bucket.py
git commit -m "feat(stage3): AUM 가중 종목내 배분 + cap water-filling"
```

### Task 2.2: 위험자산% 계산 헬퍼 (per-ETF)

**Files:**
- Modify: `tradingagents/skills/portfolio/within_bucket.py`
- Test: `tests/unit/skills/portfolio/test_realized_risk_weight.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/skills/portfolio/test_realized_risk_weight.py
import pytest
from tradingagents.skills.portfolio.within_bucket import realized_risk_weight


def test_sums_only_위험_flagged():
    weights = {"A1": 0.5, "A2": 0.3, "A3": 0.2}
    risk_flag = {"A1": "위험", "A2": "안전", "A3": "위험"}
    assert realized_risk_weight(weights, risk_flag) == pytest.approx(0.7)


def test_missing_flag_treated_as_안전():
    weights = {"A1": 0.6, "A2": 0.4}
    assert realized_risk_weight(weights, {"A1": "위험"}) == pytest.approx(0.6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_realized_risk_weight.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement** — `within_bucket.py` 끝에 추가:

```python
def realized_risk_weight(
    weights: dict[str, float],
    risk_flag: dict[str, str],
) -> float:
    """최종 weight 중 universe.json bucket=='위험' 인 종목 비중 합 (mandate ≤0.70)."""
    return sum(w for t, w in weights.items() if risk_flag.get(t) == "위험")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_realized_risk_weight.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/within_bucket.py tests/unit/skills/portfolio/test_realized_risk_weight.py
git commit -m "feat(stage3): realized_risk_weight (per-ETF 위험자산 합)"
```

### Task 2.3: Trader/Allocator 노드 — 2-step + AUM 배분

`research_decision`(ResearchThesis), Stage 1 reports, universe, `allocation_feedback`(retry)를 읽어 `bucket_target`(14) + `candidate_set` + `weight_vector`(AUM_WEIGHTED)를 산출한다. 두 LLM 콜(step A: BucketAllocation, step B: StockSelection). step B는 비중>0 버킷의 종목 풀만 제시.

**Files:**
- Create: `tradingagents/agents/trader/trader_allocator.py`
- Test: `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/agents/trader/test_trader_allocator.py
import pytest
from tradingagents.schemas.research import ResearchThesis
from tradingagents.schemas.portfolio import (
    BucketAllocation, StockSelection, BucketTarget, CandidateSet,
    WeightVector, OptimizationMethod,
)
from tradingagents.agents.trader.trader_allocator import create_trader_allocator


class _FakeStep:
    """with_structured_output(schema).invoke(prompt) → 미리 정한 객체."""
    def __init__(self, obj):
        self._o = obj
    def with_structured_output(self, schema):
        return self
    def invoke(self, prompt):
        return self._o


def _universe(tmp_path):
    import json
    etfs = [
        {"ticker": "C1", "name": "현금성1", "aum_krw": 100.0,
         "underlying_index": "i", "bucket": "안전", "category": "c",
         "gaps_bucket": "a1_cash"},
        {"ticker": "E1", "name": "코스피1", "aum_krw": 300.0,
         "underlying_index": "i", "bucket": "위험", "category": "c",
         "gaps_bucket": "b1_kr_equity"},
        {"ticker": "E2", "name": "코스피2", "aum_krw": 100.0,
         "underlying_index": "i", "bucket": "위험", "category": "c",
         "gaps_bucket": "b1_kr_equity"},
    ]
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    return str(p)


def _state(universe_path):
    return {
        "research_decision": ResearchThesis(conviction="medium",
                                            dominant_scenario="neutral",
                                            thesis_md="t"),
        "universe_path": universe_path,
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
    }


def test_trader_produces_weight_vector_and_bucket_target(tmp_path):
    up = _universe(tmp_path)
    step_a = _FakeStep(BucketAllocation(weights={"a1_cash": 0.4, "b1_kr_equity": 0.6}))
    step_b = _FakeStep(StockSelection(selections={
        "a1_cash": ["C1"], "b1_kr_equity": ["E1", "E2"]}))
    node = create_trader_allocator(step_a_llm=step_a, step_b_llm=step_b)
    out = node(_state(up))

    assert isinstance(out["bucket_target"], BucketTarget)
    assert out["bucket_target"].weights["b1_kr_equity"] == pytest.approx(0.6)
    assert isinstance(out["candidate_set"], CandidateSet)
    wv = out["weight_vector"]
    assert isinstance(wv, WeightVector)
    assert wv.method == OptimizationMethod.AUM_WEIGHTED
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    # C1 = 0.4 (단일 cash), E1/E2 = 0.6 AUM 비례 (0.45/0.15)
    assert wv.weights["C1"] == pytest.approx(0.4, abs=1e-3)
    assert wv.weights["E1"] == pytest.approx(0.45, abs=1e-3)


def test_trader_normalizes_offsum_bucket_weights(tmp_path):
    up = _universe(tmp_path)
    # 합이 1이 아닌 raw → 정규화돼야 함
    step_a = _FakeStep(BucketAllocation(weights={"a1_cash": 0.8, "b1_kr_equity": 1.2}))
    step_b = _FakeStep(StockSelection(selections={
        "a1_cash": ["C1"], "b1_kr_equity": ["E1", "E2"]}))
    node = create_trader_allocator(step_a_llm=step_a, step_b_llm=step_b)
    out = node(_state(up))
    assert sum(out["bucket_target"].weights.values()) == pytest.approx(1.0)


def test_trader_drops_unknown_bucket_keys(tmp_path):
    up = _universe(tmp_path)
    step_a = _FakeStep(BucketAllocation(weights={
        "a1_cash": 0.4, "b1_kr_equity": 0.6, "garbage_key": 0.5}))
    step_b = _FakeStep(StockSelection(selections={
        "a1_cash": ["C1"], "b1_kr_equity": ["E1", "E2"]}))
    node = create_trader_allocator(step_a_llm=step_a, step_b_llm=step_b)
    out = node(_state(up))
    assert "garbage_key" not in out["bucket_target"].weights
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/agents/trader/test_trader_allocator.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

```python
# tradingagents/agents/trader/trader_allocator.py
"""Stage 3 trader/allocator — LLM 2-step 배분 + 결정적 AUM 종목내 배분.

step A: 14-bucket 비중 결정 (BucketAllocation)
step B: 비중>0 버킷의 종목 선정 (StockSelection)
종목내 비중: AUM 가중 + 단일 20% cap (within_bucket.aum_weighted_allocation)

위험자산(≤70%)은 최종 weight 에 per-ETF 위험/안전 적용해 검사 — Stage 5 가 하드 검증.
trader 는 step A 프롬프트에서 위험자산 예산을 안내받지만 강제는 사후 단계가 한다.
"""
from __future__ import annotations
import logging

from tradingagents.dataflows.universe import Universe
from tradingagents.agents.utils.structured import bind_structured, invoke_structured_obj
from tradingagents.schemas.portfolio import (
    BucketAllocation, StockSelection, BucketTarget, CandidateSet,
    WeightVector, OptimizationMethod,
)
from tradingagents.skills.portfolio.gaps_buckets import (
    GAPS_BUCKET_KEYS, BUCKET_KR_NAME, BUCKET_CAMP, GROWTH_KEYS,
)
from tradingagents.skills.portfolio.within_bucket import (
    aum_weighted_allocation, realized_risk_weight, InfeasibleBucket, SINGLE_CAP,
)
import json
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_universe(path: str) -> Universe:
    return Universe(**json.loads(Path(path).read_text()))


def _pool_by_bucket(uni: Universe) -> dict[str, list]:
    pool: dict[str, list] = {k: [] for k in GAPS_BUCKET_KEYS}
    for e in uni.etfs:
        if e.gaps_bucket in pool:
            pool[e.gaps_bucket].append(e)
    return pool


_STEP_A_SYSTEM = (
    "당신은 자산배분 트레이더다. 리서치 매니저의 종합 판단을 받아 14개 버킷에 "
    "비중(합=1.0)을 배정한다. 위험자산(주식·원자재·금 등 성장+일부 방어)은 합쳐 "
    "70%를 넘기지 말 것(대회 룰). 방어 버킷(A1~A5)과 성장 버킷(B1~B9)의 균형을 "
    "매니저 conviction 에 맞춰라."
)
_STEP_B_SYSTEM = (
    "당신은 트레이더다. 정해진 버킷 비중에 맞춰, 각 버킷에서 실제 매수할 ETF를 "
    "고른다. AUM·유동성이 충분하고 버킷 성격에 맞는 대표 종목을 고르되, 한 버킷의 "
    "비중이 클수록 단일 종목 20% 상한 때문에 더 많은 종목이 필요하다(최소 "
    "ceil(버킷비중/0.20)개)."
)


def _bucket_menu() -> str:
    return "\n".join(
        f"  {k} ({BUCKET_KR_NAME[k]}, {BUCKET_CAMP[k]})" for k in GAPS_BUCKET_KEYS
    )


def _step_a_prompt(state) -> list[dict]:
    rd = state.get("research_decision")
    thesis = getattr(rd, "thesis_md", "") if rd else ""
    conviction = getattr(rd, "conviction", "medium") if rd else "medium"
    fb = state.get("allocation_feedback") or []
    fb_txt = "\n".join(f"  - {getattr(v, 'message', str(v))}" for v in fb)
    return [
        {"role": "system", "content": _STEP_A_SYSTEM},
        {"role": "user", "content": (
            f"## 리서치 종합 (conviction={conviction})\n{thesis}\n\n"
            f"## 14 버킷\n{_bucket_menu()}\n\n"
            + (f"## 직전 시도 위반 피드백 (반영 필수)\n{fb_txt}\n\n" if fb_txt else "")
            + "각 버킷 key 에 0~1 비중을 배정(합 1.0). 위험자산 ≤70% 준수."
        )},
    ]


def _step_b_prompt(state, bucket_weights, pool) -> list[dict]:
    lines = []
    for k, w in bucket_weights.items():
        if w <= 0:
            continue
        min_n = max(1, int(-(-w // SINGLE_CAP)))   # ceil(w/cap)
        cand = sorted(pool.get(k, []), key=lambda e: -e.aum_krw)
        listing = "\n".join(
            f"    {e.ticker} {e.name} (AUM {e.aum_krw:,.0f}, {e.bucket})"
            for e in cand
        )
        lines.append(
            f"### {k} ({BUCKET_KR_NAME[k]}) 비중 {w*100:.1f}% — 최소 {min_n}종목\n{listing}"
        )
    return [
        {"role": "system", "content": _STEP_B_SYSTEM},
        {"role": "user", "content": (
            "## 버킷별 종목 풀 (비중>0 버킷만)\n" + "\n\n".join(lines) +
            "\n\n각 버킷 key 에 선정 ticker 리스트를 배정하라."
        )},
    ]


def _normalize_bucket_weights(raw: dict[str, float]) -> dict[str, float]:
    clean = {k: max(0.0, float(v)) for k, v in raw.items()
             if k in GAPS_BUCKET_KEYS}
    total = sum(clean.values())
    if total <= 1e-9:
        # 빈 배분 → 전액 현금
        return {"a1_cash": 1.0}
    return {k: v / total for k, v in clean.items() if v > 0}


def create_trader_allocator(step_a_llm, step_b_llm):
    structured_a = bind_structured(step_a_llm, BucketAllocation, "TraderStepA")
    structured_b = bind_structured(step_b_llm, StockSelection, "TraderStepB")

    def node(state):
        uni = _load_universe(state["universe_path"])
        pool = _pool_by_bucket(uni)
        aum = {e.ticker: e.aum_krw for e in uni.etfs}
        risk_flag = {e.ticker: e.bucket for e in uni.etfs}
        valid_tickers = set(aum)

        # --- step A: bucket weights ---
        ba = invoke_structured_obj(
            structured_a, _step_a_prompt(state),
            BucketAllocation(weights={"a1_cash": 1.0}), "TraderStepA",
        )
        bucket_weights = _normalize_bucket_weights(ba.weights)

        # --- step B: stock selection (비중>0 버킷만) ---
        ss = invoke_structured_obj(
            structured_b, _step_b_prompt(state, bucket_weights, pool),
            StockSelection(selections={}), "TraderStepB",
        )
        # 선정 정제: valid ticker + 해당 버킷 소속만, 비중>0 버킷은 비었으면 AUM top 보충
        selections: dict[str, list[str]] = {}
        for bkey, w in bucket_weights.items():
            if w <= 0:
                continue
            picked = [t for t in ss.selections.get(bkey, [])
                      if t in valid_tickers and getattr(
                          next((e for e in pool[bkey] if e.ticker == t), None),
                          "gaps_bucket", None) == bkey]
            need = max(1, int(-(-w // SINGLE_CAP)))
            if len(picked) < need:
                # AUM 상위로 보충 (이미 고른 것 제외)
                extra = [e.ticker for e in sorted(pool[bkey], key=lambda e: -e.aum_krw)
                         if e.ticker not in picked]
                picked = (picked + extra)[:max(need, len(picked))]
            selections[bkey] = picked

        # --- 종목내 AUM 배분 (infeasible 시 균등 fallback 위해 한 번 더 보충 시도) ---
        try:
            weights = aum_weighted_allocation(bucket_weights, selections, aum)
        except InfeasibleBucket as exc:
            logger.warning("within-bucket infeasible (%s) — AUM top-N 으로 강제 보충", exc)
            for bkey, w in bucket_weights.items():
                if w <= 0:
                    continue
                need = max(1, int(-(-w // SINGLE_CAP)))
                selections[bkey] = [
                    e.ticker for e in sorted(pool[bkey], key=lambda e: -e.aum_krw)
                ][:max(need, len(selections.get(bkey, [])))]
            weights = aum_weighted_allocation(bucket_weights, selections, aum)

        # renormalize (부동소수 안전망)
        s = sum(weights.values())
        if s > 0:
            weights = {t: w / s for t, w in weights.items()}

        risk_pct = realized_risk_weight(weights, risk_flag)
        bucket_target = BucketTarget(
            weights=bucket_weights,
            rationale=(getattr(state.get("research_decision"), "dominant_scenario", "")
                       + f" / risk={risk_pct*100:.1f}%")[:500],
        )
        candidate_set = CandidateSet(
            bucket_to_tickers={k: v for k, v in selections.items() if v},
            selection_criteria="LLM trader step B + AUM top-N 보충",
            total_candidates=sum(len(v) for v in selections.values()) or 1,
        )
        weight_vector = WeightVector(
            method=OptimizationMethod.AUM_WEIGHTED,
            weights={t: round(w, 6) for t, w in weights.items() if w > 1e-6},
            rationale=f"14-bucket trader + AUM within-bucket. risk={risk_pct*100:.1f}%",
        )
        attribution = {
            "bucket_weights": bucket_weights,
            "realized_risk_pct": risk_pct,
            "n_holdings": len(weight_vector.weights),
        }
        return {
            "bucket_target": bucket_target,
            "candidate_set": candidate_set,
            "weight_vector": weight_vector,
            "method_choice": {"method": "aum_weighted"},
            "allocation_attribution": attribution,
        }

    return node
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/agents/trader/test_trader_allocator.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(stage3): trader/allocator 노드 (2-step LLM + AUM 배분)"
```

---

## Phase 3 — 통합 & 배선

### Task 3.1: trading_graph.py 새 노드 배선

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`
- Test: `tests/integration/test_research_trade_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_research_trade_wiring.py
"""새 노드가 trading_graph 에 배선되고, factory("research_debate"|"allocator")가
새 구현을 반환하는지 — LLM 호출 없이 nodes dict 만 검증."""
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_research_and_allocator_nodes_exist():
    g = TradingAgentsGraph(preset_name="db_gaps")
    assert "research_debate" in g.nodes
    assert "allocator" in g.nodes
    # 두 노드 모두 callable
    assert callable(g.nodes["research_debate"])
    assert callable(g.nodes["allocator"])
```

- [ ] **Step 2: Run test to verify it fails (or passes trivially) then update wiring**

Run: `.venv/bin/python -m pytest tests/integration/test_research_trade_wiring.py -v`
Expected: 현재는 old 노드로 PASS. 배선 변경 후에도 PASS 유지가 목표(회귀 가드).

- [ ] **Step 3: Update wiring** — `trading_graph.py`에서 import + 노드 생성 교체.

Import 블록에서 다음 두 줄 제거:
```python
from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator
from tradingagents.agents.managers.research_manager import create_research_manager
```
추가:
```python
from tradingagents.agents.researchers.research_cluster import create_research_cluster
from tradingagents.agents.trader.trader_allocator import create_trader_allocator
```

`research_estimator = create_research_manager(deep)` ~ `research_debate_node = research_estimator` 블록을 교체:
```python
        # Stage 2: bull/bear/manager 클러스터 (단일 패스).
        research_debate_node = create_research_cluster(
            bull_llm=deep, bear_llm=deep, manager_llm=deep,
        )
```

`allocator = archive_wrap_node(create_portfolio_allocator(...), [...])` 블록을 교체:
```python
        allocator = archive_wrap_node(
            create_trader_allocator(step_a_llm=deep, step_b_llm=deep),
            ["candidate_set", "weight_vector", "method_choice",
             "allocation_attribution", "bucket_target"],
        )
```

`research_debate_node = archive_wrap_node(research_debate_node, ["research_decision", "research_debate_summary", "bucket_target"])` 를 (bucket_target 제거):
```python
        research_debate_node = archive_wrap_node(
            research_debate_node,
            ["research_decision", "research_debate_summary"],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_research_trade_wiring.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/graph/trading_graph.py tests/integration/test_research_trade_wiring.py
git commit -m "feat(graph): research_cluster + trader_allocator 배선"
```

### Task 3.2: Stage 4 overlay_apply — 비중보존 shrink/clip 교체

기존 `apply_risk_overlay`(EfficientFrontier 2차 호출)를 weight_vector 직접 조작으로 교체한다. risk_asset_multiplier는 per-ETF 위험 종목을 비례 축소→안전에 재분배, weight_ceilings/cluster_caps는 clip+재정규화. risk_judge가 `risk_flags`를 만들어 전달한다.

**Files:**
- Modify: `tradingagents/agents/allocator/overlay_apply.py`
- Modify: `tradingagents/agents/managers/risk_judge.py`
- Test: `tests/unit/agents/allocator/test_overlay_apply_shrink.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/agents/allocator/test_overlay_apply_shrink.py
import pytest
from tradingagents.schemas.portfolio import WeightVector, OptimizationMethod
from tradingagents.schemas.risk_overlay import RiskOverlay
from tradingagents.agents.allocator.overlay_apply import apply_overlay_to_weights


def _wv():
    return WeightVector(
        method=OptimizationMethod.AUM_WEIGHTED,
        weights={"R1": 0.4, "R2": 0.3, "S1": 0.3},
        rationale="t",
    )


def test_empty_overlay_preserves_weights():
    wv = _wv()
    flags = {"R1": "위험", "R2": "위험", "S1": "안전"}
    out, changed = apply_overlay_to_weights(wv, RiskOverlay(), flags)
    assert not changed
    assert out.weights == wv.weights


def test_multiplier_shrinks_risk_redistributes_to_safe():
    wv = _wv()                       # 위험합 0.7
    flags = {"R1": "위험", "R2": "위험", "S1": "안전"}
    ov = RiskOverlay(risk_asset_multiplier=0.5)
    out, changed = apply_overlay_to_weights(wv, ov, flags)
    assert changed
    risk = out.weights["R1"] + out.weights["R2"]
    assert risk == pytest.approx(0.35, abs=1e-6)        # 0.7 * 0.5
    assert out.weights["S1"] == pytest.approx(0.65, abs=1e-6)
    assert sum(out.weights.values()) == pytest.approx(1.0)


def test_weight_ceiling_clips_and_renormalizes():
    wv = _wv()
    flags = {"R1": "위험", "R2": "위험", "S1": "안전"}
    ov = RiskOverlay(weight_ceilings={"R1": 0.2})
    out, changed = apply_overlay_to_weights(wv, ov, flags)
    assert out.weights["R1"] <= 0.2 + 1e-6
    assert sum(out.weights.values()) == pytest.approx(1.0)
```

확인: `RiskOverlay`의 필드명(`risk_asset_multiplier`, `weight_ceilings`, `cluster_caps`)은 `tradingagents/schemas/risk_overlay.py`에 정의됨(기존 lens가 사용). 빈 생성자 허용 여부는 Step 2에서 확인.

- [ ] **Step 2: Run test to verify it fails + RiskOverlay 필드 확인**

Run: `.venv/bin/python -m pytest tests/unit/agents/allocator/test_overlay_apply_shrink.py -v`
Expected: FAIL — `apply_overlay_to_weights` 없음. 동시에 `RiskOverlay()` 빈 생성이 되는지, 필드 default를 확인(필요 시 테스트의 RiskOverlay 생성 인자 조정).

확인 명령:
```bash
.venv/bin/python -c "from tradingagents.schemas.risk_overlay import RiskOverlay; print(RiskOverlay().model_dump())"
```

- [ ] **Step 3: Implement `apply_overlay_to_weights`** — `overlay_apply.py`에 추가(기존 `apply_risk_overlay`는 Step 4에서 교체):

```python
def apply_overlay_to_weights(
    weight_vector: "WeightVector",
    overlay: "RiskOverlay",
    risk_flags: dict[str, str],
) -> tuple["WeightVector", bool]:
    """RiskOverlay 를 weight_vector 에 직접 적용(재최적화 없음, 비중 구조 보존).

    1) risk_asset_multiplier < 1 → 위험 종목 비례 축소, 축소분을 안전 종목에 비례 재분배.
    2) weight_ceilings → 해당 종목 clip, 초과분 나머지에 비례 재분배.
    3) cluster_caps → (clusters 인자 없으면 skip; risk_judge 가 ceilings 로 변환).
    전부 끝나면 sum=1 로 renormalize.
    """
    from tradingagents.schemas.portfolio import WeightVector

    w = dict(weight_vector.weights)
    changed = False
    m = getattr(overlay, "risk_asset_multiplier", 1.0) or 1.0

    if m < 1.0 - 1e-9:
        risk_t = [t for t in w if risk_flags.get(t) == "위험"]
        safe_t = [t for t in w if risk_flags.get(t) != "위험"]
        freed = 0.0
        for t in risk_t:
            new = w[t] * m
            freed += w[t] - new
            w[t] = new
        safe_sum = sum(w[t] for t in safe_t)
        if safe_sum > 1e-9 and freed > 0:
            for t in safe_t:
                w[t] += freed * w[t] / safe_sum
        changed = True

    ceilings = getattr(overlay, "weight_ceilings", {}) or {}
    for t, cap in ceilings.items():
        if t in w and w[t] > cap + 1e-9:
            excess = w[t] - cap
            w[t] = cap
            others = [o for o in w if o != t]
            osum = sum(w[o] for o in others)
            if osum > 1e-9:
                for o in others:
                    w[o] += excess * w[o] / osum
            changed = True

    s = sum(w.values())
    if s > 1e-9:
        w = {t: v / s for t, v in w.items()}

    if not changed:
        return weight_vector, False
    return weight_vector.model_copy(update={"weights": w}), True
```

- [ ] **Step 4: Repoint `risk_judge` to the new applier**

`risk_judge.py`에서 `apply_risk_overlay(...)` 호출부(앞서 본 240-300 구간)를 교체. universe로 risk_flags를 만들고 새 함수 호출:

```python
        # risk_flags: per-ETF 위험/안전 (universe.json bucket) — mandate 정의 그대로.
        from tradingagents.dataflows.universe import Universe
        import json as _json
        from pathlib import Path as _Path
        try:
            _uni = Universe(**_json.loads(_Path(state["universe_path"]).read_text()))
            risk_flags = {e.ticker: e.bucket for e in _uni.etfs}
        except Exception:
            risk_flags = {}

        from tradingagents.agents.allocator.overlay_apply import apply_overlay_to_weights
        weight_vector_2, weight_changed = apply_overlay_to_weights(
            weight_vector_1, overlay, risk_flags,
        )
        outcome = "weights_shrunk" if weight_changed else "primary_success"
```

이 블록 아래의 기존 `outcome, weight_vector_2.weights != ...` 사용처를 `weight_changed`로 정리(요약 문자열의 `weight_changed` 변수는 그대로 사용 가능).

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/agents/allocator/test_overlay_apply_shrink.py tests/unit/agents/managers/ -v`
Expected: 신규 3 PASS. risk_judge 관련 기존 테스트 중 `apply_risk_overlay` 재최적화에 의존하던 것은 실패할 수 있음 → 해당 테스트를 새 계약(shrink/clip)으로 갱신하거나 Phase 4에서 정리. 실패 목록을 기록.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/allocator/overlay_apply.py tradingagents/agents/managers/risk_judge.py tests/unit/agents/allocator/test_overlay_apply_shrink.py
git commit -m "feat(stage4): overlay 재최적화 → 비중보존 shrink/clip (per-ETF 위험)"
```

### Task 3.3: Stage 6 philosophy 14-bucket 포맷터

기존 `philosophy.py`의 5/8-bucket 하드코딩 포맷터를 14-bucket(`gaps_buckets`)로 갱신.

**Files:**
- Modify: `tradingagents/reports/philosophy.py`
- Test: `tests/unit/reports/test_philosophy_bucket_format.py`

- [ ] **Step 1: 현재 포맷터 위치 확인**

Run: `grep -nE "_bucket_field|_format_bucket_target|fx_commodity|bond|kr_equity" tradingagents/reports/philosophy.py`
Expected: legacy 필드명을 쓰는 헬퍼 위치 식별.

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/reports/test_philosophy_bucket_format.py
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.reports.philosophy import format_bucket_target_14


def test_format_lists_nonzero_14_buckets_with_kr_names():
    bt = BucketTarget(weights={"a1_cash": 0.3, "b1_kr_equity": 0.5,
                               "b3_global_tech": 0.2}, rationale="t")
    out = format_bucket_target_14(bt)
    assert "현금성" in out
    assert "한국주식" in out
    assert "30.0%" in out or "30%" in out
    # 0 비중 버킷은 생략
    assert "중국주식" not in out
```

- [ ] **Step 3: Implement** — `philosophy.py`에 추가:

```python
def format_bucket_target_14(bucket_target) -> str:
    """14-bucket 비중을 한글명과 함께 markdown 으로 (0 비중 생략)."""
    from tradingagents.skills.portfolio.gaps_buckets import (
        GAPS_BUCKET_KEYS, BUCKET_KR_NAME,
    )
    weights = getattr(bucket_target, "weights", {}) or {}
    lines = []
    for k in GAPS_BUCKET_KEYS:
        w = weights.get(k, 0.0)
        if w > 1e-6:
            lines.append(f"- {BUCKET_KR_NAME[k]}: {w*100:.1f}%")
    return "\n".join(lines) or "(빈 배분)"
```

기존 `_build_state_summary` 등에서 옛 bucket 포맷터를 호출하던 자리를 `format_bucket_target_14(state.get("bucket_target"))`로 교체(Step 1에서 찾은 위치).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/reports/test_philosophy_bucket_format.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/reports/philosophy.py tests/unit/reports/test_philosophy_bucket_format.py
git commit -m "feat(stage6): philosophy 14-bucket 포맷터"
```

### Task 3.4: E2E mock 파이프라인 그린

**Files:**
- Test: 기존 E2E mock 테스트 활용/갱신 (예: `tests/integration/` 또는 `tests/e2e/`의 mock 파이프라인)

- [ ] **Step 1: 기존 E2E mock 테스트 식별**

Run: `grep -rilE "build_main_graph|node_factory|mock.*node|TradingAgentsGraph" tests/ | head`
Expected: mock 노드를 주입해 전체 파이프라인을 도는 테스트 파일 식별.

- [ ] **Step 2: 새 계약으로 mock 노드 갱신**

`research_debate` mock → `{"research_decision": ResearchThesis(...), "research_debate_summary": "..."}`,
`allocator` mock → `{"bucket_target": BucketTarget(14키), "candidate_set": CandidateSet(...), "weight_vector": WeightVector(...), "allocation_attribution": {}, "method_choice": {}}`로 수정(과거 8-bucket/factor 필드 제거).

- [ ] **Step 3: Run E2E**

Run: `.venv/bin/python -m pytest tests/ -k "e2e or integration or pipeline" -v`
Expected: 갱신한 mock 파이프라인 PASS. 실패는 old 계약 참조 → 수정.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test(e2e): mock 파이프라인을 14-bucket/ResearchThesis 계약으로 갱신"
```

---

## Phase 4 — 정리 (factor model 일체 삭제)

### Task 4.1: factor model + optimizer 모듈 삭제

**Files (삭제):**
- `tradingagents/skills/research/factor_to_bucket.py`, `factor_estimators.py`, `factor_calibration.py`, `factor_calibration_hierarchical.py`, `factor_baselines.py`, `factor_reliability_audit.py`
- `tradingagents/agents/managers/research_manager.py`
- `tradingagents/agents/allocator/portfolio_allocator.py`
- `tradingagents/skills/portfolio/candidate_selector*.py`, `method_picker*.py`, `cash_spillover.py`
- optimizer adapter / ENB(minimum_torsion) 모듈 (해당 파일 식별 후)

**보존:** `cov_estimator.py`, `returns_matrix.py` (Stage 5 fallback min-var), `sub_category.py`/`bucket_for_etf` (분류 참조).

- [ ] **Step 1: 잔존 import 그래프 확인 (삭제 안전성)**

Run:
```bash
grep -rnE "factor_to_bucket|factor_estimators|factor_calibration|candidate_selector|method_picker|cash_spillover|portfolio_allocator|research_manager|apply_risk_overlay|_solve_with_overlay" tradingagents/ --include="*.py" | grep -v "research_cluster\|trader_allocator"
```
Expected: 프로덕션 코드에서 참조가 남아있으면 먼저 제거. (observability/scripts 등 보조 도구는 함께 정리하거나 stub 처리.)

- [ ] **Step 2: 파일 삭제**

```bash
git rm tradingagents/skills/research/factor_to_bucket.py \
       tradingagents/skills/research/factor_estimators.py \
       tradingagents/skills/research/factor_calibration.py \
       tradingagents/skills/research/factor_calibration_hierarchical.py \
       tradingagents/skills/research/factor_baselines.py \
       tradingagents/skills/research/factor_reliability_audit.py \
       tradingagents/agents/managers/research_manager.py \
       tradingagents/agents/allocator/portfolio_allocator.py
# candidate_selector / method_picker / cash_spillover / optimizers(어댑터) / ENB:
git rm tradingagents/skills/portfolio/candidate_selector.py \
       tradingagents/skills/portfolio/method_picker.py \
       tradingagents/skills/portfolio/cash_spillover.py \
       tradingagents/skills/portfolio/optimizers.py
# ENB/minimum_torsion 모듈이 별도 파일이면 Step 1 grep 결과로 추가. cov_estimator/returns_matrix 는 보존.
```

- [ ] **Step 3: 죽은 `apply_risk_overlay` + 헬퍼 정리**

`overlay_apply.py`에서 더 이상 안 쓰는 `apply_risk_overlay`, `_solve_with_overlay`, `_shrink_bucket_by_multiplier`, EfficientFrontier import 제거(새 `apply_overlay_to_weights`만 남김).

- [ ] **Step 4: Run full suite, fix collection errors**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: import 에러 발생 지점이 삭제 모듈 참조 → 다음 Task에서 테스트 정리.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: factor model + candidate_selector/optimizer 모듈 삭제"
```

### Task 4.2: 죽은 테스트 정리

- [ ] **Step 1: 삭제 모듈을 import 하는 테스트 수집**

Run:
```bash
grep -rlE "factor_to_bucket|factor_estimators|factor_calibration|candidate_selector|method_picker|cash_spillover|portfolio_allocator|research_manager import|apply_risk_overlay|_solve_with_overlay|risk_asset_weight" tests/
```

- [ ] **Step 2: 해당 테스트 삭제 또는 새 계약으로 이관**

factor/optimizer 전용 테스트는 `git rm`. 통합 가치가 있는 것(예: mandate, fallback)은 새 계약으로 갱신. `test_research_manager_confidence.py`(8-bucket `_apply_confidence_to_bucket` 검증)는 해당 함수 삭제와 함께 제거.

```bash
git rm tests/unit/agents/test_research_manager_confidence.py
# (Step 1 결과의 나머지 factor/optimizer 전용 테스트 동일 처리)
```

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: collection 에러 0. PASS (사전 존재하던 알려진 fail 외 신규 fail 0).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: factor model/optimizer 의존 죽은 테스트 정리"
```

### Task 4.3: BucketTarget dead 필드 정리 (cosmetic)

`bond_tips_share`/`risk_asset_weight`가 더 이상 참조되지 않음을 확인 후 제거.

**Files:**
- Modify: `tradingagents/schemas/portfolio.py`
- Test: 기존 schema 테스트

- [ ] **Step 1: 참조 0 확인**

Run: `grep -rnE "bond_tips_share|risk_asset_weight" tradingagents/ tests/ --include="*.py"`
Expected: 참조 없음(있으면 먼저 정리). 없으면 진행.

- [ ] **Step 2: 제거** — `BucketTarget`에서 `bond_tips_share` 필드와 `risk_asset_weight` property 삭제. (docstring도 14-bucket으로 갱신.)

- [ ] **Step 3: Run schema + full tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (신규 fail 0).

- [ ] **Step 4: Commit**

```bash
git add tradingagents/schemas/portfolio.py
git commit -m "refactor(schemas): BucketTarget 의 dead bond_tips_share/risk_asset_weight 제거"
```

---

## Self-Review 결과 (작성자 체크)

- **Spec coverage**: §4 버킷/위험 분리→Task 0.1/0.2/2.2; §5 컴포넌트→Phase 1/2; §6 스키마→Task 0.3; §7 downstream(Stage4/5/6/그래프)→Task 3.1~3.3; §8 삭제→Phase 4; §9 phases→Phase 0~4 매핑. §5 within-bucket=AUM→Task 2.1(승인 반영). 모든 spec 요구에 대응 Task 존재.
- **Placeholder scan**: 코드/명령/기대출력 모두 구체화. "Step 1에서 찾은 위치" 류는 grep 명령으로 실제 탐색을 지시(placeholder 아님). Phase 4 삭제 파일명은 Step 1 grep으로 정확화하도록 가드.
- **Type consistency**: `create_research_cluster(bull_llm, bear_llm, manager_llm)`, `create_trader_allocator(step_a_llm, step_b_llm)`, `aum_weighted_allocation(bucket_weights, selections, aum)`, `realized_risk_weight(weights, risk_flag)`, `apply_overlay_to_weights(weight_vector, overlay, risk_flags)→(WeightVector,bool)`, `ResearchThesis`/`InvestmentThesis`/`BucketAllocation`/`StockSelection` 필드명 — 정의 Task와 사용 Task 간 일치 확인 완료.
- **알려진 리스크**: Phase 3.2(risk_judge 수정), 3.4(E2E), 4.1/4.2(삭제 후 collection)는 기존 테스트와 충돌 가능 → 각 Task에 "실패 목록 기록 후 갱신" 단계 포함. `RiskOverlay()` 빈 생성 가능 여부는 Task 3.2 Step 2에서 실측 확인하도록 명시.
