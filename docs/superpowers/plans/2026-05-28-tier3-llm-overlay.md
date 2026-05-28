# Tier 3 — LLM Bucket Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add additive LLM overlay on top of Stage 2 quant bucket target — K=5 multi-sample directional view (`LLMBucketView`) with `novelty × consensus × credibility` dynamic weighting, ±5pp BAND clipping, EWMA cred update (α=0.1, prior 0.3), salience history persistence, and feature-flagged research_manager integration with forward-tuning protocol.

**Architecture:** New module `tradingagents/skills/overlay/` (novelty, consensus, credibility, apply). LLM prompt assembled from AgentState's 4 analyst summaries + 12 factor z-scores + quant_target + Stage 2 safety_diag. K=5 samples via existing `llm_clients/`. Blended dict → `project_to_mandate_qp` directly (no normalize step). Salience and credibility persist as parquet/json. Default OFF (feature flag).

**Tech Stack:** Python 3.11+, pydantic v2 (LLMBucketView), existing `tradingagents/llm_clients/`, scipy (QP via factor_to_bucket), pytest.

**Spec:** [`docs/superpowers/specs/2026-05-28-tier3-llm-overlay-design.md`](../specs/2026-05-28-tier3-llm-overlay-design.md)

**Dependency:** Tier 0 (12 factors) + Tier 1 (8 buckets + project_to_mandate_qp).

---

## File Structure

**Created:**
- `tradingagents/schemas/llm_overlay.py` — LLMBucketView, CredibilityState, LLMOverlayJournal
- `tradingagents/agents/overlay/__init__.py`
- `tradingagents/agents/overlay/llm_bucket_overlay.py` — generate_llm_views (K-sample)
- `tradingagents/skills/overlay/__init__.py`
- `tradingagents/skills/overlay/novelty.py` — compute_novelty + salience persistence
- `tradingagents/skills/overlay/consensus.py`
- `tradingagents/skills/overlay/credibility.py` — EWMA + json persistence
- `tradingagents/skills/overlay/apply.py` — apply_llm_overlay
- `tradingagents/skills/overlay/forward_tuning.py` — auto_tune_band
- `data/llm_overlay/.gitkeep`
- `tests/unit/schemas/test_llm_overlay.py`
- `tests/unit/skills/overlay/test_novelty.py`
- `tests/unit/skills/overlay/test_consensus.py`
- `tests/unit/skills/overlay/test_credibility.py`
- `tests/unit/skills/overlay/test_apply.py`
- `tests/unit/agents/overlay/test_llm_bucket_overlay.py`
- `tests/integration/test_tier3_overlay_pipeline.py`

**Modified:**
- `tradingagents/agents/managers/research_manager.py` — Tier 3 hook (feature-flagged)
- `tradingagents/default_config.py` — tier3 flags

---

## Task 1: LLMBucketView + CredibilityState schemas

**Files:**
- Create: `tradingagents/schemas/llm_overlay.py`
- Create: `tests/unit/schemas/test_llm_overlay.py`

- [ ] **Step 1: Test**

```python
import pytest
from datetime import date, datetime
from tradingagents.schemas.llm_overlay import (
    LLMBucketView, CredibilityState,
)


def test_llm_bucket_view_8_buckets():
    v = LLMBucketView(
        kr_equity=0.5, global_equity=0.3, precious_metals=-0.2,
        cyclical_commodity_fx=0.0, kr_bond=-0.1, credit=-0.3,
        global_duration=0.2, cash_mmf=0.1,
        confidence=0.7,
        reasoning="growth strong",
        cited_events=["FOMC minutes hawkish"],
    )
    deltas = v.to_delta_dict()
    assert set(deltas.keys()) == {
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    }
    assert deltas["kr_equity"] == 0.5


def test_llm_bucket_view_delta_bounds():
    """Per-bucket delta ∈ [-1, +1]."""
    with pytest.raises(Exception):
        LLMBucketView(
            kr_equity=1.5,  # out of bound
            global_equity=0, precious_metals=0, cyclical_commodity_fx=0,
            kr_bond=0, credit=0, global_duration=0, cash_mmf=0,
            confidence=0.5, reasoning="", cited_events=[],
        )


def test_credibility_state_default_prior():
    cs = CredibilityState(bucket_cred={}, history_count=0,
                           last_updated=date(2026, 6, 1))
    assert cs.bucket_cred == {}
```

- [ ] **Step 2: Implement**

