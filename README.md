<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="./assets/wechat.png" target="_blank"><img alt="WeChat" src="https://img.shields.io/badge/WeChat-TauricResearch-brightgreen?logo=wechat&logoColor=white"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <br>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/Join_GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>

<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# DB GAPS Asset Allocation Agent (v0.3 — fork)

**제12회 DB GAPS 투자대회용 fork.** 원본 TradingAgents v0.2.4(주식 stock-picking) → 한국 ETF 188종목 top-down 자산배분 시스템으로 전환.

> **대회 기간**: 2026-06-01 ~ 2026-08-31 · **포트폴리오 제출 마감**: 2026-05-28 · **초기 자본**: 10억 KRW

## 프로젝트 상태

| Plan | 영역 | 상태 |
|---|---|---|
| 1 | Foundation (schema · dataflows · cache · BaseSubagent) | ✅ |
| 2 | Skills 카탈로그 (16 subagents · 4 optimizers · 4 mandate validators) | ✅ |
| 3 | Agents (4 analysts · debate sub-graphs · allocator · validator · PM) | ✅ |
| 4 | CLI · Reports · 3-tier rebalance · E2E mock test | ✅ |

- **테스트**: 275 passing · 9 deselected (`slow` E2E + `eval`은 opt-in)
- **5/28 ready**: `gaps plan` 실행 시 portfolio.json + philosophy.md + trade_plan.csv 3종 산출

## Setup

```bash
pip install -e ".[test]"            # pure Python (TA-Lib 시스템 패키지 불필요)
cp .env.example .env                # FRED_API_KEY, ECOS_API_KEY, OPENAI_API_KEY 등 입력
gaps universe sync                  # data/universe.json 생성 (188 ETF)
```

(선택) Observability: `.env`에 `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=...`, `LANGSMITH_PROJECT=db-gaps-agent`을 추가하면 모든 multi-agent run이 https://smith.langchain.com/ 에 trace됨.

## 시스템 아키텍처

**Hybrid topology γ** — stage 간 summary handoff + debate cluster 내 shared state. 6 stage 파이프라인:

```
[stage 1] Analysts (병렬 4)
  ├─ macro_quant   ┐
  ├─ market_risk   │
  ├─ technical     ├─→ summaries
  └─ macro_news    ┘
        │
[stage 2] Research debate (sub-graph, D2 격리)
  Bull ⇄ Bear ↔ Research Manager → BucketTarget(5-bucket)
        │
[stage 3] Portfolio Allocator
  method_picker → 4 optimizers + constraint injection
  (단일 ETF ≤ 20%, sector cap, weight bounds)
        │
[stage 4] Risk debate (Aggressive/Conservative/Neutral → Risk Judge)
        │
[stage 5] Mandate Validator (4 룰)
  pass → finalize
  fail (≤2회) → Allocator 재시도
  fail (>2회) → fallback normalizer (clip + renormalize)
        │
[stage 6] Portfolio Manager → 3 산출물
```

핵심 결정사항(D1-D17)은 `docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md` Appendix 참조.

## Skills 카탈로그 (16 subagents · 6 도메인)

| 도메인 | 모듈 |
|---|---|
| `macro` | regime_classifier, yield_curve, inflation, employment, divergence, calendar, fred_fetcher, ecos_fetcher |
| `risk` | systemic_score, volatility, correlation_pca, credit_spread, fear_greed, breadth |
| `technical` | correlation_cluster, momentum_ranker, ta_indicators, trend_state, price_batch |
| `news` | impact_classifier, news_fetcher, ranker, event_calendar |
| `portfolio` | candidate_selector, method_picker, optimizers (HRP/RP/MinVar/BL), returns_matrix |
| `mandate` | universe_check, concentration_check, turnover_check, correlation_check |

모든 LLM 콜은 Pydantic v2 schema-locked structured output. Tenacity 기반 retry + TieredCache(D5, max staleness 7일) fallback.

## Optimizer 4종 (PyPortfolioOpt 기반)

