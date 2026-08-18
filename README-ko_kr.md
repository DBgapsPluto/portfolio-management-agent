# DB GAPS Asset Allocation Agent

[English](README.md) | **한국어**

**한국 상장 ETF를 위한 멀티에이전트 자산배분 시스템 — regime-조건부 기준 포트폴리오를 Black-Litterman view로 기울이고, 의무사항(mandate) 준수를 매 실행 결정론적으로 강제한다.**

![License](https://img.shields.io/badge/license-Apache--2.0-blue)
![Python](https://img.shields.io/badge/python-3.12%2B-3776AB)
![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-lightgrey)
![Tests](https://img.shields.io/badge/tests-1300%2B_passing_locally-brightgreen)

이 프로젝트는 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 포크에서 출발해, 종목 선정(stock-picking) 프레임워크를 top-down 자산배분 시스템으로 전면 재구축한 것이다.

업스트림 대비 차별점: **한국 상장 ETF 유니버스**와 14-bucket 자산 분류체계, **KRW-numeraire 주간 공분산 모델**, 결정론적 신호-일치도 점수로 중립 포트폴리오와 매크로 regime 베이스라인 사이를 보간하는 **confidence-scaled Black-Litterman prior**, 그리고 **결정론적 컴플라이언스** — 의무사항 cap은 매 실행마다 repair 루프가 강제하고 LLM-free validator가 재검증한다.

![파이프라인: 분석가 4종 → 리서치 디베이트 → Black-Litterman allocator → ETF 선정 → repair → mandate validator → 산출물](assets/architecture.svg)

## Why — 왜 만들었나

제12회 **DB GAPS 투자대회**(2026-06-01 → 2026-08-31)를 위해 만들었다: 국내 상장 ETF 188종만 담을 수 있는 10억 원 모의계좌를 운용하며, **수익률 30% + 투자철학 70%**로 평가받는다 — 계획서 로직이 실제 운용에 일관 적용됐는가, 시장 충격 시 방어 논리, 표면적 분산이 아닌 내부 상관관계 기반 단일 리스크 통제.

이 채점 구조가 아키텍처를 결정했다. 시스템은 **결정론적 의사결정**(regime 분류, 공분산, ETF 선정, cap repair, 의무사항 검증)과 **LLM 판단**(서술, 디베이트, 한도 내 상대 view)을 분리한다. 모든 배분이 재현할 수 있고, 귀속을 추적할 수 있고, 감사할 수 있어야 한다 — 일관된 철학의 궤적이 배분 그 자체만큼 중요하기 때문이다.

두 번째, 더 엄격한 요구: 규칙 위반은 경고 없이 탈락이다. 따라서 시스템은 **매 실행마다** 의무사항을 검증한다:

| 규칙 | 제약 | 강제 주체 |
|---|---|---|
| 위험자산 (국내·해외 주식, FX, 원자재) | ≤ 70% | repair 루프 + validator |
| 단일 ETF | ≤ 20% | 최적화 제약 + repair + validator |
| 세부 카테고리별 상한 (예: 국내주식_섹터 ≤ 15%) | 룰북 표 | repair + validator |
| 고상관 클러스터 비중 | cluster cap | cluster repair + validator |
| 초기 회전율 (개시 후 5영업일) | ≥ 80% | 모니터 + 알림 |
| 월간 회전율 | 매월 ≥ 10% | MTD 추적 + 알림 |

규정→코드 대응표 전체는 [`docs/competition-rules-summary.md`](docs/competition-rules-summary.md) 참조.

## Quickstart — 빠른 시작

```bash
# 1. 설치 (pure Python — TA-Lib 시스템 패키지 불필요)
pip install -e ".[test]"

# 2. 키 설정: FRED_API_KEY, ECOS_API_KEY, LLM provider 키 1개 (기본: OpenAI)
cp .env.example .env    # 편집

# 3. 전체 파이프라인 실행 → artifacts/{date}/ 에 3종 산출
gaps plan --date 2026-06-05 --capital 1000000000
```

ETF 유니버스는 [`data/universe.json`](data/universe.json)으로 동봉되어 별도 다운로드가 필요 없다. 자주 쓰는 명령:

| 명령 | 용도 |
|---|---|
| `gaps plan` | 전체 파이프라인: 분석 → 배분 → 검증 → 산출물 |
| `gaps rebalance {daily,weekly,monthly}` | 현재 보유 기준 tier별 리밸런싱 |
| `gaps validate` | 기존 포트폴리오 의무사항 검증 |
| `gaps monitor` | 운영 모니터링 (회전율 / 노출 / drift) |
| `gaps macro` | 단일 분석가 디버그 (regime / risk / news / technical) |

## Features — 주요 기능

- **6-stage LangGraph 파이프라인** — 병렬 분석가 4종 → 리서치 디베이트 → allocator → validator → 산출물. stage 간에는 압축 요약(summary handoff)만 전달하고, 모든 LLM 출력은 Pydantic 스키마에 잠긴다(schema-locked).
- **Regime-조건부 기준 포트폴리오 + BL view 엔진** — prior는 수작업 설정된 regime-조건부 기준 포트폴리오다 (의도적으로 canonical equilibrium Black-Litterman이 *아님*; [LIMITATIONS.md](LIMITATIONS.md) 참조). LLM 상대-랭킹 view와 결정론적 FX/credit rule view가 confidence-가중 결합으로 prior를 기울인다.
- **Confidence-scaled prior** — 결정론적 신호-일치도 점수(매크로 스냅샷 투표로 계산; LLM의 자가보고 confidence가 아님)가 prior를 중립 포트폴리오 ↔ regime 베이스라인 사이에서 보간한다. regime을 잘못 분류하더라도 성능이 급격히 무너지지 않는다.
- **KRW-numeraire 주간 공분산** — bucket 프록시를 KRW 기준으로 재표현(unhedged bucket은 USDKRW 합성), 104주 창의 주간 수익률, Ledoit–Wolf shrinkage.
- **한도 내 LLM 영향** — view는 prior 대비 capped active-share 예산을 통해서만 반영된다. LLM은 구조적 배분을 기울일 수는 있어도 뒤집을 수는 없다.
- **재현 가능한 ETF 선정** — 자격 스크린(카테고리, AUM, 상장일) + 이질(heterogeneous) bucket은 LLM 테마 view와 위험조정 모멘텀으로 선정. 같은 입력이면 같은 출력.
- **결정론적 repair + LLM-free 검증** — 단일 ETF 20%, 카테고리 cap, 위험자산 70%, 상관 클러스터 cap을 water-fill로 수선한 뒤, 독립 validator가 재검증한다. 실패 시 재시도 → 안전 fallback 사이클.
- **회전율 컴플라이언스 도구** — 대회의 초기 ≥80%·월간 ≥10% 회전율 floor를 체결 명목금액 기반으로 월누적(MTD) 추적하고, 미달 예상 시 경고한다.
- **방어적 데이터 레이어** — FRED / ECOS / KRX / KOFIA / yfinance fetcher 전반에 tiered cache, look-ahead 차단 PIT guard, 발표 지연(publication lag) 처리, rate-limit 게이트, hard timeout.
- **Observability** — 모든 run이 archive되어 LLM 재호출 없이 단일 stage 재현이 가능하다 ([`scripts/replay_stage.py`](scripts/replay_stage.py)); LangSmith tracing은 선택 활성화.

## How it works — 어떻게 동작하나

전체 방법론은 [`docs/`](docs/)에 있다 (한국어). 각 단계는 해당 문서로 링크한다.

**Stage 1 — 병렬 분석가 4종** ([docs/stages/](docs/stages/)). 서로 직교하는 시장 관점: `macro_quant`는 매크로 데이터만으로 성장–인플레 regime을 분류하고(가격 내생성 회피), `market_risk`는 시스템 스트레스를 점수화하며(변동성, 신용, breadth, 펀딩), `technical`은 유니버스 모멘텀과 상관 클러스터를 계산하고, `macro_news`는 이벤트·섹터 테마를 정리한다. 각자 압축된 구조화 report를 handoff한다.

**Stage 2 — 리서치 디베이트** ([docs/design/2026-06-02](docs/design/2026-06-02-stage2-3-merge-llm-research-trader-design.md)). Bull·Bear 리서처가 동일한 사실을 적대적으로 재해석하고, manager가 이를 종합해 5단계 risk tilt와 핵심 리스크가 담긴 구조화 thesis를 만든다. 이 thesis 텍스트가 allocator의 view 프롬프트를 grounding한다.

**Stage 3 — Black-Litterman allocator** ([docs/design/2026-06-20](docs/design/2026-06-20-bl-allocator-design.md), [2026-06-23](docs/design/2026-06-23-confidence-scaled-prior-design.md)). 14개 자산 bucket(방어 5 + 성장 9) 위에서: confidence-scaled prior가 포트폴리오를 앵커하고, LLM이 bucket 상대 랭킹(zero-sum view로 변환)을, 결정론적 룰이 FX/credit view를 제공한다. view는 confidence 기반 불확실성 가중으로 prior와 결합되고, 제약 최적화가 mandate cap + active-share 예산 아래 bucket 가중치를 산출한다. view가 없으면 최적화기가 기준 포트폴리오를 정확히 복원한다 — 테스트로 잠근 불변식이다.

**ETF 선정** ([docs/design/2026-06-16](docs/design/2026-06-16-etf-selection-hybrid-design.md)). bucket 가중치를 실제 ETF로 변환한다: 동질 bucket은 자격 스크린 후 AUM 가중, 이질 bucket(선진 코어, 글로벌 테크, 기타 해외)은 LLM 테마 view → 위험조정 모멘텀으로 선정한다.

**Repair 루프와 validator** ([docs/methodology/mandate-validation.md](docs/methodology/mandate-validation.md)). 결정론적 water-fill repair가 모든 cap을 강제한 뒤, 독립적인 LLM-free validator가 무결성·유니버스 소속·단일 ETF cap·위험자산 cap·상관 클러스터를 재검증한다(초기 회전율 floor는 하드 게이트, 월간 floor는 여기서는 advisory — 권위는 리밸런싱 엔진의 체결 명목 검사에 있다). 실패 시 위반 피드백과 함께 allocator를 최대 2회 재시도하고, 그래도 실패하면 제약 재최적화 fallback으로 착지하며 그 결과를 다시 검증한다 — 파이프라인은 위반 상태를 숨긴 채 포트폴리오를 내보내지 않는다.

**산출물 & 리밸런싱** ([docs/stages/stage6-portfolio-manager.md](docs/stages/stage6-portfolio-manager.md), [docs/methodology/rebalancing.md](docs/methodology/rebalancing.md)). 매 실행마다 `portfolio.json`(prior → view → final 귀속을 담은 전체 의사결정 trace), `philosophy.md`(대회가 채점하는 투자철학 보고서), `trade_plan.csv`(실행 가능한 주문 계획)를 산출한다. 리밸런싱은 보유를 재평가하고, 캘린더/드리프트/이벤트 트리거를 평가하고, tier별로 목표를 재산출한 뒤, 결정론적 매매 델타를 만든다.

## 데이터 레이어

외부 데이터는 방어적으로 가져온다 — 라이브 API는 불안정하다는 전제다:

| 소스 | 제공 데이터 |
|---|---|
| **FRED** | 미국 매크로 50+ 시계열 (금리, CPI/PCE, 고용, CFNAI, NFCI, 스프레드) |
| **ECOS** (한국은행) | 한국 매크로 (기준금리, CPI, 수출입, 산업생산, CLI, BSI) |
| **pykrx / KRX OpenAPI** | ETF 유니버스 일별 OHLCV, KOSPI/VKOSPI, 현재가 |
| **KOFIA FreeSIS** | 시장 전체 신용잔고 |
| **yfinance** | 글로벌 주식·섹터·overnight 지수 (STOXX, N225, WTI, USDKRW, …) |
| **BIS / Shiller / GPR** | 중국 신용 impulse, 미국 CAPE, 지정학 리스크 지수 |

방어는 겹겹이 쌓인다: FRED 쿼터 아래로 선제 제어하는 rate-limit 게이트 + exponential backoff 재시도, 소켓 hang을 격리하는 hard timeout, 과거 `as_of` 날짜에 live-only 데이터를 비우는 point-in-time guard, 발표 지연을 인지하는 tiered cache, 그리고 모든 것이 실패했을 때의 최후 안전자산 포트폴리오.

## 프로젝트 구조

```
tradingagents/
├── graph/          # LangGraph 조립 — 진입점, topology, validation router
├── agents/         # analysts / researchers / trader (allocator) / validator / managers
├── skills/         # 결정론적 skill 카탈로그 — macro / risk / technical / news / portfolio / mandate
│   └── portfolio/  # 배분 핵심: bl_engine · bucket_cov · candidate_selector · gaps_buckets
├── rebalance/      # 보유 재평가, 트리거, tier별 목표, 매매 델타
├── dataflows/      # fetcher + 캐시 + 방어 (FRED / ECOS / pykrx / KRX / KOFIA / PIT guard)
├── schemas/        # LLM 접점 전체의 Pydantic 모델
└── observability/  # run archive + stage replay

cli/                # `gaps` CLI (Click)
data/               # universe.json + 캐시
docs/               # methodology / stages / design / audits / setup (한국어)
tests/              # 단위 · 통합 · smoke · eval (pytest 마커)
```

## 개발

```bash
pytest tests/unit -q                        # 빠른 단위 테스트
pytest tests/ -m "not slow and not eval"    # 단위 + 통합
pytest tests/ -m slow                       # 풀 파이프라인 E2E (mock)
pytest tests/ -m eval                       # LLM 품질 eval (API 키 필요)
```

CI는 없다 — 상단 배지는 로컬에서 실행한 스위트 기준이다. Windows에서는 `PYTHONUTF8=1`로 실행할 것.

## 프로젝트 상태

**대회용 리서치 코드이지, 유지보수되는 제품이 아니다.** 3개월 대회 기간 동안 1인이 만들고 운용했으며(AI 보조 엔지니어링을 적극 활용), 대회 후 참조 구현으로 공개한 것이다. 대회 특화 상수, 한국어 문서·프롬프트가 남아 있고, 유지보수·지원은 보장하지 않는다. 이 리포지토리 어디에도 성과 수치를 싣지 않았다 — 단일 시장 환경은 표본 1개일 뿐이며, 데이터가 무엇을 뒷받침할 수 있었고 무엇을 뒷받침하지 못했는지는 [LIMITATIONS.md](LIMITATIONS.md)에 정확히 기록했다.

## 문서

[`docs/`](docs/) 아래 문서는 모두 **한국어**다 (대회의 작업 언어):

- [`docs/methodology/`](docs/methodology/) — 리밸런싱·의무사항 검증의 동작 방식
- [`docs/stages/`](docs/stages/) — stage별 파이프라인 문서
- [`docs/design/`](docs/design/) — 주요 서브시스템별 날짜 있는 설계 문서
- [`docs/audits/`](docs/audits/) — 현행 아키텍처의 근거가 된 전체 파이프라인 감사
- [`docs/setup/`](docs/setup/) — 사전 요구사항·환경 설정
- [`docs/competition-rules-summary.md`](docs/competition-rules-summary.md) — 대회 규정 자체 요약 + 코드 상수 대응표
- [`LIMITATIONS.md`](LIMITATIONS.md) — 이 프로젝트가 약속하지 **않는** 것; 정직한 방법론 공시
- [`ROADMAP.md`](ROADMAP.md) — 알려진 미해결 항목과 보류 중인 결정

개발 기간의 역사 문서 85편(설계/플랜/감사)은 트리에서 제거했으며 git 태그 **`docs-archive-2026-08`**에 보존되어 있다.

## Acknowledgements — 감사의 글

이 프로젝트는 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 위에 서 있다. 멀티에이전트 디베이트 아키텍처, LangGraph 오케스트레이션, provider 추상화가 이 시스템이 자라난 골격이다. 포크는 크게 갈라졌지만 — 다른 자산군, 다른 목표, 다른 배분 엔진 — 업스트림의 설계 DNA가 곳곳에 남아 있다. 이 리포지토리가 유용했다면 업스트림의 논문도 함께 인용해 달라:

```bibtex
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

## Disclaimer — 면책 조항

이 소프트웨어는 **연구·교육 목적으로만 제공된다. 투자 조언이 아니며**, 이 시스템의 어떤 산출물도 금융상품 매수·매도 권유로 받아들여서는 안 된다. 파이프라인 일부는 대형 언어 모델을 호출한다: 그 출력은 실행마다 달라질 수 있고, 틀릴 수 있으며, 결정론적 검증 레이어가 피해를 제한하지만 제거하지는 못한다. 사용에 따른 책임은 사용자에게 있다.

## License — 라이선스

[Apache License 2.0](LICENSE) — 업스트림 TradingAgents 프로젝트에서 승계.