`tradingagents/schemas/llm_overlay.py`:
```python
"""Tier 3 LLM overlay schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


BucketDirection = Literal["increase", "neutral", "decrease"]


class LLMBucketView(BaseModel):
    """Single LLM forward output — directional bucket view.

    Per-bucket delta ∈ [-1, +1]:
      +1 = strongly increase from quant baseline
       0 = neutral
      -1 = strongly decrease
    """
    kr_equity:             float = Field(ge=-1.0, le=1.0)
    global_equity:         float = Field(ge=-1.0, le=1.0)
    precious_metals:       float = Field(ge=-1.0, le=1.0)
    cyclical_commodity_fx: float = Field(ge=-1.0, le=1.0)
    kr_bond:               float = Field(ge=-1.0, le=1.0)
    credit:                float = Field(ge=-1.0, le=1.0)
    global_duration:       float = Field(ge=-1.0, le=1.0)
    cash_mmf:              float = Field(ge=-1.0, le=1.0)

    confidence: float = Field(ge=0.0, le=1.0,
                               description="LLM self-rated confidence")
    reasoning: str = Field(max_length=500)
    cited_events: list[str] = Field(default_factory=list, max_length=5)

    def to_delta_dict(self) -> dict[str, float]:
        return {
            "kr_equity": self.kr_equity,
            "global_equity": self.global_equity,
            "precious_metals": self.precious_metals,
            "cyclical_commodity_fx": self.cyclical_commodity_fx,
            "kr_bond": self.kr_bond,
            "credit": self.credit,
            "global_duration": self.global_duration,
            "cash_mmf": self.cash_mmf,
        }


class CredibilityState(BaseModel):
    """Per-bucket LLM credibility (EWMA, persisted)."""
    bucket_cred: dict[str, float] = Field(default_factory=dict)
    history_count: int = 0
    last_updated: date


class LLMOverlayJournal(BaseModel):
    """Per-rebalance LLM overlay journal entry for forward-tuning."""
    timestamp: datetime
    quant_target: dict[str, float]
    llm_views: list[LLMBucketView]
    novelty: float
    consensus: dict[str, float]
    credibility_snapshot: dict[str, float]
    final_target: dict[str, float]
    audit: dict[str, dict[str, float]]
    realized_returns: dict[str, float] | None = None  # filled N-period later
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/schemas/test_llm_overlay.py -v
git add tradingagents/schemas/llm_overlay.py tests/unit/schemas/test_llm_overlay.py
git commit -m "feat(tier3): LLMBucketView, CredibilityState, LLMOverlayJournal schemas"
```

---

## Task 2: novelty + salience persistence

**Files:**
- Create: `tradingagents/skills/overlay/__init__.py` (empty)
- Create: `tradingagents/skills/overlay/novelty.py`
- Create: `tests/unit/skills/overlay/test_novelty.py`
- Create: `data/llm_overlay/.gitkeep`

- [ ] **Step 1: Test**

```python
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd
from tradingagents.skills.overlay.novelty import (
    compute_novelty, append_daily_salience, load_salience_history,
    SALIENCE_HISTORY_PATH,
)


def test_compute_novelty_returns_zero_when_no_history(tmp_path, monkeypatch):
    """Insufficient history (< 10 days) → novelty = 0."""
    monkeypatch.setattr("tradingagents.skills.overlay.novelty.SALIENCE_HISTORY_PATH",
                        tmp_path / "salience.parquet")
    nr = MagicMock()
    nr.release_surprise.high_importance_today = 0
    nr.news_sentiment.avg_sentiment.macro = 0.0
    assert compute_novelty(nr, date(2026, 6, 1)) == 0.0


def test_compute_novelty_extreme_z_capped(tmp_path, monkeypatch):
    """z > 3 → novelty clipped to 1.0."""
    salience_file = tmp_path / "salience.parquet"
    monkeypatch.setattr("tradingagents.skills.overlay.novelty.SALIENCE_HISTORY_PATH",
                        salience_file)
    # Seed history with 30 days of low salience (mean ~0.5, sd ~0.1)
    hist = pd.DataFrame({
        "date": pd.date_range("2026-05-01", periods=30, freq="D").date,
        "salience": [0.5 + 0.05 * (i % 5) for i in range(30)],
    })
    salience_file.parent.mkdir(parents=True, exist_ok=True)
    hist.to_parquet(salience_file, index=False)
    
    nr = MagicMock()
    nr.release_surprise.high_importance_today = 100  # extreme
    nr.news_sentiment.avg_sentiment.macro = 1.0
    n = compute_novelty(nr, date(2026, 6, 1))
    assert 0.0 <= n <= 1.0
    assert n > 0.5  # high salience → high novelty


def test_append_idempotent(tmp_path, monkeypatch):
    salience_file = tmp_path / "salience.parquet"
    monkeypatch.setattr("tradingagents.skills.overlay.novelty.SALIENCE_HISTORY_PATH",
                        salience_file)
    nr = MagicMock()
    nr.release_surprise.high_importance_today = 2
    nr.news_sentiment.avg_sentiment.macro = 0.3
    append_daily_salience(nr, date(2026, 6, 1))
    append_daily_salience(nr, date(2026, 6, 1))  # duplicate
    df = pd.read_parquet(salience_file)
    assert len(df) == 1
```

- [ ] **Step 2: Implement**

`tradingagents/skills/overlay/novelty.py`:
```python
"""Tier 3 novelty + salience persistence.

Novelty = clip(z(today_salience) / 3.0, 0, 1)
Salience = log(1 + high_impact_count) + |macro_sentiment|
History: data/llm_overlay/salience_history.parquet (daily append-only).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SALIENCE_HISTORY_PATH: Final[Path] = Path("data/llm_overlay/salience_history.parquet")


def _safe_get(obj, *path, default=None):
    cur = obj
    for k in path:
        if cur is None:
            return default
        try:
            cur = getattr(cur, k)
        except AttributeError:
            try:
                cur = cur[k]
            except Exception:
                return default
    return cur if cur is not None else default


def _compute_today_salience(news_report: Any) -> float:
    high_imp = float(_safe_get(news_report, "release_surprise", "high_importance_today", default=0) or 0)
    sent = _safe_get(news_report, "news_sentiment", "avg_sentiment", "macro", default=0.0)
    sent_mag = abs(float(sent or 0.0))
    return float(np.log1p(high_imp) + sent_mag)


def append_daily_salience(news_report: Any, run_date: date) -> None:
    """Idempotent daily append. Same date → no-op."""
    if news_report is None:
        return
    salience = _compute_today_salience(news_report)
    row = pd.DataFrame({"date": [run_date], "salience": [salience]})
    if SALIENCE_HISTORY_PATH.exists():
        existing = pd.read_parquet(SALIENCE_HISTORY_PATH)
        if run_date in existing["date"].values:
            return
        combined = pd.concat([existing, row], ignore_index=True).sort_values("date")
    else:
        SALIENCE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        combined = row
    combined.to_parquet(SALIENCE_HISTORY_PATH, index=False)


def load_salience_history(as_of: date, window_days: int = 60) -> pd.Series:
    if not SALIENCE_HISTORY_PATH.exists():
        return pd.Series(dtype=float)
    df = pd.read_parquet(SALIENCE_HISTORY_PATH)
    cutoff = as_of - timedelta(days=window_days)
    df = df[(df["date"] >= cutoff) & (df["date"] < as_of)]
    return df.set_index("date")["salience"]


def compute_novelty(news_report: Any, as_of: date, window_days: int = 60) -> float:
    """News salience anomaly score, ∈ [0, 1]."""
    if news_report is None:
        return 0.0
    today = _compute_today_salience(news_report)
    history = load_salience_history(as_of, window_days)
    if len(history) < 10:
        return 0.0
    mu = float(history.mean())
    sd = float(history.std(ddof=1)) or 1e-9
    z = (today - mu) / sd
    return float(np.clip(z / 3.0, 0.0, 1.0))


__all__ = [
    "compute_novelty", "append_daily_salience", "load_salience_history",
    "SALIENCE_HISTORY_PATH",
]
```