| 방법 | 적용 시 | 비고 |
|---|---|---|
| **HRP** (Hierarchical Risk Parity) | 기본값 (전 regime) | iterative water-filling으로 20% cap 보장 |
| **Risk Parity** | growth_disinflation | 동일 위험 기여도 |
| **Min Variance** | recession 계열 | `add_sector_constraints` + weight bounds |
| **Black-Litterman** | 강한 view 존재 시 | views를 BucketTarget으로 주입 |

⚠️ **Critical fix**: 기존 post-scaling 방식은 20% cap을 사후 위반. 현재 구현은 **constraint injection** (최적화 단계에서 강제) → mandate 자동 통과.

## 5/28 제출용 파이프라인

```bash
gaps universe sync                                # 188 ETF universe.json
gaps macro regime --date 2026-05-25               # 매크로 진단 미리 확인
gaps plan --date 2026-05-25 --capital 1000000000  # 풀 파이프라인 (3 산출물)

# 검증 + 분석
gaps analysis validate --portfolio artifacts/2026-05-25/portfolio.json
gaps analysis correlate --portfolio artifacts/2026-05-25/portfolio.json --cluster
gaps analysis simulate --portfolio artifacts/2026-05-25/portfolio.json --window 3y

# 보고서 (대회 §4 제출 형식)
gaps report philosophy --portfolio artifacts/2026-05-25/portfolio.json   # ≥4000자 한국어
gaps report trade-plan --portfolio artifacts/2026-05-25/portfolio.json   # MTS 입력 CSV
```

## 운용 중 (6/1~8/31) — 3-tier 리밸런싱

```bash
gaps rebalance daily                              # 매일 — 룰 기반 트리거 (LLM 없음)
                                                  # VIX/VKOSPI/yield curve/KOSPI/drift 평가
gaps rebalance weekly --week 24                   # 매주 — macro+risk만, ±5%p tilt
gaps rebalance monthly --month 6                  # 월말 — 풀 파이프라인 + 월간 보고서

# 모니터링
gaps monitor turnover --transactions june.csv     # 회전율 floor (초기 80% / 월 10%)
gaps monitor exposure --portfolio current.json    # 자산군별 비중 + risk/safe split
gaps monitor drift --portfolio current.json --prices-csv mts.csv  # 가격 변동 drift
gaps monitor cost --transactions june.csv         # 수수료 + 슬리피지 (bps)

# 월간 보고서 (대회 §4.2)
gaps report monthly --month 6 --actual june_pnl.csv
```

## CLI 전체 (22개 명령)

| 그룹 | 명령 | 비고 |
|---|---|---|
| `universe` | `sync` · `list` · `info` | xlsx → universe.json (188 ETF) |
| `macro` | `regime` · `risk` · `news` · `technical` | 단독 분석가 디버그 |
| `portfolio` | `plan` · `rebalance {daily,weekly,monthly}` · `optimize` | 메인 진입점 |
| `analysis` | `correlate` · `validate` · `simulate` | 1y/3y/5y 백테스트 포함 |
| `report` | `philosophy` · `monthly` · `trade-plan` | 3 산출물 생성 |
| `monitor` | `turnover` · `exposure` · `drift` · `cost` | 운용 중 추적 |
| `preset` | `list` · `run` | YAML 기반 프리셋 |

## DB GAPS mandate (자동 검증)

자동 검증은 stage 5에서 4-rule check + cycle (D4):

- ✅ **위험자산 ≤ 70%** — 단순 비중 합산 + 상관관계 cluster cap
- ✅ **단일 ETF ≤ 20%** — Allocator 제약 주입 단계에서 보장
- ✅ **회전율 floor** — 초기 5영업일 ≥ 80%, 월간 ≥ 10% (cap 없음, monitor만)
- ✅ **188 ETF 풀 외 매수 금지** — universe_check가 강제

위반 시 ≤ 2회 Allocator 재시도, 이후 fallback normalizer가 clip + renormalize로 강제 통과.

## 개발 / 테스트

```bash
pytest tests/ -m 'not slow and not eval'   # 단위 + 통합 (~3s, 275 passing)
pytest tests/ -m slow                       # 5/28 E2E gold-standard mock test
pytest tests/ -m eval                       # 8-case regime classifier eval (실 LLM 필요)
```

