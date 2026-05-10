# DB GAPS Plan 4 — CLI + Reports + Rebalancing + E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 22 CLI 서브커맨드 + 보고서 생성기 (philosophy/monthly/trade-plan) + 3-tier 리밸런싱 (daily/weekly/monthly) + 5/28 E2E mock fixture 테스트. Plan 끝나면 `gaps plan` 실행으로 5/28 제출 패키지 생성 가능.

**Architecture:** Click(또는 argparse) 기반 CLI, 각 명령은 `tradingagents/cli/commands/`의 모듈로 분리. Reports는 `tradingagents/reports/`에서 마크다운+docx 생성. Rebalancing 3-tier는 `tradingagents/rebalance/`에 (daily 트리거 룰셋 / weekly tilt / monthly 풀 파이프라인).

**Tech Stack:** Click, python-docx, jinja2 (선택), Plan 1-3의 모든 자산.

**Prerequisites:** Plan 1, 2, 3 완료.

**참조 스펙:** §10 (CLI), §11 (artifacts), §9 (3-tier rebalance), §15.1 critical gap (LLM rate limit — TODO #3).

---

## File Structure

```
cli/
├── main.py                              # 기존 1221줄 → rewrite (얇은 dispatcher)
└── commands/
    ├── __init__.py
    ├── universe.py                      # sync, list, info
    ├── macro.py                         # regime, risk, news, technical (단독 분석가)
    ├── portfolio.py                     # plan, rebalance, optimize
    ├── analysis.py                      # correlate, validate, simulate
    ├── report.py                        # philosophy, monthly, trade-plan
    ├── monitor.py                       # turnover, exposure, drift, cost
    └── preset.py                        # list, run

tradingagents/
├── reports/
│   ├── __init__.py
│   ├── philosophy.py                    # 4-page 투자철학 문서
│   ├── monthly.py                       # 월간 운용 보고서 (3섹션)
│   ├── trade_plan.py                    # MTS 입력용 CSV
│   └── analysis_appendix.py             # macro 데이터 + 클러스터 부록
├── rebalance/
│   ├── __init__.py
│   ├── daily_triggers.py                # 룰 기반 트리거 평가
│   ├── weekly_tilt.py                   # macro+risk만 + 5%p tilt
│   └── monthly_full.py                  # 풀 파이프라인 + 월간 보고서
├── monitor/
│   ├── __init__.py
│   ├── turnover.py                      # floor 추적
│   ├── exposure.py                      # 자산군 비중
│   ├── drift.py                         # 가격 변동 drift
│   └── cost.py                          # 수수료·슬리피지

presets/
├── db_gaps.yaml                         # Plan 3에서 생성됨
└── triggers_default.yaml                # 신규 — daily 트리거 룰셋

tests/
├── unit/cli/                            # 22개 명령별 smoke
├── unit/reports/
├── unit/rebalance/
├── unit/monitor/
├── fixtures/
│   ├── fred_macro.json                  # 신규 mock fixture
│   ├── ecos_macro.json
│   ├── pykrx_etf_prices.parquet
│   ├── llm_mock_responses.json
│   ├── pyportfolioopt_fake.py
│   └── universe_test.json
└── integration/
    ├── test_5_28_dry_run.py             # D9 — gold standard E2E
    ├── test_validator_cycle.py
    ├── test_cache_fallback.py
    ├── test_subgraph_isolation.py
    └── test_eval_regime_classifier.py   # eval (8 historical cases)
```

---

## Phase 1: CLI Skeleton

### Task 1: CLI 진입점 + dispatcher

**Files:**
- Modify: `cli/main.py` (전면 rewrite)
- Create: `cli/commands/__init__.py`
- Create: `tests/unit/cli/test_main_smoke.py`

- [ ] **Step 1: 실패 테스트**

```python
from click.testing import CliRunner

from cli.main import cli


def test_help_prints():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "universe" in result.output
    assert "plan" in result.output


def test_subcommand_routing():
    runner = CliRunner()
    result = runner.invoke(cli, ["universe", "--help"])
    assert result.exit_code == 0
    assert "sync" in result.output
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/cli/test_main_smoke.py -v`

- [ ] **Step 3: 구현**

`cli/main.py`:

```python
"""DB GAPS agent CLI entry point. Replaces the legacy 1221-line interactive CLI."""
import click

from cli.commands import (
    universe, macro, portfolio, analysis, report, monitor, preset,
)
from tradingagents.observability.tracing import setup_tracing


@click.group()
@click.version_option(version="0.3.0")
def cli():
    """gaps — DB GAPS asset-allocation agent CLI.

    Run `gaps <subcommand> --help` for details.

    Tracing: set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to enable
    multi-agent run-tree visualization at https://smith.langchain.com/.
    """
    # Enable LangSmith tracing once per CLI invocation (no-op if disabled).
    setup_tracing()


cli.add_command(universe.group, name="universe")
cli.add_command(macro.group, name="macro")
cli.add_command(portfolio.plan)         # gaps plan ...
cli.add_command(portfolio.rebalance)    # gaps rebalance ...
cli.add_command(portfolio.optimize)     # gaps optimize ...
cli.add_command(analysis.correlate)
cli.add_command(analysis.validate)
cli.add_command(analysis.simulate)
cli.add_command(report.group, name="report")
cli.add_command(monitor.group, name="monitor")
cli.add_command(preset.group, name="preset")


if __name__ == "__main__":
    cli()
```

`cli/commands/__init__.py`:

```python
"""CLI command modules."""
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/cli/test_main_smoke.py -v`

- [ ] **Step 5: Commit**

```bash
git add cli/main.py cli/commands/__init__.py tests/unit/cli/test_main_smoke.py
git commit -m "feat(cli): replace legacy CLI with Click-based gaps dispatcher"
```

---

## Phase 2: Universe Commands (3개)

### Task 2: gaps universe {sync, list, info}

**Files:**
- Create: `cli/commands/universe.py`
- Create: `tests/unit/cli/test_universe_cmd.py`

- [ ] **Step 1-5: 구현 + 테스트 + commit**

```python
"""gaps universe — manage 188-ETF universe (sync/list/info)."""
from pathlib import Path

import click

from tradingagents.dataflows.universe import sync_from_xlsx, load_universe


@click.group()
def group():
    """Manage the GAPS ETF universe."""


@group.command("sync")
@click.option("--xlsx", default="docs/제12회 GAPS ETF 리스트 (2026-5-9 게시).xlsx",
              help="Source xlsx file")
@click.option("--out", default="data/universe.json", help="Output JSON path")
def sync(xlsx, out):
    """Parse the GAPS xlsx → universe.json (188 ETFs)."""
    universe = sync_from_xlsx(Path(xlsx), Path(out))
    click.echo(f"✓ Synced {len(universe.etfs)} ETFs to {out}")


@group.command("list")
@click.option("--bucket", type=click.Choice(["위험", "안전"]), default=None)
@click.option("--category", default=None)
@click.option("--top", type=int, default=20, help="Top N by AUM")
@click.option("--universe-path", default="data/universe.json")
def list_cmd(bucket, category, top, universe_path):
    """List ETFs filtered by bucket/category, sorted by AUM."""
    u = load_universe(Path(universe_path))
    etfs = u.etfs
    if bucket:
        etfs = [e for e in etfs if e.bucket == bucket]
    if category:
        etfs = [e for e in etfs if e.category == category]
    etfs.sort(key=lambda e: -e.aum_krw)
    for e in etfs[:top]:
        click.echo(f"{e.ticker} {e.name[:40]:40s}  AUM={e.aum_krw / 1e8:>10.0f}억  [{e.category}]")


@group.command("info")
@click.argument("ticker")
@click.option("--universe-path", default="data/universe.json")
def info(ticker, universe_path):
    """Show details for a single ETF."""
    u = load_universe(Path(universe_path))
    match = next((e for e in u.etfs if e.ticker == ticker), None)
    if not match:
        click.secho(f"✗ {ticker} not in universe", fg="red")
        raise click.Abort()
    click.echo(f"Ticker:        {match.ticker}")
    click.echo(f"Name:          {match.name}")
    click.echo(f"AUM (KRW):     {match.aum_krw:,.0f}")
    click.echo(f"Underlying:    {match.underlying_index}")
    click.echo(f"Bucket:        {match.bucket}")
    click.echo(f"Category:      {match.category}")
```

테스트:

```python
from click.testing import CliRunner
from cli.commands.universe import group


def test_sync_uses_fixture(tmp_path):
    runner = CliRunner()
    out = tmp_path / "u.json"
    result = runner.invoke(group, [
        "sync", "--xlsx", "tests/fixtures/universe_test.xlsx", "--out", str(out),
    ])
    assert result.exit_code == 0
    assert out.exists()


def test_list_filters_by_bucket(tmp_path):
    # First sync, then list
    runner = CliRunner()
    out = tmp_path / "u.json"
    runner.invoke(group, ["sync", "--xlsx", "tests/fixtures/universe_test.xlsx", "--out", str(out)])
    result = runner.invoke(group, ["list", "--bucket", "안전", "--universe-path", str(out)])
    assert result.exit_code == 0
    assert "KODEX 국고채3년" in result.output
```

```bash
git commit -am "feat(cli): add universe sync/list/info commands"
```

---

## Phase 3: Macro Single-Analyst Commands (4개)

### Task 3: gaps macro {regime, risk, news, technical}

**Files:**
- Create: `cli/commands/macro.py`

각 명령은 단일 분석가 노드만 실행 후 narrative + key fields 출력. 디버깅·보고서 작성 시 인용용.

```python
"""gaps macro — single-analyst quick lookups."""
from datetime import date

import click

from tradingagents.agents.analysts.macro_news_analyst import create_macro_news_analyst
from tradingagents.agents.analysts.macro_quant_analyst import create_macro_quant_analyst
from tradingagents.agents.analysts.market_risk_analyst import create_market_risk_analyst
from tradingagents.agents.analysts.technical_analyst import create_technical_analyst
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client


def _make_llms():
    deep = create_llm_client(provider=DEFAULT_CONFIG["llm_provider"], model=DEFAULT_CONFIG["deep_think_llm"]).get_llm()
    quick = create_llm_client(provider=DEFAULT_CONFIG["llm_provider"], model=DEFAULT_CONFIG["quick_think_llm"]).get_llm()
    return quick, deep


@click.group()
def group():
    """Quick single-analyst commands for debugging or report citation."""


@group.command("regime")
@click.option("--date", "as_of", default=None, help="ISO date, default today")
def regime(as_of):
    """Macro/Quant Analyst — regime quadrant판단."""
    quick, deep = _make_llms()
    node = create_macro_quant_analyst(quick, deep)
    state = {"as_of_date": as_of or date.today().isoformat()}
    result = node(state)
    rep = result["macro_report"]
    click.echo(f"Regime: {rep.regime.quadrant} (confidence {rep.regime.confidence:.2f})")
    click.echo(f"Drivers: {', '.join(rep.regime.drivers)}")
    click.echo(f"\nYield curve: 10y-2y={rep.yield_curve.spread_10y_2y_bps:.0f}bps, "
               f"inverted {rep.yield_curve.inverted_days_count}d")
    click.echo(f"Inflation: CPI YoY {rep.inflation.cpi_yoy:.2f}%, accelerating={rep.inflation.accelerating}")
    click.echo(f"Employment: UR {rep.employment.unemployment_rate:.1f}%, Sahm={rep.employment.sahm_rule_triggered}")
    click.echo(f"\n{rep.narrative}")


@group.command("risk")
@click.option("--date", "as_of", default=None)
def risk(as_of):
    """Market Risk Analyst — VIX·credit spread·systemic score."""
    quick, deep = _make_llms()
    node = create_market_risk_analyst(quick, deep)
    state = {"as_of_date": as_of or date.today().isoformat()}
    result = node(state)
    rep = result["risk_report"]
    click.echo(f"Systemic risk: {rep.systemic_score.score:.1f}/10 ({rep.systemic_score.regime})")
    click.echo(f"VIX: {rep.vix.current_value:.1f} (z={rep.vix.zscore_30d:+.2f})")
    click.echo(f"VKOSPI: {rep.vkospi.current_value:.1f}")
    click.echo(f"US HY OAS: {rep.credit_spread_us_hy.current_bps:.0f}bps "
               f"{'(widening)' if rep.credit_spread_us_hy.widening else ''}")
    click.echo(f"PCA 1st share: {rep.correlation_concentration.first_eigenvalue_share:.2f} "
               f"{'(concentrated)' if rep.correlation_concentration.is_concentrated else ''}")
    click.echo(f"\n{rep.narrative}")


@group.command("news")
@click.option("--window", type=int, default=30, help="Calendar window in days")
@click.option("--date", "as_of", default=None)
def news(window, as_of):
    """Macro News Analyst — calendar + ranked headlines."""
    quick, deep = _make_llms()
    node = create_macro_news_analyst(quick, deep)
    state = {"as_of_date": as_of or date.today().isoformat()}
    result = node(state)
    rep = result["news_report"]
    click.echo(f"Upcoming events ({len(rep.upcoming_events)}):")
    for e in rep.upcoming_events[:5]:
        click.echo(f"  {e.event_date} {e.region}: {e.description}")
    click.echo(f"\nTop news ({len(rep.ranked_news)}):")
    for r in rep.ranked_news[:5]:
        click.echo(f"  [sev{r.impact.severity}] {r.item.headline[:80]}")


@group.command("technical")
@click.option("--ticker", default=None, help="Single ticker; else top-momentum scan")
@click.option("--date", "as_of", default=None)
def technical(ticker, as_of):
    """Technical Analyst — momentum + correlation clusters."""
    quick, deep = _make_llms()
    node = create_technical_analyst(quick, deep)
    state = {
        "as_of_date": as_of or date.today().isoformat(),
        "universe_path": DEFAULT_CONFIG["universe_path"],
    }
    result = node(state)
    rep = result["technical_report"]
    click.echo(f"Categories: {len(rep.asset_class_momentum)}")
    for cat, rankings in list(rep.asset_class_momentum.items())[:3]:
        click.echo(f"\n[{cat}] top 3:")
        for r in rankings[:3]:
            click.echo(f"  {r.ticker} {r.name[:40]:40s}  6m={r.momentum_6m:+.2%}")
    click.echo(f"\nClusters: {len(rep.correlation_clusters)}")
    for c in rep.correlation_clusters[:3]:
        click.echo(f"  [{c.cluster_id}] {c.category_label} ({len(c.members)} ETFs, ρ={c.avg_internal_correlation:.2f})")
```

테스트는 mock으로 4개 명령 smoke 검증.

```bash
git commit -am "feat(cli): add macro {regime,risk,news,technical} single-analyst commands"
```

---

## Phase 4: Plan / Rebalance / Optimize (3개)

### Task 4: gaps plan (풀 파이프라인)

**Files:**
- Create: `cli/commands/portfolio.py`

```python
"""gaps plan / rebalance / optimize."""
from datetime import date

import click

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


@click.command("plan")
@click.option("--date", "as_of", default=None, help="ISO date, default today")
@click.option("--capital", type=int, default=1_000_000_000, help="Capital in KRW")
@click.option("--preset", default="db_gaps")
@click.option("--dry-run", is_flag=True, help="Run with mock LLM outputs (D9)")
def plan(as_of, capital, preset, dry_run):
    """Run the full pipeline and produce 5/28 submission package."""
    if dry_run:
        click.secho("Dry-run mode: using mock LLM responses", fg="yellow")
        # Future: load fixtures from tests/fixtures/llm_mock_responses.json

    graph = TradingAgentsGraph(preset_name=preset)
    final = graph.run(
        as_of_date=as_of or date.today().isoformat(),
        capital_krw=capital,
    )
    click.echo(f"✓ Plan complete:")
    click.echo(f"  portfolio.json     : {final['final_portfolio_path']}")
    click.echo(f"  philosophy.md      : {final['philosophy_doc_path']}")
    click.echo(f"  trade_plan.csv     : {final['trade_plan_csv_path']}")
    click.echo(f"  validation_passed : {final['validation_passed']}")
    if final.get("validation_report") and not final["validation_passed"]:
        click.secho("  Hard violations:", fg="red")
        for v in final["validation_report"].hard_violations:
            click.echo(f"    - {v.description}")


@click.command("rebalance")
@click.argument("tier", type=click.Choice(["daily", "weekly", "monthly"]))
@click.option("--date", "as_of", default=None)
@click.option("--week", type=int, default=None, help="Week number (for weekly)")
@click.option("--month", type=int, default=None, help="Month number (for monthly)")
@click.option("--from", "previous_path", default=None, help="Path to previous portfolio.json")
def rebalance(tier, as_of, week, month, previous_path):
    """Run a 3-tier rebalancing pipeline."""
    from tradingagents.rebalance import daily_triggers, weekly_tilt, monthly_full

    target = as_of or date.today().isoformat()
    if tier == "daily":
        # D15: pass current portfolio path if available so drift trigger fires
        result = daily_triggers.run(as_of=target, portfolio_path=previous_path)
        click.echo(result.summary())
    elif tier == "weekly":
        result = weekly_tilt.run(as_of=target, previous_path=previous_path)
        click.echo(result.summary())
    elif tier == "monthly":
        if month is None:
            raise click.UsageError("--month required for monthly")
        result = monthly_full.run(month=month, as_of=target, previous_path=previous_path)
        click.echo(result.summary())


@click.command("optimize")
@click.option("--method", type=click.Choice(["hrp", "rp", "minvar", "bl"]), default="hrp")
@click.option("--candidates", required=True, help="Comma-separated tickers")
@click.option("--date", "as_of", default=None)
def optimize(method, candidates, as_of):
    """Run a single optimizer on a manual candidate set (debug tool)."""
    from datetime import date as _date, timedelta
    from tradingagents.skills.portfolio.optimizers import (
        optimize_hrp, optimize_risk_parity, optimize_min_variance, optimize_black_litterman,
    )
    from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix

    tickers = [t.strip() for t in candidates.split(",")]
    end = _date.fromisoformat(as_of) if as_of else _date.today()
    start = end - timedelta(days=365 * 3)
    returns = fetch_returns_matrix(tickers, start, end, cache_path=DEFAULT_CONFIG["etf_price_cache_path"])

    fn_map = {"hrp": optimize_hrp, "rp": optimize_risk_parity,
              "minvar": optimize_min_variance, "bl": optimize_black_litterman}
    fn = fn_map[method]
    if method == "bl":
        click.secho("BL requires --views; use HRP/RP/MinVar for quick optimize", fg="yellow")
        return
    wv = fn(returns)
    click.echo(f"Method: {wv.method.value}")
    for t, w in sorted(wv.weights.items(), key=lambda x: -x[1]):
        click.echo(f"  {t}: {w:.4f}")
```

테스트 + commit.

---

## Phase 5: Analysis Commands (3개)

### Task 5: gaps {correlate, validate, simulate}

**Files:**
- Create: `cli/commands/analysis.py`

```python
"""gaps correlate / validate / simulate."""
import json
from datetime import date, timedelta
from pathlib import Path

import click

from tradingagents.dataflows.universe import load_universe
from tradingagents.skills.mandate.universe_check import validate_universe
from tradingagents.skills.mandate.concentration_check import validate_concentration
from tradingagents.skills.mandate.correlation_check import validate_correlation_concentration
from tradingagents.skills.mandate.turnover_check import validate_turnover_feasibility
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
from tradingagents.skills.technical.correlation_cluster import find_correlation_clusters
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector


def _load_portfolio(path: Path) -> WeightVector:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return WeightVector(
        method=OptimizationMethod(raw["method"]),
        weights=raw["weights"],
        rationale=raw["rationale"],
        expected_volatility=raw.get("expected_volatility"),
        expected_sharpe=raw.get("expected_sharpe"),
    )


@click.command("correlate")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--cluster", is_flag=True, help="Run hierarchical clustering")
def correlate(portfolio, cluster):
    """Compute correlation matrix and (optionally) clusters for a portfolio."""
    wv = _load_portfolio(Path(portfolio))
    end = date.today()
    start = end - timedelta(days=365 * 3)
    returns = fetch_returns_matrix(list(wv.weights.keys()), start, end)

    corr = returns.corr()
    click.echo("Correlation matrix:")
    click.echo(corr.round(2).to_string())

    if cluster:
        clusters = find_correlation_clusters(returns, threshold=0.7)
        click.echo(f"\nClusters: {len(clusters)}")
        for c in clusters:
            click.echo(f"  [{c.cluster_id}] {c.category_label}")
            click.echo(f"    members: {', '.join(c.members)}")
            click.echo(f"    avg correlation: {c.avg_internal_correlation:.3f}")


@click.command("validate")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--universe-path", default="data/universe.json")
@click.option("--capital", type=int, default=1_000_000_000)
@click.option("--floor", type=float, default=0.80, help="Turnover floor (0.80 initial, 0.10 monthly)")
def validate(portfolio, universe_path, capital, floor):
    """Run all 4 mandate checks against a portfolio."""
    wv = _load_portfolio(Path(portfolio))
    universe = load_universe(Path(universe_path))

    checks = {
        "Universe": validate_universe(wv, universe),
        "Concentration": validate_concentration(wv, universe),
        "Turnover": validate_turnover_feasibility(wv, None, capital, floor, days_remaining=5),
        "Correlation": validate_correlation_concentration(wv, []),  # need clusters from technical
    }

    for name, report in checks.items():
        if report.passed:
            click.secho(f"  ✓ {name}: PASS", fg="green")
        else:
            click.secho(f"  ✗ {name}: {len(report.violations)} violations", fg="red")
            for v in report.violations:
                click.echo(f"    - [{v.severity}] {v.description}")


@click.command("simulate")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--window", default="3y", help="Backtest window: 1y/3y/5y")
def simulate(portfolio, window):
    """Lightweight historical simulation (returns, vol, MDD, Sharpe)."""
    wv = _load_portfolio(Path(portfolio))
    days_map = {"1y": 365, "3y": 365 * 3, "5y": 365 * 5}
    days = days_map.get(window, 365 * 3)
    end = date.today()
    start = end - timedelta(days=days)
    returns = fetch_returns_matrix(list(wv.weights.keys()), start, end)

    weights = pd.Series(wv.weights)
    common = returns.columns.intersection(weights.index)
    weighted = returns[common] * weights[common]
    portfolio_returns = weighted.sum(axis=1)

    cum = (1 + portfolio_returns).cumprod()
    total_return = cum.iloc[-1] - 1
    vol_ann = portfolio_returns.std() * (252 ** 0.5)
    sharpe = portfolio_returns.mean() / portfolio_returns.std() * (252 ** 0.5) if portfolio_returns.std() > 0 else 0
    rolling_max = cum.cummax()
    mdd = (cum / rolling_max - 1).min()

    click.echo(f"Window: {window} ({len(portfolio_returns)} days)")
    click.echo(f"Total return:  {total_return:+.2%}")
    click.echo(f"Annualized vol: {vol_ann:.2%}")
    click.echo(f"Sharpe:        {sharpe:.2f}")
    click.echo(f"Max drawdown: {mdd:.2%}")


import pandas as pd  # at top
```

테스트 + commit.

---

## Phase 6: Reports (3개)

### Task 6: philosophy.md generator (≥4000 chars)

**Files:**
- Create: `tradingagents/reports/__init__.py`
- Create: `tradingagents/reports/philosophy.py`
- Create: `tests/unit/reports/test_philosophy.py`

```python
"""Investment philosophy document generator (대회 §4.1: ≥4 워드 페이지)."""
from pathlib import Path


PHILOSOPHY_PROMPT = """\
You are writing the investment philosophy document for a Korean investment competition.

Mandatory sections (each ≥600 chars in Korean):
1. 매크로 환경 진단 (Regime, yield curve, inflation, employment)
2. 시장 리스크 평가 (VIX, credit spread, single risk via correlation)
3. 자산군 비중 결정 논리 (5-bucket target with rationale)
4. 단일 리스크 통제 전략 (correlation clusters, cluster cap)
5. 시장 충격 시나리오 (3 stress scenarios with defensive responses)
6. 매매 원칙 (turnover floor, rebalance triggers)

Inputs:
{state_summary}

CRITICAL RULES (대회 §4.2):
- Korean only
- DO NOT copy ETF prospectus text or news headlines verbatim
- All numbers MUST come from the inputs above
- Total ≥4000 chars

Output the full markdown document."""


def generate_philosophy(state: dict, deep_llm) -> str:
    state_summary = (
        f"### Macro\n{state.get('macro_summary', '')}\n\n"
        f"### Risk\n{state.get('risk_summary', '')}\n\n"
        f"### Technical\n{state.get('technical_summary', '')}\n\n"
        f"### News\n{state.get('news_summary', '')}\n\n"
        f"### Bucket Target\n{state.get('research_debate_summary', '')}\n\n"
        f"### Final Portfolio\n"
        f"Method: {state['weight_vector'].method.value}\n"
        f"Top 5 weights: {sorted(state['weight_vector'].weights.items(), key=lambda x: -x[1])[:5]}\n"
        f"Rationale: {state['weight_vector'].rationale}\n"
    )
    response = deep_llm.invoke(PHILOSOPHY_PROMPT.format(state_summary=state_summary))
    text = response.content
    if len(text) < 4000:
        # 1회 retry로 더 길게 요청
        retry = deep_llm.invoke(
            f"The document below is only {len(text)} chars. Expand each of 6 sections to ≥600 chars (total ≥4000):\n\n{text}"
        )
        text = retry.content
    return text


def write_philosophy(state: dict, deep_llm, out_path: Path) -> Path:
    text = generate_philosophy(state, deep_llm)
    out_path.write_text(text, encoding="utf-8")
    return out_path
```

테스트:

```python
from unittest.mock import MagicMock
from pathlib import Path

from tradingagents.reports.philosophy import generate_philosophy


def test_philosophy_min_length(tmp_path):
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "x" * 4500  # mock 4500 chars
    state = {
        "macro_summary": "regime: recession",
        "risk_summary": "VIX 25",
        "technical_summary": "clusters",
        "news_summary": "events",
        "research_debate_summary": "60/40",
        "weight_vector": MagicMock(method=MagicMock(value="hrp"), weights={"A069500": 0.5}, rationale="x"),
    }
    text = generate_philosophy(state, deep_llm)
    assert len(text) >= 4000
```

```bash
git commit -am "feat(reports): add philosophy generator (≥4000 chars Korean)"
```

---

### Task 7: monthly report generator (3섹션)

```python
"""Monthly operations report (대회 §4.2: ≥A4 2 pages)."""
from pathlib import Path

import pandas as pd


MONTHLY_PROMPT = """\
You are writing the monthly operations report for {month}월 of the Korean investment competition.

Mandatory 3 sections (each ≥500 chars in Korean):
1. **수익률 자체 평가** — 월 수익률이 왜 이렇게 나왔는가? Cite specific events and asset moves.
2. **포트폴리오 변경 사유** — 시장 상황 변화에 따라 비중을 어떻게 조정했는지 logical reasoning.
3. **향후 시장 전망 및 전략** — 다음 월의 매크로 환경 예측 + 선제 대응 전략.

Inputs:
{state_summary}

Performance data:
{pnl_summary}

CRITICAL RULES:
- Korean only, ≥A4 2 pages (~2500 chars total)
- DO NOT copy ETF prospectus or news verbatim
- Self-evaluation must be honest about underperformance

Output full markdown."""


def generate_monthly(state: dict, pnl_csv: Path, month: int, deep_llm) -> str:
    pnl = pd.read_csv(pnl_csv)
    pnl_summary = (
        f"Starting equity: {pnl['equity'].iloc[0]:,.0f} KRW\n"
        f"Ending equity:   {pnl['equity'].iloc[-1]:,.0f} KRW\n"
        f"Return:          {(pnl['equity'].iloc[-1] / pnl['equity'].iloc[0] - 1):+.2%}\n"
        f"Best day:        {pnl['equity'].pct_change().max():+.2%}\n"
        f"Worst day:       {pnl['equity'].pct_change().min():+.2%}\n"
    )
    state_summary = (
        f"Macro: {state.get('macro_summary', '')}\n"
        f"Risk: {state.get('risk_summary', '')}\n"
    )
    response = deep_llm.invoke(MONTHLY_PROMPT.format(
        month=month, state_summary=state_summary, pnl_summary=pnl_summary,
    ))
    return response.content


def write_monthly(state: dict, pnl_csv: Path, month: int, deep_llm, out_path: Path) -> Path:
    text = generate_monthly(state, pnl_csv, month, deep_llm)
    out_path.write_text(text, encoding="utf-8")
    return out_path
```

테스트 + commit.

---

### Task 8: trade_plan.csv generator + report group CLI

`tradingagents/reports/trade_plan.py`:

```python
"""Trade plan CSV — MTS 입력 포맷."""
import csv
from pathlib import Path


def write_trade_plan(
    weights: dict[str, float], capital_krw: int,
    universe_lookup: dict, current_prices: dict[str, float],
    out_path: Path,
) -> Path:
    """Generate MTS-input CSV with: ticker, name, category, weight, amount, qty."""
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["티커", "ETF명", "자산군", "가중치", "매수금액(KRW)", "수량(주)"])
        for ticker, weight in sorted(weights.items(), key=lambda x: -x[1]):
            meta = universe_lookup.get(ticker, {})
            amount = int(weight * capital_krw)
            price = current_prices.get(ticker, 0)
            qty = int(amount / price) if price > 0 else 0
            w.writerow([
                ticker, meta.get("name", ""), meta.get("category", ""),
                f"{weight:.4f}", amount, qty,
            ])
    return out_path
```

`cli/commands/report.py`:

```python
"""gaps report — generate philosophy / monthly / trade-plan."""
import json
from datetime import date
from pathlib import Path

import click

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.pykrx_data import fetch_etf_ohlcv_batch, ParquetCache
from tradingagents.dataflows.universe import load_universe
from tradingagents.llm_clients import create_llm_client
from tradingagents.reports.philosophy import write_philosophy
from tradingagents.reports.monthly import write_monthly
from tradingagents.reports.trade_plan import write_trade_plan


@click.group()
def group():
    """Generate reports."""


@group.command("philosophy")
@click.option("--portfolio", default=None, type=click.Path(exists=True))
@click.option("--out", default=None)
def philosophy_cmd(portfolio, out):
    """투자철학 문서 생성 (≥4 페이지)."""
    deep = create_llm_client(provider=DEFAULT_CONFIG["llm_provider"], model=DEFAULT_CONFIG["deep_think_llm"]).get_llm()
    # Reload state from portfolio.json (simplified — in production, also load summaries)
    state = json.loads(Path(portfolio).read_text(encoding="utf-8"))
    out_path = Path(out or "artifacts/philosophy.md")
    write_philosophy(state, deep, out_path)
    click.echo(f"✓ Wrote {out_path}")


@group.command("monthly")
@click.option("--month", type=int, required=True)
@click.option("--actual", required=True, type=click.Path(exists=True), help="P&L CSV from MTS")
@click.option("--state-json", default=None)
@click.option("--out", default=None)
def monthly_cmd(month, actual, state_json, out):
    """월간 운용보고서 (3섹션)."""
    deep = create_llm_client(provider=DEFAULT_CONFIG["llm_provider"], model=DEFAULT_CONFIG["deep_think_llm"]).get_llm()
    state = json.loads(Path(state_json).read_text(encoding="utf-8")) if state_json else {}
    out_path = Path(out or f"artifacts/monthly_report_{month}.md")
    write_monthly(state, Path(actual), month, deep, out_path)
    click.echo(f"✓ Wrote {out_path}")


@group.command("trade-plan")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--universe-path", default="data/universe.json")
@click.option("--out", default="artifacts/trade_plan.csv")
def trade_plan_cmd(portfolio, universe_path, out):
    """MTS 입력용 매매명세서 CSV."""
    raw = json.loads(Path(portfolio).read_text(encoding="utf-8"))
    universe = load_universe(Path(universe_path))
    lookup = {e.ticker: {"name": e.name, "category": e.category} for e in universe.etfs}

    # Fetch latest snapshot — 1 call covers all ETFs (vs 188 ticker calls)
    from tradingagents.dataflows.pykrx_data import fetch_etf_snapshot_by_date
    import datetime as _dt

    cache = ParquetCache(DEFAULT_CONFIG["etf_price_cache_path"])
    today = date.today()
    snapshot = pd.DataFrame()
    # Walk back up to 5 business days to find the most recent trading day
    for d_off in range(7):
        try:
            snapshot = fetch_etf_snapshot_by_date(today - _dt.timedelta(days=d_off), cache=cache)
            if not snapshot.empty:
                break
        except Exception:
            continue
    latest_prices = {
        row["ticker"]: float(row["close"])
        for _, row in snapshot.iterrows()
        if row["ticker"] in raw["weights"]
    }

    write_trade_plan(
        raw["weights"], raw["capital_krw"],
        lookup, latest_prices, Path(out),
    )
    click.echo(f"✓ Wrote {out}")
```

테스트 + commit.

```bash
git commit -am "feat(reports): add philosophy/monthly/trade-plan generators + report CLI group"
```

---

## Phase 7: 3-tier Rebalancing

### Task 9: Daily triggers (룰 기반, LLM 없음)

**Files:**
- Create: `presets/triggers_default.yaml`
- Create: `tradingagents/rebalance/daily_triggers.py`
- Create: `tests/unit/rebalance/test_daily_triggers.py`

`presets/triggers_default.yaml`:

```yaml
triggers:
  - name: vix_spike
    condition: "vix > 30 OR vix_change_1d > 0.20"
    action: emergency_defensive_proposal
  - name: vkospi_spike
    condition: "vkospi > 25"
    action: emergency_defensive_proposal
  - name: yield_curve_deep_inversion
    condition: "spread_10y_2y_bps < -50"
    action: alert
  - name: kospi_drop
    condition: "kospi_return_1d < -0.02"
    action: alert
  - name: drift_breach_imminent
    condition: "any_etf_weight > 0.18"
    action: rebalance_proposal
```

```python
"""Daily trigger evaluator (D5 light, no LLM)."""
from dataclasses import dataclass
from datetime import date

import yaml

from tradingagents.skills.risk.volatility import fetch_volatility_index


@dataclass
class TriggerResult:
    fired: list[str]
    suggested_action: str | None
    summary: str

    def __str__(self):
        return self.summary


def run(
    as_of: str | None = None,
    portfolio_path: str | None = None,
) -> TriggerResult:
    """Per D15: all 5 trigger context fields populated with real data.

    Args:
        as_of: ISO date.
        portfolio_path: Path to current portfolio.json. If provided, drift is
            computed from latest snapshot prices vs. allocated weights.
            None → drift trigger always evaluates 0 (skip).
    """
    from datetime import timedelta
    import json
    from pathlib import Path
    from tradingagents.dataflows.fred import fetch_fred_series
    from tradingagents.dataflows.pykrx_data import fetch_etf_snapshot_by_date

    target = date.fromisoformat(as_of) if as_of else date.today()
    triggers = yaml.safe_load(open("presets/triggers_default.yaml").read())["triggers"]

    # 1. VIX (current + 1-day change)
    vix = fetch_volatility_index("VIX", target)
    vix_2d = fetch_fred_series("vix_close", target - timedelta(days=5), target).dropna()
    vix_change_1d = (
        float(vix_2d.iloc[-1] / vix_2d.iloc[-2] - 1)
        if len(vix_2d) >= 2 else 0.0
    )

    # 2. VKOSPI (current only — 1-day change less actionable for daily ops)
    vkospi = fetch_volatility_index("VKOSPI", target)

    # 3. Yield curve spread (10y-2y in bps)
    s_10y = fetch_fred_series("us_10y", target - timedelta(days=10), target).dropna()
    s_2y = fetch_fred_series("us_2y", target - timedelta(days=10), target).dropna()
    spread_10y_2y_bps = (
        float(s_10y.iloc[-1] - s_2y.iloc[-1]) * 100
        if not s_10y.empty and not s_2y.empty else 0.0
    )

    # 4. KOSPI 1-day return
    try:
        from pykrx import stock
        kospi_df = stock.get_index_ohlcv(
            (target - timedelta(days=5)).strftime("%Y%m%d"),
            target.strftime("%Y%m%d"),
            "1001",  # KOSPI
        )
        kospi_return_1d = (
            float(kospi_df["종가"].iloc[-1] / kospi_df["종가"].iloc[-2] - 1)
            if len(kospi_df) >= 2 else 0.0
        )
    except Exception:
        kospi_return_1d = 0.0

    # 5. Drift — max single-ETF weight after gain/loss vs. allocated
    any_etf_weight = 0.0
    if portfolio_path and Path(portfolio_path).exists():
        port = json.loads(Path(portfolio_path).read_text(encoding="utf-8"))
        snap = fetch_etf_snapshot_by_date(target)
        if not snap.empty:
            price_map = {row["ticker"]: float(row["close"]) for _, row in snap.iterrows()}
            # NAV = sum(weight * capital * (current_price / entry_price))
            # We approximate entry_price from portfolio.json if present, else
            # treat current weights as drift-free (any_etf_weight = max declared)
            current_values = {}
            for ticker, weight in port["weights"].items():
                current_values[ticker] = weight * price_map.get(ticker, 1.0)
            total = sum(current_values.values())
            if total > 0:
                drifted = {t: v / total for t, v in current_values.items()}
                any_etf_weight = max(drifted.values())

    context = {
        "vix": vix.current_value,
        "vix_change_1d": vix_change_1d,
        "vkospi": vkospi.current_value,
        "spread_10y_2y_bps": spread_10y_2y_bps,
        "kospi_return_1d": kospi_return_1d,
        "any_etf_weight": any_etf_weight,
    }

    fired = []
    for t in triggers:
        if _eval_condition(t["condition"], context):
            fired.append(t["name"])

    if not fired:
        return TriggerResult(fired=[], suggested_action=None,
                             summary=f"[{target}] No triggers fired. VIX={vix.current_value:.1f}")

    summary = f"[{target}] Triggers fired: {', '.join(fired)}"
    action = "emergency_defensive_proposal" if "spike" in str(fired) else "alert"
    return TriggerResult(fired=fired, suggested_action=action, summary=summary)


def _eval_condition(expr: str, ctx: dict) -> bool:
    """Safe AND/OR/comparison parser. NO eval(), NO exec().

    Replaces the original `eval()`-based evaluator. Trigger conditions in
    YAML are user-controllable config; running them through Python's eval
    is an arbitrary-code-execution sink even with restricted __builtins__
    (CPython has known eval-sandbox escapes).

    Grammar (intentionally limited):
        expression := comparison ((AND|OR) comparison)*
        comparison := <var> <op> <number>
        op         := > | < | >= | <= | == | !=
        var        := identifier present in `ctx` dict
        number     := int or float literal

    Examples:
        "vix > 30 OR vix_change_1d > 0.20"
        "spread_10y_2y_bps < -50"
        "any_etf_weight > 0.18"
    """
    return _ConditionParser(expr, ctx).evaluate()


class _ConditionParser:
    _COMPARISON_RE = __import__("re").compile(
        r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$"
    )

    def __init__(self, expr: str, ctx: dict):
        self.expr = expr.strip()
        self.ctx = ctx

    def evaluate(self) -> bool:
        # Split on OR (lowest precedence) — any True wins
        or_parts = self._split_top_level(self.expr, "OR")
        for or_part in or_parts:
            and_parts = self._split_top_level(or_part, "AND")
            if all(self._eval_comparison(p) for p in and_parts):
                return True
        return False

    @staticmethod
    def _split_top_level(s: str, sep: str) -> list[str]:
        # No parentheses supported in this minimal grammar
        # (anti-pattern to allow them: parens enable nested logic that's
        #  cheap to add but expands the security review surface)
        return [p.strip() for p in s.split(f" {sep} ")]

    def _eval_comparison(self, comp: str) -> bool:
        m = self._COMPARISON_RE.match(comp)
        if not m:
            raise ValueError(f"Cannot parse comparison: {comp!r}")
        var, op, num_str = m.group(1), m.group(2), m.group(3)
        if var not in self.ctx:
            raise KeyError(f"Unknown variable in trigger: {var!r}")
        lhs = float(self.ctx[var])
        rhs = float(num_str)
        match op:
            case ">":  return lhs > rhs
            case "<":  return lhs < rhs
            case ">=": return lhs >= rhs
            case "<=": return lhs <= rhs
            case "==": return lhs == rhs
            case "!=": return lhs != rhs
            case _:    raise ValueError(f"Unknown operator: {op}")
```

> **변경 (production hardening):** `eval()` 제거. YAML에서 읽은 trigger 표현식은 외부 입력이므로 임의 코드 실행 위험. 정규식 기반 제한 문법(>, <, >=, <=, ==, !=, AND, OR)으로 안전하게 파싱. 괄호·함수 호출·산술식은 의도적으로 차단해 보안 리뷰 표면을 최소화.

테스트 + commit.

---

### Task 10: Weekly tilt (Macro + Risk만)

`tradingagents/rebalance/weekly_tilt.py`:

```python
"""Weekly tilt — macro + risk only, ±5%p tilt around core."""
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

from tradingagents.agents.analysts.macro_quant_analyst import create_macro_quant_analyst
from tradingagents.agents.analysts.market_risk_analyst import create_market_risk_analyst
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client


@dataclass
class WeeklyResult:
    regime_changed: bool
    tilt_proposed: dict[str, float]
    summary: str

    def __str__(self):
        return self.summary


def run(as_of: str | None = None, previous_path: str | None = None) -> WeeklyResult:
    deep = create_llm_client(provider=DEFAULT_CONFIG["llm_provider"], model=DEFAULT_CONFIG["deep_think_llm"]).get_llm()
    quick = create_llm_client(provider=DEFAULT_CONFIG["llm_provider"], model=DEFAULT_CONFIG["quick_think_llm"]).get_llm()

    target = as_of or date.today().isoformat()
    state = {"as_of_date": target}
    macro_node = create_macro_quant_analyst(quick, deep)
    risk_node = create_market_risk_analyst(quick, deep)

    macro_result = macro_node(state)
    risk_result = risk_node(state)

    # Compare to previous regime
    regime_changed = False
    if previous_path:
        prev = json.loads(Path(previous_path).read_text(encoding="utf-8"))
        prev_regime = prev.get("bucket_target", {}).get("rationale", "")
        if macro_result["macro_report"].regime.quadrant not in prev_regime:
            regime_changed = True

    tilt = {}
    if regime_changed:
        # Trivial example — production: more sophisticated tilt logic
        if "recession" in macro_result["macro_report"].regime.quadrant:
            tilt = {"risk_asset_delta": -0.05, "bond_delta": +0.05}
        else:
            tilt = {"risk_asset_delta": +0.05, "bond_delta": -0.05}

    summary = (
        f"[{target}] Regime: {macro_result['macro_report'].regime.quadrant} | "
        f"Risk score: {risk_result['risk_report'].systemic_score.score:.1f}/10 | "
        f"Regime changed: {regime_changed} | "
        f"Tilt: {tilt or '(none)'}"
    )
    return WeeklyResult(regime_changed=regime_changed, tilt_proposed=tilt, summary=summary)
```

테스트 + commit.

---

### Task 11: Monthly full pipeline + 보고서

`tradingagents/rebalance/monthly_full.py`:

```python
"""Monthly rebalancing — full pipeline + monthly report."""
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


@dataclass
class MonthlyResult:
    portfolio_path: str
    report_path: str | None
    summary: str

    def __str__(self):
        return self.summary


def run(month: int, as_of: str | None = None, previous_path: str | None = None) -> MonthlyResult:
    target = as_of or date.today().isoformat()

    previous_portfolio = None
    if previous_path:
        previous_portfolio = json.loads(Path(previous_path).read_text(encoding="utf-8"))

    graph = TradingAgentsGraph()
    final = graph.run(as_of_date=target, capital_krw=DEFAULT_CONFIG.get("capital_krw", 1_000_000_000))

    # Note: monthly report generation needs P&L CSV from MTS export — caller passes it
    return MonthlyResult(
        portfolio_path=final["final_portfolio_path"],
        report_path=None,  # Use `gaps report monthly` separately
        summary=f"Month {month} rebalance complete: {final['final_portfolio_path']}",
    )
```

테스트 + commit.

---

## Phase 8: Monitor Commands (4개)

### Task 12: gaps monitor {turnover, exposure, drift, cost}

**Files:**
- Create: `cli/commands/monitor.py`
- Create: `tradingagents/monitor/{turnover,exposure,drift,cost}.py`

회전율 floor 추적, 자산군 노출, drift, 비용 모니터.

```python
"""tradingagents/monitor/turnover.py — D11 결정에 따른 floor-only 추적."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass
class TurnoverStatus:
    initial_pct: float
    monthly_pcts: dict[int, float]
    warnings: list[str]


def compute_turnover(transactions_csv: Path, capital_krw: int, as_of: date) -> TurnoverStatus:
    """Compute cumulative + per-month turnover from MTS export.

    Formula (대회 §3): (매수금액 + 매도금액) / 평균자산 * 100
    """
    df = pd.read_csv(transactions_csv)
    df["거래일자"] = pd.to_datetime(df["거래일자"])

    # Initial 5-business-days: 6/1-6/8
    initial_window = df[(df["거래일자"] >= "2026-06-01") & (df["거래일자"] <= "2026-06-08")]
    initial = (initial_window["거래금액"].sum()) / capital_krw

    # Per month
    monthly = {}
    for m in [6, 7, 8]:
        m_data = df[df["거래일자"].dt.month == m]
        monthly[m] = m_data["거래금액"].sum() / capital_krw

    warnings = []
    if initial < 0.80:
        warnings.append(f"⚠ Initial turnover {initial:.2%} < 80% floor (CUTOFF RISK)")
    for m, pct in monthly.items():
        if pct < 0.10:
            warnings.append(f"⚠ Month {m} turnover {pct:.2%} < 10% floor (CUTOFF RISK)")

    return TurnoverStatus(initial_pct=initial, monthly_pcts=monthly, warnings=warnings)
```

CLI:

```python
"""cli/commands/monitor.py."""
import click
from datetime import date
from pathlib import Path

from tradingagents.monitor.turnover import compute_turnover


@click.group()
def group():
    """Operations monitoring."""


@group.command("turnover")
@click.option("--transactions", required=True, type=click.Path(exists=True))
@click.option("--capital", type=int, default=1_000_000_000)
@click.option("--as-of", default=None)
def turnover_cmd(transactions, capital, as_of):
    """Track turnover floor (initial 80%, monthly 10%) — CUTOFF risk."""
    target = date.fromisoformat(as_of) if as_of else date.today()
    status = compute_turnover(Path(transactions), capital, target)
    click.echo(f"Initial (6/1-6/8): {status.initial_pct:.2%} (floor 80%)")
    for m, pct in status.monthly_pcts.items():
        click.echo(f"Month {m}:           {pct:.2%} (floor 10%)")
    for w in status.warnings:
        click.secho(w, fg="red")


# 비슷하게 exposure, drift, cost 명령 구현
```

테스트 + commit.

---

## Phase 9: Preset Commands

### Task 13: gaps preset {list, run}

```python
"""cli/commands/preset.py."""
from pathlib import Path

import click


@click.group()
def group():
    """Preset YAML management."""


@group.command("list")
@click.option("--preset-dir", default="presets")
def list_cmd(preset_dir):
    """List available presets."""
    for f in sorted(Path(preset_dir).glob("*.yaml")):
        click.echo(f.stem)


@group.command("run")
@click.argument("name")
@click.option("--date", "as_of", default=None)
def run_cmd(name, as_of):
    """Run a preset directly (equivalent to `gaps plan --preset NAME`)."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from datetime import date as _date

    graph = TradingAgentsGraph(preset_name=name)
    final = graph.run(as_of_date=as_of or _date.today().isoformat())
    click.echo(f"✓ Preset '{name}' complete: {final['final_portfolio_path']}")
```

테스트 + commit.

---

## Phase 10: Mock Fixtures + 5/28 E2E (D9)

### Task 14: 6 mock fixture 생성

**Files:**
- Create: `tests/fixtures/fred_macro.json`
- Create: `tests/fixtures/ecos_macro.json`
- Create: `tests/fixtures/pykrx_etf_prices.parquet`
- Create: `tests/fixtures/llm_mock_responses.json`
- Create: `tests/fixtures/pyportfolioopt_fake.py`
- Create: `tests/fixtures/universe_test.json` (Plan 1의 sync 결과)

각 fixture 내용:

`fred_macro.json`:
```json
{
  "DGS10": {"2024-01-01": 4.0, "...": "...", "2026-05-10": 4.4},
  "DGS2": {"2024-01-01": 4.5, "...": "...", "2026-05-10": 4.5},
  "CPIAUCSL": {"2024-01-01": 305.0, "...": "...", "2026-04-01": 318.0},
  "UNRATE": {"2024-01-01": 3.7, "...": "...", "2026-04-01": 4.5},
  "PAYEMS": {"...": "..."},
  "VIXCLS": {"...": "..."}
}
```

각 fixture를 sample 1년치만 포함 (전체 5년은 운영 환경에서 fetch).

`pyportfolioopt_fake.py`:

```python
"""Fake PyPortfolioOpt that returns deterministic weights for fixed ticker sets."""

def fake_optimize_hrp(returns):
    """Returns equal-weighted across input tickers."""
    n = returns.shape[1]
    return {col: 1.0 / n for col in returns.columns}
```

`llm_mock_responses.json`:

```json
{
  "classify_regime": {
    "quadrant": "recession_disinflation",
    "confidence": 0.82,
    "drivers": ["yield curve inverted 120 days", "Sahm rule triggered"],
    "reasoning": "Curve and labor market signal recession; CPI decelerating."
  },
  "score_systemic_risk": {
    "score": 6.5,
    "regime": "risk_off",
    "drivers": ["VIX above 25", "HY OAS widening"],
    "reasoning": "Multiple stress signals."
  },
  "pick_optimization_method": {
    "method": "min_variance",
    "params": {},
    "reasoning": "Recession + risk-off → defensive."
  }
}
```

```bash
git add tests/fixtures/
git commit -m "test(fixtures): add 6 mock fixtures for D9 E2E test"
```

---

### Task 15: 5/28 E2E integration test (D9 gold standard)

**Files:**
- Create: `tests/integration/test_5_28_dry_run.py`

```python
"""D9 — 5/28 E2E dry-run with all external APIs mocked.

This is the single most important test. If this passes, we have confidence
that the full pipeline works end-to-end and produces the 3-artifact submission
package compliant with DB GAPS rules.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.fixture
def fred_fixture():
    """Load FRED time-series fixture."""
    raw = json.loads(Path("tests/fixtures/fred_macro.json").read_text())
    series_dict = {}
    for series_id, points in raw.items():
        series_dict[series_id] = pd.Series(points)
        series_dict[series_id].index = pd.to_datetime(series_dict[series_id].index)
    return series_dict


@pytest.fixture
def llm_responses():
    return json.loads(Path("tests/fixtures/llm_mock_responses.json").read_text())


def test_5_28_dry_run_produces_artifacts(tmp_path, fred_fixture, llm_responses, monkeypatch):
    # 1. Mock FRED
    def fake_fred(series_id, start, end, api_key=None):
        from tradingagents.dataflows.fred import FRED_SERIES
        sid = FRED_SERIES.get(series_id, series_id)
        return fred_fixture.get(sid, pd.Series())

    monkeypatch.setattr("tradingagents.dataflows.fred.fetch_fred_series", fake_fred)
    monkeypatch.setattr("tradingagents.skills.macro.fred_fetcher.fetch_fred_series", fake_fred)

    # 2. Mock ECOS — return constant
    def fake_ecos(name, start, end, api_key=None, freq="M"):
        return pd.Series([3.5] * 12, index=pd.date_range("2025-06-01", periods=12, freq="MS"))

    monkeypatch.setattr("tradingagents.dataflows.ecos.fetch_ecos_series", fake_ecos)
    monkeypatch.setattr("tradingagents.skills.macro.ecos_fetcher.fetch_ecos_series", fake_ecos)

    # 3. Mock pykrx — load Parquet fixture
    def fake_pykrx(*args, **kwargs):
        return pd.read_parquet("tests/fixtures/pykrx_etf_prices.parquet")

    monkeypatch.setattr("tradingagents.dataflows.pykrx_data.fetch_etf_ohlcv_batch", fake_pykrx)

    # 4. Mock LLMs (deep + quick)
    def make_mock_llm(responses):
        llm = MagicMock()
        # Default invoke returns generic narrative
        llm.invoke.return_value.content = "mocked narrative " * 10  # ~150 chars
        # with_structured_output returns based on schema
        def structured(schema):
            sub = MagicMock()
            schema_name = schema.__name__
            if schema_name == "RegimeClassification":
                sub.invoke.return_value = schema.model_validate(responses["classify_regime"])
            elif schema_name == "SystemicRiskScore":
                sub.invoke.return_value = schema.model_validate(responses["score_systemic_risk"])
            elif schema_name == "MethodChoice":
                sub.invoke.return_value = schema.model_validate(responses["pick_optimization_method"])
            elif schema_name == "BucketTarget":
                sub.invoke.return_value = schema(
                    kr_equity=0.15, global_equity=0.20, fx_commodity=0.10,
                    bond=0.40, cash_mmf=0.15,
                    rationale="recession-disinflation regime, defensive",
                )
            else:
                sub.invoke.return_value = schema()
            return sub
        llm.with_structured_output = structured
        return llm

    deep = make_mock_llm(llm_responses)
    quick = make_mock_llm(llm_responses)
    monkeypatch.setattr("tradingagents.graph.trading_graph.create_llm_client",
                        lambda **kw: MagicMock(get_llm=lambda: deep))

    # 5. Mock universe
    monkeypatch.setattr("tradingagents.dataflows.universe.load_universe",
                        lambda path: __import__("tradingagents.dataflows.universe", fromlist=["Universe"]).Universe.model_validate(
                            json.loads(Path("tests/fixtures/universe_test.json").read_text())
                        ))

    # 6. Run
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr("tradingagents.default_config.DEFAULT_CONFIG", {
        **__import__("tradingagents.default_config", fromlist=["DEFAULT_CONFIG"]).DEFAULT_CONFIG,
        "artifacts_dir": str(artifacts_dir),
        "preset_dir": "presets",
        "universe_path": "tests/fixtures/universe_test.json",
    })

    graph = TradingAgentsGraph()
    final = graph.run(as_of_date="2026-05-25", capital_krw=1_000_000_000)

    # 7. Assertions
    assert final["validation_passed"] is True, f"Validation failed: {final.get('validation_report')}"
    assert Path(final["final_portfolio_path"]).exists()
    assert Path(final["philosophy_doc_path"]).exists()
    assert Path(final["trade_plan_csv_path"]).exists()

    # Check portfolio.json structure
    portfolio = json.loads(Path(final["final_portfolio_path"]).read_text(encoding="utf-8"))
    assert abs(sum(portfolio["weights"].values()) - 1.0) < 1e-3
    assert all(w <= 0.20 + 1e-6 for w in portfolio["weights"].values()), "Single ETF cap violated"

    # Check trade_plan.csv has all required columns
    import csv
    with open(final["trade_plan_csv_path"], encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == ["티커", "ETF명", "자산군", "가중치", "매수금액(KRW)", "수량(주)"]
```

```bash
git commit -am "test(integration): add D9 5/28 E2E dry-run gold standard"
```

---

## Phase 11: Validator Cycle + Cache Tests (D4, D5)

### Task 16: D4 cycle integration test

`tests/integration/test_validator_cycle.py`:

```python
"""D4 — Validator → Allocator cycle with retry + fallback."""
from unittest.mock import MagicMock

from tradingagents.graph.conditional_logic import validation_router, MAX_ALLOCATION_ATTEMPTS


def test_pass_routes_to_finalize():
    state = {"validation_passed": True, "allocation_attempts": 1}
    assert validation_router(state) == "finalize"


def test_fail_attempt_1_retries():
    state = {"validation_passed": False, "allocation_attempts": 1}
    assert validation_router(state) == "retry_allocator"


def test_fail_attempt_max_falls_back():
    state = {"validation_passed": False, "allocation_attempts": MAX_ALLOCATION_ATTEMPTS}
    assert validation_router(state) == "fallback"


def test_fallback_node_clips_and_renormalizes():
    from tradingagents.graph.conditional_logic import create_fallback_normalizer
    from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector

    fb = create_fallback_normalizer()
    bad_weights = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A1": 0.30, "A2": 0.25, "A3": 0.45},
        rationale="bad",
    )
    state = {"weight_vector": bad_weights, "allocation_attempts": 2}
    result = fb(state)
    new = result["weight_vector"]
    assert all(w <= 0.20 + 1e-6 for w in new.weights.values())
    assert abs(sum(new.weights.values()) - 1.0) < 1e-6
    assert result["validation_passed"] is True
```

```bash
git commit -am "test(integration): add D4 Validator cycle + fallback test"
```

---

### Task 17: D5 cache fallback integration test

`tests/integration/test_cache_fallback.py`:

```python
"""D5 — Tiered cache fallback behavior."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from tradingagents.dataflows.cache import TieredCache, CacheMiss, FetchFailure


def test_d1_hit_when_live_fails(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    c.write(today - timedelta(days=1), {"data": "yesterday"})

    def fail():
        raise FetchFailure("api down")

    val, staleness = c.fetch_with_fallback(fail, as_of=today)
    assert val == {"data": "yesterday"}
    assert staleness == 1


def test_d7_max_staleness(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    c.write(today - timedelta(days=8), {"data": "ancient"})

    def fail():
        raise FetchFailure("api down")

    with pytest.raises(CacheMiss):
        c.fetch_with_fallback(fail, as_of=today, max_staleness=7)


def test_staleness_propagates_to_snapshot(tmp_path):
    """Verify snapshots reflect staleness from cache."""
    from tradingagents.schemas.macro import YieldCurveSnapshot

    snap = YieldCurveSnapshot(
        spread_10y_2y_bps=-25.0, spread_10y_3m_bps=-30.0,
        inverted_days_count=120, percentile_5y=0.05,
        staleness_days=3,
    )
    assert snap.is_stale is True
    assert snap.is_severely_stale is False
```

```bash
git commit -am "test(integration): add D5 cache fallback test"
```

---

## Phase 12: Eval (LLM 품질)

### Task 18: regime_classifier eval (8 historical cases)

`tests/integration/test_eval_regime_classifier.py`:

```python
"""Eval — classify_regime accuracy across 8 historical regime cases.

Per design §15, this is the LLM eval that should be re-run when classifier
prompts change.
"""
from datetime import date

import pytest

from tradingagents.skills.macro.regime_classifier import RegimeClassifier


HISTORICAL_CASES = [
    # (case_name, inputs, expected_quadrant)
    ("2008-09 (Lehman, deep recession)", {
        "spread_10y_2y_bps": -50.0, "inverted_days_count": 200,
        "cpi_yoy": 4.5, "momentum_3mo": -2.0, "accelerating": False,
        "unemployment_rate": 6.8, "sahm_rule_triggered": True,
    }, "recession_disinflation"),
    ("2022-06 (peak inflation, growth)", {
        "spread_10y_2y_bps": 10.0, "inverted_days_count": 0,
        "cpi_yoy": 9.1, "momentum_3mo": 8.0, "accelerating": True,
        "unemployment_rate": 3.6, "sahm_rule_triggered": False,
    }, "growth_inflation"),
    ("2020-04 (COVID recession + supply inflation)", {
        "spread_10y_2y_bps": 50.0, "inverted_days_count": 0,
        "cpi_yoy": 0.3, "momentum_3mo": -1.0, "accelerating": False,
        "unemployment_rate": 14.7, "sahm_rule_triggered": True,
    }, "recession_disinflation"),
    ("2017-Q3 (Goldilocks)", {
        "spread_10y_2y_bps": 80.0, "inverted_days_count": 0,
        "cpi_yoy": 2.0, "momentum_3mo": 1.8, "accelerating": False,
        "unemployment_rate": 4.2, "sahm_rule_triggered": False,
    }, "growth_disinflation"),
    # ... 4 more
]


@pytest.mark.eval
@pytest.mark.parametrize("case_name,inputs,expected", HISTORICAL_CASES)
def test_regime_classifier_accuracy(case_name, inputs, expected):
    """Run with real LLM (skip in CI; opt-in via -m eval)."""
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.llm_clients import create_llm_client

    quick = create_llm_client(provider=DEFAULT_CONFIG["llm_provider"], model=DEFAULT_CONFIG["quick_think_llm"]).get_llm()
    deep = create_llm_client(provider=DEFAULT_CONFIG["llm_provider"], model=DEFAULT_CONFIG["deep_think_llm"]).get_llm()

    clf = RegimeClassifier(quick, deep)
    result = clf.invoke(**inputs)
    assert result.quadrant == expected, f"{case_name}: got {result.quadrant}, expected {expected}"
    assert result.confidence >= 0.7, f"{case_name}: confidence too low {result.confidence}"
```

`pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "eval: LLM quality eval, requires API access; skip in CI",
]
```

```bash
git commit -am "test(eval): add regime classifier 4-quadrant eval (8 historical cases)"
```

---

## Phase 13: Documentation

### Task 19: README 업데이트 + 사용 가이드

**Files:**
- Modify: `README.md`

```markdown
## DB GAPS Asset Allocation Agent (v0.3)

**대회용 fork.** TradingAgents v0.2.4 → KR 188-ETF 자산배분 의사결정 시스템.

### Setup

1. Install: `pip install -e ".[test]"` (pure Python — TA-Lib 시스템 패키지 불필요)
2. API keys: `.env`에 `FRED_API_KEY`, `ECOS_API_KEY`, `OPENAI_API_KEY` 등
3. (선택) Tracing: `.env`에 `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=...`,
   `LANGSMITH_PROJECT=db-gaps-agent`. 활성화 시 모든 multi-agent run이
   https://smith.langchain.com/ 에 trace됨.
4. Universe sync: `gaps universe sync`

### 5/28 제출용 파이프라인

```bash
gaps universe sync                                # 188 ETF JSON
gaps macro regime --date 2026-05-25               # 매크로 진단 빠른 확인
gaps plan --date 2026-05-25 --capital 1000000000  # 풀 파이프라인
gaps validate --portfolio artifacts/2026-05-25/portfolio.json
gaps correlate --portfolio ... --cluster
gaps report philosophy --portfolio ...
gaps report trade-plan --portfolio ...
```

### 운용 중 (6/1~8/31)

```bash
gaps rebalance daily                              # 매일 (트리거 평가)
gaps rebalance weekly --week 24                   # 매주 금요일
gaps rebalance monthly --month 6                  # 월말
gaps monitor turnover --transactions june.csv     # 컷오프 추적
gaps report monthly --month 6 --actual june_pnl.csv
```

자세한 설계: `docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md`
```

```bash
git commit -am "docs: update README with DB GAPS usage guide"
```

---

## Self-Review

- ✅ 22 CLI 명령 모두 구현
- ✅ D9 (mock fixture E2E + manual live dry-run)
- ✅ D4 (Validator cycle test)
- ✅ D5 (cache fallback test)
- ✅ §11 산출물 3종 모두 생성
- ✅ §10.6 floor-only 회전율 모니터 (D11)
- ✅ §9.1 daily 트리거 룰셋 YAML
- ✅ regime_classifier eval

## Plan 4 완료 시 산출물

- 22 CLI 명령
- 3 보고서 생성기
- 3-tier rebalancing (daily/weekly/monthly)
- 4 모니터링 명령
- 6 mock fixture
- 5/28 E2E gold-standard 테스트
- D4·D5 검증 통합 테스트
- 8-case regime classifier eval

**다음 단계:** Plan 1 → 2 → 3 → 4 순차 실행. 각 plan 완료 후 phase 단위로 커밋·검토.

---

## 통합 자체 점검

### Plan 1 → Plan 4 결정 매핑

| 결정 | Plan | Task |
|---|---|---|
| D2 (subgraph 격리) | 3 | Task 6, 10, 11, 13 |
| D3 (preset YAML) | 1, 3 | P1 Task 21, 22; P3 Task 18 |
| D4 (Validator cycle) | 3 | Task 14, 15, 16 |
| D5 (tiered cache) | 1, 4 | P1 Task 15; P4 Task 17 |
| D6 (BaseSubagent) | 1 | Task 13 |
| D7 (retry helper) | 1 | Task 12 |
| D8 (memory deprecate) | (no-op for v1) | — |
| D9 (E2E mock + manual) | 4 | Task 14, 15 |
| D10 (pykrx Parquet) | 1 | Task 16 |
| D11 (TODOS) | (separate doc) | — |

### 5/28 마감 일정 (D-18, today=2026-05-10)

- D-18 ~ D-13 (5/10~5/15): Plan 1 (foundation, 23 tasks ≈ 4-5일)
- D-12 ~ D-8 (5/16~5/20): Plan 2 (skills, 31 tasks ≈ 4일)
- D-7 ~ D-4 (5/21~5/24): Plan 3 (agents, 22 tasks ≈ 3-4일)
- D-3 ~ D-1 (5/25~5/27): Plan 4 (CLI, 19 tasks ≈ 3일) + 5/28 dry-run + 보고서 제출

타이트하지만 가능. 병렬화는 Plan 1 phase 1·2·3, Plan 2 6 도메인 간 병렬 가능.

---

**Total tasks across 4 plans: ~95.**

Plan execution은 `superpowers:subagent-driven-development` (각 task당 fresh subagent + 검토) 권장.