- [ ] **Step 3: Test + commit**

```bash
mkdir -p data/llm_overlay
touch data/llm_overlay/.gitkeep
pytest tests/unit/skills/overlay/test_novelty.py -v
git add tradingagents/skills/overlay/__init__.py tradingagents/skills/overlay/novelty.py data/llm_overlay/.gitkeep tests/unit/skills/overlay/test_novelty.py
git commit -m "feat(tier3): novelty score + salience parquet persistence"
```

---

## Task 3: consensus

**Files:**
- Create: `tradingagents/skills/overlay/consensus.py`
- Create: `tests/unit/skills/overlay/test_consensus.py`

- [ ] **Step 1: Test**

```python
import pytest
from tradingagents.schemas.llm_overlay import LLMBucketView
from tradingagents.skills.overlay.consensus import compute_consensus


def _make_view(**deltas):
    """Build LLMBucketView with default values, overriding given."""
    defaults = {b: 0.0 for b in [
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    ]}
    defaults.update(deltas)
    return LLMBucketView(**defaults, confidence=0.5, reasoning="", cited_events=[])


def test_unanimous_consensus_is_1():
    views = [_make_view(kr_equity=0.5) for _ in range(5)]
    c = compute_consensus(views)
    assert c["kr_equity"] == 1.0


def test_split_consensus():
    # 3 positive, 2 negative
    views = [_make_view(kr_equity=0.5)] * 3 + [_make_view(kr_equity=-0.5)] * 2
    c = compute_consensus(views)
    # |3 - 2| / 5 = 0.2
    assert abs(c["kr_equity"] - 0.2) < 1e-9


def test_all_neutral():
    views = [_make_view(kr_equity=0.0)] * 5
    c = compute_consensus(views)
    assert c["kr_equity"] == 0.0
```

- [ ] **Step 2: Implement**

`tradingagents/skills/overlay/consensus.py`:
```python
"""Tier 3 consensus = |Σ sign(delta)| / K per bucket."""
from __future__ import annotations
from typing import Final

import numpy as np

from tradingagents.schemas.llm_overlay import LLMBucketView
from tradingagents.skills.research.factor_to_bucket import BUCKETS

NEUTRAL_THRESHOLD: Final[float] = 0.1


def compute_consensus(views: list[LLMBucketView]) -> dict[str, float]:
    """Per-bucket consensus ∈ [0, 1]. K=5 sample agreement."""
    result: dict[str, float] = {}
    if not views:
        return {b: 0.0 for b in BUCKETS}
    for bucket in BUCKETS:
        signs = []
        for v in views:
            delta = getattr(v, bucket)
            s = np.sign(delta) if abs(delta) >= NEUTRAL_THRESHOLD else 0
            signs.append(s)
        if all(s == 0 for s in signs):
            result[bucket] = 0.0
        else:
            result[bucket] = abs(sum(signs)) / len(signs)
    return result
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/overlay/test_consensus.py -v
git add tradingagents/skills/overlay/consensus.py tests/unit/skills/overlay/test_consensus.py
git commit -m "feat(tier3): compute_consensus (per-bucket sign agreement)"
```

---

## Task 4: credibility (EWMA + json persistence)

**Files:**
- Create: `tradingagents/skills/overlay/credibility.py`
- Create: `tests/unit/skills/overlay/test_credibility.py`

- [ ] **Step 1: Test**

```python
import pytest
from datetime import date
from pathlib import Path
from tradingagents.schemas.llm_overlay import CredibilityState
from tradingagents.skills.overlay.credibility import (
    update_credibility, get_credibility, load_credibility, save_credibility,
    COLD_START_PRIOR, EWMA_ALPHA,
)


def test_cold_start_prior_0_3():
    cs = CredibilityState(bucket_cred={}, history_count=0, last_updated=date(2026, 6, 1))
    assert get_credibility(cs, "kr_equity") == COLD_START_PRIOR == 0.3


def test_update_hit_increases_cred(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.skills.overlay.credibility.CRED_PATH",
                        tmp_path / "cred.json")
    cs = CredibilityState(bucket_cred={"kr_equity": 0.3}, history_count=0,
                           last_updated=date(2026, 6, 1))
    # predicted_delta + realized_return same sign → hit
    update_credibility(cs, "kr_equity", predicted_delta=0.02, realized_return=0.05)
    # cred_new = 0.9 × 0.3 + 0.1 × 1.0 = 0.37
    assert abs(cs.bucket_cred["kr_equity"] - 0.37) < 1e-9


def test_update_miss_decreases_cred(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.skills.overlay.credibility.CRED_PATH",
                        tmp_path / "cred.json")
    cs = CredibilityState(bucket_cred={"kr_equity": 0.5}, history_count=0,
                           last_updated=date(2026, 6, 1))
    update_credibility(cs, "kr_equity", predicted_delta=0.03, realized_return=-0.05)
    # miss: 0.9 × 0.5 + 0.1 × 0.0 = 0.45
    assert abs(cs.bucket_cred["kr_equity"] - 0.45) < 1e-9


def test_persistence_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.skills.overlay.credibility.CRED_PATH",
                        tmp_path / "cred.json")
    cs = CredibilityState(bucket_cred={"kr_equity": 0.4}, history_count=5,
                           last_updated=date(2026, 6, 15))
    save_credibility(cs)
    loaded = load_credibility()
    assert loaded.bucket_cred["kr_equity"] == 0.4
    assert loaded.history_count == 5
```