핵심 통합 테스트:
- `tests/integration/test_5_28_dry_run.py` — 풀 파이프라인 mock E2E (D9 gold standard)
- `tests/integration/test_validator_cycle.py` — D4 Validator → Allocator 사이클
- `tests/integration/test_cache_fallback.py` — D5 TieredCache fallback
- `tests/integration/test_eval_regime_classifier.py` — 8 historical regime cases (opt-in)

## 설계 문서

- 디자인 스펙: `docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md` (17 결정 포함)
- 4개 plan: `docs/superpowers/plans/2026-05-10-db-gaps-plan-{1-foundation,2-skills,3-agents,4-cli}.md`
- 사전 요구: `docs/db-gaps-prerequisites.md`
- 테스트 플랜: `docs/db-gaps-test-plan.md`
- 미해결 follow-up: `TODOS.md`
- 대회 규칙: `docs/DB_GAPS_Investment_Tournament_Rules.md`

---

# TradingAgents: Multi-Agents LLM Financial Trading Framework

> 아래는 upstream TradingAgents v0.2.4의 원본 README입니다 (참고용).

## News
- [2026-04] **TradingAgents v0.2.4** released with structured-output agents (Research Manager, Trader, Portfolio Manager), LangGraph checkpoint resume, persistent decision log, DeepSeek/Qwen/GLM/Azure provider support, Docker, and a Windows UTF-8 encoding fix. See [CHANGELOG.md](CHANGELOG.md) for the full list.
- [2026-03] **TradingAgents v0.2.3** released with multi-language support, GPT-5.4 family models, unified model catalog, backtesting date fidelity, and proxy support.
- [2026-03] **TradingAgents v0.2.2** released with GPT-5.4/Gemini 3.1/Claude 4.6 model coverage, five-tier rating scale, OpenAI Responses API, Anthropic effort control, and cross-platform stability.
- [2026-02] **TradingAgents v0.2.0** released with multi-provider LLM support (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x) and improved system architecture.
- [2026-01] **Trading-R1** [Technical Report](https://arxiv.org/abs/2509.11420) released, with [Terminal](https://github.com/TauricResearch/Trading-R1) expected to land soon.

<div align="center">
<a href="https://www.star-history.com/#TauricResearch/TradingAgents&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" />
   <img alt="TradingAgents Star History" src="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" style="width: 80%; height: auto;" />
 </picture>
</a>
</div>

> 🎉 **TradingAgents** officially released! We have received numerous inquiries about the work, and we would like to express our thanks for the enthusiasm in our community.
>
> So we decided to fully open-source the framework. Looking forward to building impactful projects with you!

<div align="center">

🚀 [TradingAgents](#tradingagents-framework) | ⚡ [Installation & CLI](#installation-and-cli) | 🎬 [Demo](https://www.youtube.com/watch?v=90gr5lwjIho) | 📦 [Package Usage](#tradingagents-package) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

## TradingAgents Framework

TradingAgents is a multi-agent trading framework that mirrors the dynamics of real-world trading firms. By deploying specialized LLM-powered agents: from fundamental analysts, sentiment experts, and technical analysts, to trader, risk management team, the platform collaboratively evaluates market conditions and informs trading decisions. Moreover, these agents engage in dynamic discussions to pinpoint the optimal strategy.

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> TradingAgents framework is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, the quality of data, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

Our framework decomposes complex trading tasks into specialized roles. This ensures the system achieves a robust, scalable approach to market analysis and decision-making.

### Analyst Team
- Fundamentals Analyst: Evaluates company financials and performance metrics, identifying intrinsic values and potential red flags.
- Sentiment Analyst: Analyzes social media and public sentiment using sentiment scoring algorithms to gauge short-term market mood.
- News Analyst: Monitors global news and macroeconomic indicators, interpreting the impact of events on market conditions.
- Technical Analyst: Utilizes technical indicators (like MACD and RSI) to detect trading patterns and forecast price movements.

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Researcher Team
- Comprises both bullish and bearish researchers who critically assess the insights provided by the Analyst Team. Through structured debates, they balance potential gains against inherent risks.

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Trader Agent
- Composes reports from the analysts and researchers to make informed trading decisions. It determines the timing and magnitude of trades based on comprehensive market insights.

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Risk Management and Portfolio Manager
- Continuously evaluates portfolio risk by assessing market volatility, liquidity, and other risk factors. The risk management team evaluates and adjusts trading strategies, providing assessment reports to the Portfolio Manager for final decision.
- The Portfolio Manager approves/rejects the transaction proposal. If approved, the order will be sent to the simulated exchange and executed.

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

## Installation and CLI

### Installation

Clone TradingAgents:
```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

Create a virtual environment in any of your favorite environment managers:
```bash
conda create -n tradingagents python=3.13
conda activate tradingagents
```

Install the package and its dependencies:
```bash
pip install .
```

### Docker

Alternatively, run with Docker:
```bash
cp .env.example .env  # add your API keys
docker compose run --rm tradingagents
```

For local models with Ollama:
```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

### Required APIs

TradingAgents supports multiple LLM providers. Set the API key for your chosen provider:

```bash
export OPENAI_API_KEY=...          # OpenAI (GPT)
export GOOGLE_API_KEY=...          # Google (Gemini)
export ANTHROPIC_API_KEY=...       # Anthropic (Claude)
export XAI_API_KEY=...             # xAI (Grok)
export DEEPSEEK_API_KEY=...        # DeepSeek
export DASHSCOPE_API_KEY=...       # Qwen (Alibaba DashScope)
export ZHIPU_API_KEY=...           # GLM (Zhipu)
export OPENROUTER_API_KEY=...      # OpenRouter
export ALPHA_VANTAGE_API_KEY=...   # Alpha Vantage
```

For enterprise providers (e.g. Azure OpenAI, AWS Bedrock), copy `.env.enterprise.example` to `.env.enterprise` and fill in your credentials.

For local models, configure Ollama with `llm_provider: "ollama"` in your config.

Alternatively, copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

### CLI Usage

Launch the interactive CLI:
```bash
tradingagents          # installed command
python -m cli.main     # alternative: run directly from source
```
You will see a screen where you can select your desired tickers, analysis date, LLM provider, research depth, and more.

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

An interface will appear showing results as they load, letting you track the agent's progress as it runs.

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

## TradingAgents Package

### Implementation Details

We built TradingAgents with LangGraph to ensure flexibility and modularity. The framework supports multiple LLM providers: OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen (Alibaba DashScope), GLM (Zhipu), OpenRouter, Ollama for local models, and Azure OpenAI for enterprise.

### Python Usage

To use TradingAgents inside your code, you can import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function will return a decision. You can run `main.py`, here's also a quick example:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# forward propagate
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

You can also adjust the default configuration to set your own choice of LLMs, debate rounds, etc.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"        # openai, google, anthropic, xai, deepseek, qwen, glm, openrouter, ollama, azure
config["deep_think_llm"] = "gpt-5.4"     # Model for complex reasoning
config["quick_think_llm"] = "gpt-5.4-mini" # Model for quick tasks
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

See `tradingagents/default_config.py` for all configuration options.

## Persistence and Recovery

TradingAgents persists two kinds of state across runs.

### Decision log

The decision log is always on. Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents fetches the realised return (raw and alpha vs SPY), generates a one-paragraph reflection, and injects the most recent same-ticker decisions plus recent cross-ticker lessons into the Portfolio Manager prompt, so each analysis carries forward what worked and what didn't.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint`. When enabled, LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step instead of starting over. On a resume run you will see `Resuming from step N for <TICKER> on <date>` in the logs; on a new run you will see `Starting fresh`. Checkpoints are cleared automatically on successful completion.

Per-ticker SQLite databases live at `~/.tradingagents/cache/checkpoints/<TICKER>.db` (override the base with `TRADINGAGENTS_CACHE_DIR`). Use `--clear-checkpoints` to reset all of them before a run.

```bash
tradingagents analyze --checkpoint           # enable for this run
tradingagents analyze --clear-checkpoints    # reset before running
```

```python
config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
```

## Contributing

We welcome contributions from the community! Whether it's fixing a bug, improving documentation, or suggesting a new feature, your input helps make this project better. If you are interested in this line of research, please consider joining our open-source financial AI research community [Tauric Research](https://tauric.ai/).

Past contributions, including code, design feedback, and bug reports, are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

## Citation

Please reference our work if you find *TradingAgents* provides you with some help :)

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```