- [ ] **Step 2: Implement**

`tradingagents/skills/overlay/credibility.py`:
```python
"""Tier 3 credibility EWMA + JSON persistence.

Cold start: cred=0.3 (conservative).
EWMA update: cred_new = (1-α) × cred_old + α × hit, α=0.1.
Hit: sign(predicted_delta) × sign(realized_return) > 0.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Final

import numpy as np

from tradingagents.schemas.llm_overlay import CredibilityState

logger = logging.getLogger(__name__)

CRED_PATH: Final[Path] = Path("data/llm_overlay/credibility.json")
COLD_START_PRIOR: Final[float] = 0.3
EWMA_ALPHA: Final[float] = 0.1
MIN_SIGNAL_THRESHOLD: Final[float] = 0.005


def get_credibility(state: CredibilityState, bucket: str) -> float:
    return state.bucket_cred.get(bucket, COLD_START_PRIOR)


def update_credibility(
    state: CredibilityState,
    bucket: str,
    predicted_delta: float,
    realized_return: float,
) -> None:
    """EWMA update. Persists state after each update."""
    if abs(predicted_delta) < MIN_SIGNAL_THRESHOLD or abs(realized_return) < MIN_SIGNAL_THRESHOLD:
        return
    hit = 1.0 if predicted_delta * realized_return > 0 else 0.0
    current = get_credibility(state, bucket)
    state.bucket_cred[bucket] = (1 - EWMA_ALPHA) * current + EWMA_ALPHA * hit
    state.history_count += 1
    state.last_updated = date.today()
    save_credibility(state)


def load_credibility() -> CredibilityState:
    if not CRED_PATH.exists():
        return CredibilityState(bucket_cred={}, history_count=0,
                                  last_updated=date.today())
    data = json.loads(CRED_PATH.read_text())
    return CredibilityState(
        bucket_cred=data.get("bucket_cred", {}),
        history_count=data.get("history_count", 0),
        last_updated=date.fromisoformat(data.get("last_updated", date.today().isoformat())),
    )


def save_credibility(state: CredibilityState) -> None:
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRED_PATH.write_text(json.dumps({
        "bucket_cred": state.bucket_cred,
        "history_count": state.history_count,
        "last_updated": state.last_updated.isoformat(),
    }, indent=2))
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/overlay/test_credibility.py -v
git add tradingagents/skills/overlay/credibility.py tests/unit/skills/overlay/test_credibility.py
git commit -m "feat(tier3): credibility EWMA + JSON persistence"
```

---

## Task 5: apply_llm_overlay (blending + QP direct)

**Files:**
- Create: `tradingagents/skills/overlay/apply.py`
- Create: `tests/unit/skills/overlay/test_apply.py`

- [ ] **Step 1: Test**

```python
import pytest
from datetime import date
from tradingagents.schemas.llm_overlay import LLMBucketView, CredibilityState
from tradingagents.skills.overlay.apply import apply_llm_overlay
from tradingagents.skills.research.factor_to_bucket import INITIAL_BASELINE


def _make_view(**deltas):
    defaults = {b: 0.0 for b in [
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    ]}
    defaults.update(deltas)
    return LLMBucketView(**defaults, confidence=0.5, reasoning="", cited_events=[])


def test_apply_overlay_respects_band():
    """Per-bucket delta clipped to ±0.05."""
    quant = dict(INITIAL_BASELINE)
    views = [_make_view(kr_equity=1.0)] * 5  # max positive
    consensus = {b: 1.0 for b in quant}
    cred = CredibilityState(bucket_cred={b: 1.0 for b in quant}, history_count=0,
                              last_updated=date(2026, 6, 1))
    final, audit = apply_llm_overlay(
        quant_target=quant, views=views, novelty=1.0,
        consensus=consensus, credibility=cred,
    )
    # kr_equity delta capped at +0.05
    assert audit["kr_equity"]["clipped_delta"] <= 0.05 + 1e-9
    assert audit["kr_equity"]["clipped_delta"] > 0


def test_apply_overlay_mandate_compliance():
    """final_target sums to 1.0 + risk_buckets ≤ 0.70 (project_to_mandate_qp)."""
    quant = dict(INITIAL_BASELINE)
    views = [_make_view(kr_equity=0.8, global_equity=0.8, precious_metals=0.8,
                         cyclical_commodity_fx=0.8)] * 5
    consensus = {b: 1.0 for b in quant}
    cred = CredibilityState(bucket_cred={b: 1.0 for b in quant}, history_count=0,
                              last_updated=date(2026, 6, 1))
    final, _ = apply_llm_overlay(quant, views, novelty=1.0, consensus=consensus,
                                   credibility=cred)
    assert abs(sum(final.values()) - 1.0) < 1e-6
    from tradingagents.skills.research.factor_to_bucket import RISK_BUCKETS
    risk = sum(final[b] for b in RISK_BUCKETS)
    assert risk <= 0.70 + 1e-6


def test_apply_overlay_zero_novelty_unchanged():
    """novelty=0 → no LLM effect, final_target == quant_target."""
    quant = dict(INITIAL_BASELINE)
    views = [_make_view(kr_equity=0.5)] * 5
    cred = CredibilityState(bucket_cred={b: 1.0 for b in quant}, history_count=0,
                              last_updated=date(2026, 6, 1))
    final, _ = apply_llm_overlay(quant, views, novelty=0.0,
                                   consensus={b: 1.0 for b in quant},
                                   credibility=cred)
    for b in quant:
        assert abs(final[b] - quant[b]) < 1e-9
```

- [ ] **Step 2: Implement**

`tradingagents/skills/overlay/apply.py`:
```python
"""Tier 3 LLM overlay blending + mandate projection."""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

from tradingagents.schemas.llm_overlay import (
    LLMBucketView, CredibilityState,
)
from tradingagents.skills.overlay.credibility import get_credibility
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS, project_to_mandate_qp,
)

logger = logging.getLogger(__name__)

BAND: Final[float] = 0.05  # ±5pp per-bucket delta cap


def _aggregate_views(views: list[LLMBucketView]) -> dict[str, float]:
    """Per-bucket mean delta × average confidence."""
    if not views:
        return {b: 0.0 for b in BUCKETS}
    avg_conf = float(np.mean([v.confidence for v in views]))
    result = {}
    for bucket in BUCKETS:
        deltas = [getattr(v, bucket) for v in views]
        result[bucket] = float(np.mean(deltas)) * avg_conf
    return result


def apply_llm_overlay(
    quant_target: dict[str, float],
    views: list[LLMBucketView],
    novelty: float,
    consensus: dict[str, float],
    credibility: CredibilityState,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Blend quant + LLM directional view → mandate-compliant target.

    w_LLM(b) = novelty × consensus[b] × credibility[b]
    delta(b) = clip(w_LLM × avg_delta × avg_confidence, -BAND, +BAND)
    blended(b) = quant_target[b] + delta(b)
    final = project_to_mandate_qp(blended)
    """
    avg_delta = _aggregate_views(views)
    audit: dict[str, dict[str, float]] = {}
    blended = dict(quant_target)
    for bucket in BUCKETS:
        w = novelty * consensus.get(bucket, 0.0) * get_credibility(credibility, bucket)
        raw_delta = w * avg_delta.get(bucket, 0.0)
        clipped = float(np.clip(raw_delta, -BAND, BAND))
        blended[bucket] = quant_target.get(bucket, 0.0) + clipped
        audit[bucket] = {
            "quant":          quant_target.get(bucket, 0.0),
            "llm_avg_delta":  avg_delta.get(bucket, 0.0),
            "w_LLM":          w,
            "clipped_delta":  clipped,
            "blended":        blended[bucket],
        }
    final = project_to_mandate_qp(blended)
    return final, audit


__all__ = ["apply_llm_overlay", "BAND"]
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/overlay/test_apply.py -v
git add tradingagents/skills/overlay/apply.py tests/unit/skills/overlay/test_apply.py
git commit -m "feat(tier3): apply_llm_overlay (novelty×consensus×credibility blending + QP)"
```

---

## Task 6: LLM bucket overlay (prompt + K-sample generation)

**Files:**
- Create: `tradingagents/agents/overlay/__init__.py` (empty)
- Create: `tradingagents/agents/overlay/llm_bucket_overlay.py`
- Create: `tests/unit/agents/overlay/test_llm_bucket_overlay.py`

- [ ] **Step 1: Test (mock LLM)**

```python
import pytest
from unittest.mock import patch, AsyncMock
from datetime import date
import asyncio
from tradingagents.schemas.llm_overlay import LLMBucketView


def test_generate_llm_views_k_samples(monkeypatch):
    """K=5 → 5 LLMBucketView returned."""
    async def _mock_complete(**kwargs):
        return LLMBucketView(
            kr_equity=0.5, global_equity=0.0, precious_metals=0.0,
            cyclical_commodity_fx=0.0, kr_bond=0.0, credit=0.0,
            global_duration=0.0, cash_mmf=0.0,
            confidence=0.6, reasoning="mock", cited_events=[],
        )
    
    from tradingagents.agents.overlay import llm_bucket_overlay as mod
    mock_client = AsyncMock()
    mock_client.complete = _mock_complete
    monkeypatch.setattr(mod, "_get_llm_client", lambda: mock_client)
    
    state = {"macro_summary": "test", "risk_summary": "", "technical_summary": "", "news_summary": ""}
    factor_z = {f: 0.0 for f in ["F1_growth", "F2_inflation"]}
    quant = {b: 0.125 for b in [
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    ]}
    views = asyncio.run(mod.generate_llm_views(
        state=state, factor_z=factor_z, quant_target=quant, k=5,
    ))
    assert len(views) == 5
    assert all(isinstance(v, LLMBucketView) for v in views)
```

- [ ] **Step 2: Implement**

`tradingagents/agents/overlay/llm_bucket_overlay.py`:
```python
"""Tier 3 LLM bucket overlay: prompt assembly + K-sample LLM forward."""
from __future__ import annotations

import json
import logging
from typing import Any

from tradingagents.schemas.llm_overlay import LLMBucketView

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a senior macroeconomic strategist for a KRW-denominated 
multi-asset portfolio. Output a directional view on 8 bucket allocations.

Output STRICT JSON conforming to LLMBucketView schema. Per-bucket delta ∈ [-1, +1].
- +1 = strongly increase from quant baseline
- 0  = no view (neutral)
- -1 = strongly decrease

Rules:
1. NO arithmetic — output directional view only, not specific weights
2. CITE sources from provided analyst narratives (cited_events field)
3. Confidence reflects YOUR uncertainty, not market volatility
4. Reasoning must be in 500 chars max, KR or EN
5. Your view should ADD value beyond quant — focus on what quant z-scores might miss:
   - Breaking events / policy surprises (recent news)
   - Regime shifts (correlation breakdown, structural shifts)
   - Qualitative signals (central bank tone, geopolitical narrative)

Buckets: kr_equity, global_equity, precious_metals, cyclical_commodity_fx,
kr_bond, credit, global_duration, cash_mmf.
"""


def _build_analyst_context(state: Any) -> str:
    """State is dict-like (AgentState TypedDict). Extract *_summary fields."""
    sections = []
    for key, title in [
        ("macro_summary", "Macro (macro_quant_analyst)"),
        ("risk_summary", "Market Risk (market_risk_analyst)"),
        ("technical_summary", "Technical (technical_analyst)"),
        ("news_summary", "News (macro_news_analyst)"),
    ]:
        text = state.get(key) if isinstance(state, dict) else getattr(state, key, "")
        if text:
            sections.append(f"## {title}\n{text}")
    return "\n\n".join(sections)


def _build_factor_context(factor_z: dict[str, float]) -> str:
    lines = ["Factor z-scores (Stage 2 factor model):"]
    for f, z in sorted(factor_z.items()):
        # Simple interpretation
        if abs(z) < 0.25:
            interp = "neutral"
        elif abs(z) < 1.0:
            interp = "modest"
        elif abs(z) < 2.0:
            interp = "strong"
        else:
            interp = "extreme"
        sign = "+" if z >= 0 else "-"
        lines.append(f"  {f}: z={sign}{abs(z):.2f} ({interp})")
    return "\n".join(lines)


def _build_audit_context(safety_diag: dict | None) -> str:
    if not safety_diag:
        return ""
    notes = []
    if safety_diag.get("cap_hits", 0) > 0:
        notes.append(f"⚠️  {safety_diag['cap_hits']} factor×bucket cells saturated at cap")
    if safety_diag.get("projection_intervened"):
        notes.append("⚠️  Mandate constraint actively binding")
    if safety_diag.get("extreme_factor_active"):
        notes.append("⚠️  Extreme factor z (|z|≥2.5) detected")
    return "Quant model limits:\n" + "\n".join(notes) if notes else ""


def build_user_prompt(
    state: Any, factor_z: dict[str, float], quant_target: dict[str, float],
    safety_diag: dict | None = None,
) -> str:
    return f"""=== Stage 1 Analyst Reports ===

{_build_analyst_context(state)}

=== Stage 2 Factor Model Signals ===

{_build_factor_context(factor_z)}

{_build_audit_context(safety_diag)}

=== Stage 2 Quant Bucket Target ===

{json.dumps(quant_target, indent=2)}

=== Task ===

Review the analyst narratives and factor signals above. Identify:
1. Macro/news signals that quant z-scores might be UNDER-weighting
2. Regime characteristics that linear factor model might miss
3. Tail risks or asymmetric scenarios not captured by mean-variance logic

Then output your directional view as LLMBucketView JSON.
"""


def _get_llm_client():
    """Return the configured LLM client. Replace with actual provider routing."""
    # Pattern depends on tradingagents/llm_clients/ — adapt to project's client factory.
    from tradingagents.llm_clients.openai_client import OpenAIClient
    return OpenAIClient(model="claude-sonnet-4-6")  # example


async def generate_llm_views(
    state: Any,
    factor_z: dict[str, float],
    quant_target: dict[str, float],
    safety_diag: dict | None = None,
    k: int = 5,
    temperature: float = 0.7,
) -> list[LLMBucketView]:
    """K independent stochastic samples (consensus estimation)."""
    user_prompt = build_user_prompt(state, factor_z, quant_target, safety_diag)
    client = _get_llm_client()
    views: list[LLMBucketView] = []
    for i in range(k):
        try:
            v = await client.complete(
                system=SYSTEM_PROMPT, user=user_prompt,
                response_schema=LLMBucketView, temperature=temperature,
            )
            views.append(v)
        except Exception as e:
            logger.warning("LLM sample %d failed: %s", i, e)
    return views


__all__ = ["generate_llm_views", "build_user_prompt", "SYSTEM_PROMPT"]
```

- [ ] **Step 3: Test + commit**

```bash
mkdir -p tests/unit/agents/overlay tradingagents/agents/overlay
touch tradingagents/agents/overlay/__init__.py tests/unit/agents/overlay/__init__.py
pytest tests/unit/agents/overlay/test_llm_bucket_overlay.py -v
git add tradingagents/agents/overlay/ tests/unit/agents/overlay/
git commit -m "feat(tier3): generate_llm_views (K-sample prompt assembly + LLM call)"
```

---

## Task 7: research_manager integration (feature-flagged)

**Files:**
- Modify: `tradingagents/agents/managers/research_manager.py`
- Modify: `tradingagents/default_config.py`

- [ ] **Step 1: Add config flags**

In `tradingagents/default_config.py`:
```python
DEFAULT_CONFIG = {
    # ... existing ...
    "tier3_llm_overlay_enabled":  False,  # default OFF
    "tier3_llm_k_samples":        5,
    "tier3_band":                 0.05,
    "tier3_ewma_alpha":           0.10,
    "tier3_cred_cold_start":      0.30,
}
```

- [ ] **Step 2: Add overlay hook to research_manager**

Locate where bucket_target is assigned in research_manager. Add after:
```python
# After factor_scores + bucket are computed
import asyncio
from tradingagents.skills.overlay.novelty import compute_novelty, append_daily_salience
from tradingagents.skills.overlay.consensus import compute_consensus
from tradingagents.skills.overlay.credibility import load_credibility
from tradingagents.skills.overlay.apply import apply_llm_overlay
from tradingagents.agents.overlay.llm_bucket_overlay import generate_llm_views

# Salience persistence (every run)
news_report = state.get("news_report")
as_of_str = state.get("as_of_date")
as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date() if as_of_str else date.today()
if news_report is not None:
    try:
        append_daily_salience(news_report, as_of)
    except Exception as e:
        logger.warning("salience persistence failed: %s", e)

# Tier 3 overlay (feature-flagged)
if config.get("tier3_llm_overlay_enabled", False):
    try:
        views = asyncio.run(generate_llm_views(
            state=state, factor_z=factor_z, quant_target=bucket,
            safety_diag=safety_diag, k=config.get("tier3_llm_k_samples", 5),
        ))
        novelty = compute_novelty(news_report, as_of)
        consensus = compute_consensus(views)
        cred = load_credibility()
        final_bucket, overlay_audit = apply_llm_overlay(
            quant_target=bucket, views=views,
            novelty=novelty, consensus=consensus, credibility=cred,
        )
        bucket = final_bucket  # overwrite for downstream
        state["tier3_overlay_audit"] = overlay_audit
        logger.info("Tier 3 overlay applied (novelty=%.2f)", novelty)
    except Exception as e:
        logger.warning("Tier 3 overlay failed, falling back to quant: %s", e)
```

- [ ] **Step 3: Smoke test**

```bash
# Run e2e with tier3 OFF (default) → should behave as before
python scripts/run_e2e_test.py 2>&1 | tail -10
# Verify no errors
```

- [ ] **Step 4: Commit**

```bash
git add tradingagents/agents/managers/research_manager.py tradingagents/default_config.py
git commit -m "feat(tier3): research_manager Tier 3 overlay hook (feature-flagged OFF default)"
```

---

## Task 8: forward-tuning auto-tune

**Files:**
- Create: `tradingagents/skills/overlay/forward_tuning.py`
- Create: `tests/unit/skills/overlay/test_forward_tuning.py`

- [ ] **Step 1: Test**

```python
import pytest
from datetime import date
from tradingagents.schemas.llm_overlay import CredibilityState
from tradingagents.skills.overlay.forward_tuning import auto_tune_band


def test_auto_tune_band_tightens_when_low_cred():
    cs = CredibilityState(
        bucket_cred={"kr_equity": 0.30, "global_equity": 0.32, "precious_metals": 0.28,
                      "cyclical_commodity_fx": 0.30, "kr_bond": 0.30,
                      "credit": 0.30, "global_duration": 0.30, "cash_mmf": 0.30},
        history_count=8 * 6,  # 6 rebalances × 8 buckets
        last_updated=date(2026, 7, 15),
    )
    new = auto_tune_band(cs, current_band=0.05)
    assert new == 0.04  # tightened by 0.01


def test_auto_tune_band_loosens_when_high_cred():
    cs = CredibilityState(
        bucket_cred={b: 0.70 for b in [
            "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
            "kr_bond", "credit", "global_duration", "cash_mmf",
        ]},
        history_count=8 * 6,
        last_updated=date(2026, 7, 15),
    )
    new = auto_tune_band(cs, current_band=0.05)
    assert new == 0.06  # loosened


def test_auto_tune_band_insufficient_history_unchanged():
    cs = CredibilityState(bucket_cred={"kr_equity": 0.7}, history_count=5,
                           last_updated=date(2026, 6, 15))
    new = auto_tune_band(cs, current_band=0.05)
    assert new == 0.05
```

- [ ] **Step 2: Implement**

```python
"""Tier 3 forward-tuning: BAND auto-adjustment based on credibility history."""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

from tradingagents.schemas.llm_overlay import CredibilityState

logger = logging.getLogger(__name__)

LOW_CRED_THRESHOLD:  Final[float] = 0.40
HIGH_CRED_THRESHOLD: Final[float] = 0.60
BAND_MIN: Final[float] = 0.03
BAND_MAX: Final[float] = 0.07
MIN_HISTORY_REBALANCES: Final[int] = 6
BUCKETS_PER_REBALANCE: Final[int] = 8


def auto_tune_band(state: CredibilityState, current_band: float) -> float:
    """After 6+ rebalances, adjust BAND ±0.01 based on average cred.

    cred < 0.40 → tighten BAND (LLM unreliable)
    cred > 0.60 → loosen BAND (LLM reliable)
    """
    if state.history_count < MIN_HISTORY_REBALANCES * BUCKETS_PER_REBALANCE:
        return current_band
    if not state.bucket_cred:
        return current_band
    avg_cred = float(np.mean(list(state.bucket_cred.values())))
    if avg_cred < LOW_CRED_THRESHOLD:
        new_band = max(BAND_MIN, current_band - 0.01)
    elif avg_cred > HIGH_CRED_THRESHOLD:
        new_band = min(BAND_MAX, current_band + 0.01)
    else:
        new_band = current_band
    if new_band != current_band:
        logger.info("Tier 3 BAND auto-tune: %.2f → %.2f (avg_cred=%.2f)",
                    current_band, new_band, avg_cred)
    return new_band
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/overlay/test_forward_tuning.py -v
git add tradingagents/skills/overlay/forward_tuning.py tests/unit/skills/overlay/test_forward_tuning.py
git commit -m "feat(tier3): auto_tune_band (cred-based BAND ±0.01 adjustment)"
```

---

## Task 9: Integration test (end-to-end Tier 3)

**Files:**
- Create: `tests/integration/test_tier3_overlay_pipeline.py`

- [ ] **Step 1: Test (mocked LLM)**

```python
import asyncio
import pytest
from datetime import date
from unittest.mock import patch, AsyncMock
from tradingagents.schemas.llm_overlay import LLMBucketView, CredibilityState
from tradingagents.skills.overlay.novelty import compute_novelty, append_daily_salience
from tradingagents.skills.overlay.consensus import compute_consensus
from tradingagents.skills.overlay.credibility import load_credibility
from tradingagents.skills.overlay.apply import apply_llm_overlay
from tradingagents.agents.overlay.llm_bucket_overlay import generate_llm_views
from tradingagents.skills.research.factor_to_bucket import INITIAL_BASELINE


@pytest.mark.asyncio
async def test_tier3_pipeline_end_to_end(tmp_path, monkeypatch):
    """Mock LLM → views → blend → mandate-compliant final."""
    monkeypatch.setattr("tradingagents.skills.overlay.novelty.SALIENCE_HISTORY_PATH",
                        tmp_path / "salience.parquet")
    monkeypatch.setattr("tradingagents.skills.overlay.credibility.CRED_PATH",
                        tmp_path / "cred.json")
    
    # Mock LLM
    async def _mock_complete(**kwargs):
        return LLMBucketView(
            kr_equity=0.4, global_equity=0.3, precious_metals=-0.2,
            cyclical_commodity_fx=0.1, kr_bond=-0.3, credit=-0.1,
            global_duration=-0.2, cash_mmf=0.0,
            confidence=0.6, reasoning="test", cited_events=[],
        )
    mock_client = AsyncMock()
    mock_client.complete = _mock_complete
    monkeypatch.setattr("tradingagents.agents.overlay.llm_bucket_overlay._get_llm_client",
                        lambda: mock_client)
    
    state = {
        "macro_summary": "Growth firming, inflation stable",
        "risk_summary": "VIX low",
        "technical_summary": "Equity momentum positive",
        "news_summary": "FOMC dovish-leaning",
    }
    factor_z = {"F1_growth": 1.2, "F2_inflation": -0.3}
    quant = dict(INITIAL_BASELINE)
    
    views = await generate_llm_views(state, factor_z, quant, k=5)
    assert len(views) == 5
    
    novelty = compute_novelty(None, date(2026, 6, 1))  # 0 (no history)
    consensus = compute_consensus(views)
    cred = load_credibility()
    final, audit = apply_llm_overlay(quant, views, novelty, consensus, cred)
    
    # Mandate compliance
    assert abs(sum(final.values()) - 1.0) < 1e-6
    from tradingagents.skills.research.factor_to_bucket import RISK_BUCKETS
    assert sum(final[b] for b in RISK_BUCKETS) <= 0.70 + 1e-6
    
    # Zero novelty → no change
    for b in quant:
        assert abs(final[b] - quant[b]) < 1e-6
```

- [ ] **Step 2: Test + commit**

```bash
pytest tests/integration/test_tier3_overlay_pipeline.py -v
git add tests/integration/test_tier3_overlay_pipeline.py
git commit -m "test(tier3): integration — mocked LLM → blend → mandate-compliant final"
```

---

## Acceptance Checklist

- [ ] LLMBucketView schema validates delta ∈ [-1, +1] per bucket
- [ ] CredibilityState + LLMOverlayJournal schemas
- [ ] compute_novelty returns 0 when history < 10 days
- [ ] Salience parquet append idempotent (same date no-op)
- [ ] compute_consensus: unanimous → 1.0, split 3-2 → 0.2, all neutral → 0
- [ ] update_credibility: hit increases cred per EWMA α=0.1, miss decreases
- [ ] save/load credibility roundtrip preserves state
- [ ] apply_llm_overlay clips per-bucket delta to ±BAND (0.05)
- [ ] apply_llm_overlay output mandate-compliant (sum=1, risk≤0.70 via QP)
- [ ] novelty=0 → final == quant (no LLM effect)
- [ ] generate_llm_views: K=5 LLMBucketView returned (mock)
- [ ] build_user_prompt assembles 4 analyst summaries + factor z + quant target
- [ ] research_manager Tier 3 hook (feature-flagged OFF default)
- [ ] auto_tune_band: cred<0.40 tighten, cred>0.60 loosen, otherwise unchanged
- [ ] insufficient history (<6 rebalances) → BAND unchanged
- [ ] Integration test: end-to-end mock LLM → mandate compliance verified

---

**Plan saved to `docs/superpowers/plans/2026-05-28-tier3-llm-overlay.md`.**

---

# Execution Choice (All 4 Tier Plans)

4 plans complete and saved:
- `docs/superpowers/plans/2026-05-28-tier0-factor-model-reform.md`
- `docs/superpowers/plans/2026-05-28-tier1-bucket-taxonomy.md`
- `docs/superpowers/plans/2026-05-28-tier2-calibration.md`
- `docs/superpowers/plans/2026-05-28-tier3-llm-overlay.md`

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task with two-stage review between tasks. Best for high-quality implementation with deliberate review checkpoints.

2. **Inline Execution** — batch execution in current session via `superpowers:executing-plans`, with manual checkpoints.

**Recommended sequence:** T0 → T1 → T2 → T3 (dependency order). Each tier completable independently.
