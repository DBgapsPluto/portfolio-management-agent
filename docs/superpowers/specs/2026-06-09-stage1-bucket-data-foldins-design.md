# Stage 1 — 14버킷 약점 보강 데이터 fold-in 설계

> 작성 2026-06-09. Stage 1(분석가 레이어)에 14 GAPS 버킷의 **펀더멘털·거시 드라이버** 데이터를 보강한다 — 약점 6버킷(A2·B1·B3·B5·B7·B9) + 14버킷 완전성 감사로 발견한 A4. **신규 애널리스트 노드 0 — 전부 기존 4개 노드에 fold-in.** 전부 무료 소스·기존 fetcher 재사용·핵심 산출 LLM 0.

---

## 1. 목적

GAPS 14버킷([gaps_buckets.py](../../../tradingagents/skills/portfolio/gaps_buckets.py)) 중 6개 버킷은 Stage 1 데이터로 **펀더멘털/거시 시황을 명확히 판단하기 어렵다**(진단 결과 §2). 이 공백을 무료·결정론 데이터로 메운다. 자산배분 결정을 바꾸는 것이 아니라, **각 버킷의 시황 인식을 균일하게 끌어올리는 입력 데이터**를 추가하는 것이 목표다.

대회 평가가 "수익률 30% + 투자철학 70%"이고 그 핵심이 "시장 충격 시 방어 논리 / 상관관계로 단일 리스크(AI 쏠림) 통제"이므로, 특히 **B3(글로벌 테크·반도체)**·**B7(리츠)**의 펀더멘털 공백 해소가 가치가 높다.

> **14버킷 완전성 감사(2026-06-09)**: 약점 6버킷 외 나머지 8버킷까지 1차 드라이버 vs 커버리지를 전수 감사한 결과, "충분하다 가정했던" 버킷 중 **A4(안전통화)에만 진짜 1차 공백**이 발견되어 §5.7로 추가한다(엔 leg 전무). 나머지(A5 금=실질금리, B2 유럽·일본 등)는 기존/광역 데이터로 커버됨을 확인. B8 원유재고·B9 CCC-OAS는 §8(후속/보류)로 분류.

## 2. 배경 — 진단 결과

stage1은 두 종류 데이터를 산출한다:
- **가격/기술축** = `technical`의 `factor_panel`(188 ETF 모멘텀/변동성/샤프/규모) + `compute_sector_rotation`(universe ETF를 **category별 집계**). → **14버킷 전부 가격 신호는 이미 흐른다.**
- **거시/펀더멘털축** = `macro_quant`의 25 snapshot. → 버킷별 커버리지가 극과 극.

코드 검증으로 확인된 핵심 사실:
- 14버킷은 [gaps_buckets.py](../../../tradingagents/skills/portfolio/gaps_buckets.py)에 이미 정의·운영 중(A1~A5, B1~B9).
- REIT·2차전지·신흥국·하이일드·KR섹터·KR반도체 ETF는 전부 universe에 등재되어 [technical_analyst.py:156](../../../tradingagents/agents/analysts/technical_analyst.py#L156) `fetch_etf_price_batch`로 **매일 가격이 batch fetch**된다.
- [sector_rotation.py:41-61](../../../tradingagents/skills/technical/sector_rotation.py#L41)은 US 전용이 아니라 universe를 category별로 집계 → KR 섹터 모멘텀도 이미 계산된다.

→ **결론: 진짜 공백은 "가격"이 아니라 "거시 드라이버/펀더멘털" 소수다.** 따라서 신규 노드가 아니라 fold-in이 정답.

## 3. 설계 원칙

1. **신규 애널리스트 노드 0** — 모든 데이터는 기존 4개 노드(`macro_quant`/`market_risk`/`technical`/`macro_news`) 안의 snapshot 필드/객체로 추가한다.
2. **신규 fetcher/클라이언트 0** — 기존 `ecos.fetch_ecos_series`·`fred.fetch_fred_series`·`cross_asset_returns._raw_yf_batch`·`fetch_etf_price_batch` 재사용.
3. **핵심 산출 LLM 0** — 모든 신규 필드는 시리즈 차분·rolling percentile·z-score·랭킹 등 산술 파생. 선택적 ≤300자 narrative만 quick_llm(생략 가능).
4. **후방호환** — 신규 필드는 전부 `default=0.0`/`None`. 기존 archive·테스트 무영향.
5. **staleness 축 분리** — 일별/주간/월간 데이터가 한 snapshot에 섞이면 freshness를 필드별로 분리 표기.

## 4. 검증 게이트 결과 (2026-06-09 라이브 fetch)

| 데이터 | 결과 | 비고 |
|---|---|---|
| 칩 PPI `PCU334413334413` | ✅ 711행, last 2026-04-01 | 월간·~2개월 lag |
| HY OAS `BAMLH0A0HYM2` / IG OAS `BAMLC0A0CM` | ✅ live, last 2026-06-05 (2.76 / 0.74) | **backtest는 BAA10Y 붕괴(§7)** |
| 미국 ETF/지수 10종 (^SOX·SMH·EEM·EMB·VWO·HYG·JNK·VNQ·XLRE·SCHH) | ✅ 전부 live OK | yfinance |
| KR REIT (329200·476800·182480·352560) | ✅ pykrx 경로 검증 완료 (KRX 로그인 후 6종 fetch) | yfinance `.KS`는 불가. 329200=3,845·476800=4,185 등 |
| 모기지 30Y `MORTGAGE30US` (B7) | ✅ last 2026-06-04 = 6.48% | project fred fetcher로 재확인 완료(초기 timeout은 일시적) |
| JPY/USD `DEXJPUS` (A4) | ✅ last 2026-06-05 = 160.26 | DEXKOUS=1555.96 → JPY/KRW=9.71 cross 복원 확인 |
| **ECOS A2** 국고채5y/30y·BBB-·CD91 (817Y002 D) | ✅ last 2026-06-08 전부 fetch | 5y=4.19%·30y=4.348%·BBB-=10.371%·CD91=2.92% |
| **ECOS B1** 섹터 수출물량 (403Y002 M) | ✅ 품목코드 5종 검증 | 반도체 30911AA·전지 31013AA·디스플레이 30921AA·화학 305AA·철강 3071AA, last 202604 |
| CCC OAS `BAMLH0A3HYC` (B9 후보) | ✅ active·daily but history 2023-06+ | **backtest는 us_hy_oas와 동일 BAA10Y fallback → 보류(§8)** |

## 5. 버킷별 fold-in 상세

### 5.1 A2 국내금리 → `market_risk`

기존 [kr_yield_curve.py](../../../tradingagents/skills/risk/kr_yield_curve.py)(3y/10y)·[kr_corp_spread.py](../../../tradingagents/skills/risk/kr_corp_spread.py)(AA- 3y)의 **해상도 확장**.

- **추가 데이터** (ECOS `817Y002`, freq=D, [ecos.py](../../../tradingagents/dataflows/ecos.py) `ECOS_STAT_CODES`에 4줄 추가):
  - 국고채 5년 `010200001`, 국고채 30년 `010230000`
  - 회사채 BBB- 3년 `010320000` (주석에 이미 "010320000은 BBB-" 명시됨)
  - CD 91일 `010502000`
  - 재사용: 국고채 3y `010200000`/10y `010210000`, 회사채 AA- `010300000`, 기준금리(`macro_quant` 보유)
- **snapshot 변경**:
  - `KRYieldCurveSnapshot` += `treasury_5y`, `treasury_30y`, `spread_30y_5y_bps`, `curve_shape`(flat/steep/inverted/humped — 3y/5y/10y/30y butterfly 부호 분류)
  - `KRCorpSpreadSnapshot` += `corp_bbb_yield_3y`, `bbb_aa_quality_spread_bps`(등급 프리미엄)
  - 신규 `KRShortRateSnapshot` { `cd91`, `cd91_minus_treasury3y_bps`(자금시장 funding stress), `regime` }
- **determinism**: LLM 0.

### 5.2 B1 한국섹터 → `macro_quant`

가격 모멘텀은 `sector_rotation`이 이미 계산. **신규는 섹터 수출물량(펀더멘털)만.** KRX OpenAPI 업종지수는 **드롭**(영업일당 1 HTTP콜 → 60d 모멘텀 시 ~130콜/일, [krx_openapi.py:169](../../../tradingagents/dataflows/krx_openapi.py#L169); 가격은 이미 ETF로 커버되어 중복).

- **추가 데이터** (ECOS `403Y002` 섹터별 수출**물량**지수, freq=M — 주의: 기존 `kr_export`가 쓰는 `403Y001`은 금액, 물량은 `403Y002`):
  - 반도체 `30911AA`, 전지 `31013AA`, 디스플레이 `30921AA`, 통신장비 `30951AA`, 의약품 `30541AA`, 화학 `305AA`, 철강 `3071AA`
- **snapshot 변경**: 신규 `KRSectorExportSnapshot` { `{sector}_export_volume_yoy`, `{sector}_momentum_3mo`, `accelerating` }. 월간 staleness 별도 표기.
- **determinism**: LLM 0.

### 5.3 B3 반도체 → `technical` + `macro_quant`

- **추가 데이터**:
  - `technical`: yfinance `^SOX`(PHLX 반도체지수), `SMH`(VanEck 글로벌 반도체 ETF) — `cross_asset_returns._raw_yf_batch`에 배치 추가
  - `macro_quant`: FRED `PCU334413334413`(칩 PPI, 월간) — [fred.py](../../../tradingagents/dataflows/fred.py) `FRED_SERIES`에 `us_chip_ppi` 1줄
  - 재사용: KR 반도체 ETF(`091160`·`395270`)는 이미 universe·매일 fetch
- **snapshot 변경**:
  - `technical`: 신규 `SemiMomentumSnapshot` { `sox_mom_3m/6m/12m`(skip1m), `smh_vs_spy_rel_strength`, `sox_minus_smh_divergence`, `vol60d` } — factor_panel 산식 재사용
  - `macro_quant`: 신규 `ChipCycleSnapshot` { `chip_ppi_yoy`, `momentum_3mo`, `accelerating` } — InflationSnapshot 패턴. 월간 staleness 분리.
- **determinism**: LLM 0.

### 5.4 B5 신흥국 → `macro_quant`

China(`ChinaLeadingSnapshot`)·FX(`FXSnapshot`)·risk_appetite 클러스터 인접 배치.

- **추가 데이터**: yfinance `EEM`(MSCI EM)·`EMB`(EM USD bond)·`VWO`(보조) — `_raw_yf_batch`. 재사용: `DXY`(`DTWEXBGS`), KR상장 EM ETF(`195980`·`245710` 이미 universe).
- **snapshot 변경**: 신규 `EmergingMarketSnapshot` { `em_equity_mom_3m/6m`(EEM), `em_vs_dxy_rel_strength`, `em_debt_carry_proxy`(EMB 가격기반), `regime`(risk_on/neutral/risk_off) }.
- **determinism**: LLM 0.

### 5.5 B7 리츠 → `market_risk`

REIT ETF 가격은 이미 universe로 흐름. **신규는 거시 드라이버**(REIT yield−10Y 스프레드, 모기지).

- **추가 데이터**:
  - FRED `MORTGAGE30US`(30y 모기지, 주간 — carry-forward로 daily 사용, NFCI 패턴), `DGS10` 재사용
  - REIT yield: `VNQ` `history(actions=True)` TTM 배당/가격 (소형 신규 헬퍼 1개; `.info['dividendYield']`는 단위 모호 → 금지)
  - REIT dispersion: yfinance `VNQ`/`XLRE`/`SCHH`
  - KR REIT: `329200`·`476800`을 **universe.json 등재** → 기존 `fetch_etf_price_batch` 경로(production KRX 자격증명 전제)
- **snapshot 변경**: 신규 `REITDriverSnapshot` { `us_reit_tr_mom_3m/6m`(VNQ), `us_reit_dispersion`, `kr_reit_tr_mom_3m`, `reit_yield_minus_10y_bps`, `mortgage_30y`, `mortgage_30y_change_4w_z`, `regime`(easing/neutral/tightening) }. 주간/월간 staleness 분리.
- **determinism**: LLM 0.

### 5.6 B9 하이일드 → `market_risk`

[credit_spread.py](../../../tradingagents/skills/risk/credit_spread.py)가 이미 `us_hy_oas`(`BAMLH0A0HYM2`)를 `SpreadSnapshot(region='US_HY')`로 보유 → **HY-IG decompression 확장**.

- **추가 데이터**: `BAMLH0A0HYM2`·`BAMLC0A0CM`(둘 다 기보유, 0-cost), HYG/JNK total-return(yfinance, daily 시장반응 보강)
- **snapshot 변경**: `SpreadSnapshot(US_HY)` 확장 또는 신규 `HYDecompressionSnapshot` { `hy_oas_bps`, `ig_oas_bps`, `hy_minus_ig_bps`, `decompression_percentile_5y`, `hy_etf_return_5d`, `regime`(calm/widening/stress) }.
- **determinism**: LLM 0.
- **⚠️ 차단 조건(§7)**: OAS decompression은 backtest에서 작동 불가 → live-only 또는 HYG/JNK total-return을 primary decompression proxy.

### 5.7 A4 안전통화 → `macro_quant` (14버킷 감사로 발견)

엔 2종(엔선물 `292560` + 엔초단기국채 `489000` = 버킷 가중 2/3)의 1차 가격 driver인 **JPY-leg가 stage1에 전무**. 현재 [fx.py](../../../tradingagents/skills/macro/fx.py) `compute_fx_overlay`는 USD/KRW·DXY만 입력 → JPY/KRW cross를 0으로 인식(DXY의 엔 비중으로는 KRW-leg 부재 탓에 복원 불가).

- **추가 데이터**: FRED `DEXJPUS`(JPY/USD spot, daily). yfinance `JPY=X` fallback(무키). `DEXKOUS`는 기보유.
- **snapshot 변경**: `FXSnapshot` += `jpy_krw`(= `usd_krw / usd_jpy`), `jpy_krw_change_1m_pct`. `compute_fx_overlay` 확장.
- **fetch_plan**: [fred.py](../../../tradingagents/dataflows/fred.py) `FRED_SERIES`에 `'usd_jpy':'DEXJPUS'` 1줄 + `publication_lag_days` `usd_jpy:1`. `_raw_fred_call` 재사용, 신규 클라이언트 0.
- **determinism**: LLM 0 (cross 산술).
- **검증**: 라이브 통과(§4). 14버킷 중 "광역지표로 안 잡히는" 유일한 1차 공백.

## 6. 공통 인프라 변경

- **ECOS** ([ecos.py](../../../tradingagents/dataflows/ecos.py)): `ECOS_STAT_CODES`에 A2 4종 + B1 7종(`403Y002`) 추가, `publication_lag_days`에 신규 키(daily=1, monthly≈30). 코드 경로 변경 0.
- **FRED** ([fred.py](../../../tradingagents/dataflows/fred.py)): `FRED_SERIES`에 `us_chip_ppi`·`us_mortgage_30y` 등록(passthrough), `publication_lag_days` 추가. HY/IG OAS는 기보유.
- **yfinance** ([cross_asset_returns.py](../../../tradingagents/dataflows/cross_asset_returns.py)): 신규 심볼(^SOX·SMH·EEM·EMB·VWO·HYG·JNK·VNQ·XLRE·SCHH) 추가. **⚠️ 캐시키가 `"_".join(sorted(symbols))`라서 심볼셋 변경 시 기존 11-SPDR 캐시 전 구간 재페치** → 신규 yf 심볼은 **별도 cache namespace/key로 분리**하거나 `equity_indices` 단일 시리즈 캐시 경로 사용.
- **universe.json**: KR REIT `329200`·`476800` 등재(B7).

## 7. 차단 조건 & 리스크

1. **B9 backtest 붕괴(hard)**: [fred.py:124-128](../../../tradingagents/dataflows/fred.py#L124) `FRED_FALLBACK_CHAIN`이 `us_hy_oas`·`us_ig_oas`를 둘 다 `BAA10Y`(`us_credit_proxy`)로 fallback → historical 경로에서 `hy_minus_ig`가 항상 0. **decompression은 live-only로 한정하거나 HYG/JNK total-return을 primary proxy로 사용. snapshot docstring에 명시.**
2. ~~**KR REIT(blocking 검증)**~~ → **해소(2026-06-09)**: `.env`의 KRX 자격증명으로 pykrx 로그인 후 `329200`/`476800`/`182480`/`352560` 전부 fetch 성공. yfinance `.KS`는 불가 확인. KR REIT는 universe 등재 + 기존 pykrx 경로로 통합.
3. **칩 PPI / 모기지(staleness)**: 월간/주간 + lag → snapshot에 price_freshness vs macro_freshness 분리 표기 강제. carry-forward 사용.
4. **칩 PPI 단종 리스크**: `PCU334413334413`는 게이트 통과(711행)했으나 BLS PPI 단종군 — fetch 실패 시 graceful(default None + 경고).
5. **yfinance 캐시 busting**: §6 — 신규 심볼 캐시 분리 미적용 시 매 fetch 전 구간 재페치.

## 8. 비범위 (Out of Scope)

- **신규 애널리스트 노드** — 전부 fold-in으로 결정.
- **KRX OpenAPI 업종지수**(B1 가격축) — 비용·중복으로 드롭. KR 섹터 가격은 기존 ETF/sector_rotation 재사용.
- **유료/과도지연 데이터** — Green Street CPPI, Nareit implied cap rate, Case-Shiller(CSUSHPINSA), Z.1 CREPI, MOTIE 일별 수출, FRED WILLREITIND(2024-06-03 영구제거) 등 8건 드롭.
- **B6 방어적 주식(배당·저변동)** — factor_panel(low-vol/quality)이 이미 정답. 추가 데이터 불필요.
- **버킷별 데일리 시황 *서술* 리포트 생성 로직** — 이 spec은 *데이터 입력*까지. 서술 레이어는 별도 작업.
- **stage2 시나리오 추정 입력 변경** — 신규 snapshot은 stage1 산출에 추가될 뿐, stage2가 이를 어떻게 소비할지는 별도 결정.

### 8.1 후속 과제 / 보류 (14버킷 감사 결과)

- **B8 원유재고(EIA)** — WTI 선행 공급동인으로 가치는 sound하나, **FRED에 부재**(EIA가 FRED 피드 중단, 라이브 확인). net-new `dataflows/eia.py` fetcher + 신규 `EIA_API_KEY` 필요 = drop-in 불가. 이번 spec 비범위, 별도 EIA 통합 과제로 분리(도입 시 천연가스 재고도 동일 인프라로 후속).
- **A5 gold↔real-rate decomposition** — 데이터는 모두 보유(`DFII10`=`us_tips_10y` + gold). 금 가격을 실질금리와 연결하는 *해석 skill*만 부재. **신규 데이터 불필요**, 후속 skill 과제.
- **B9 CCC-OAS(`BAMLH0A3HYC`) — 보류.** within-HY distress 신호로 매력 있으나, history가 2023-06+라 backtest 대부분 구간에서 기존 `us_hy_oas`와 동일 `BAA10Y` fallback으로 수렴 → "비중복" 명분이 라이브 ~2년에서만 성립. 사용자 "억지 추가 금지" 원칙 + A5/B2 기각 기준과의 일관성으로 이번엔 제외. 채택 시 "라이브 전용 보조신호, 2023-06 이전 backtest는 HY-OAS와 동일값"을 명시할 것(§10).

## 9. 성공 기준 (Verification)

1. 7개 버킷 각각에 대해, 신규 snapshot이 라이브 데이터로 채워지고 `default` sentinel이 아닌 실값이 나온다(B9 OAS, A2 커브, B3 SOX/칩PPI, B5 EEM/EMB, B7 모기지/REIT yield, B1 수출물량, **A4 jpy_krw cross**).
2. 신규 필드는 전부 결정론 — 동일 `as_of`·동일 입력이면 동일 산출(LLM 0).
3. 기존 4 애널리스트의 기존 필드·archive·단위테스트 회귀 0(default 후방호환).
4. B9 decompression이 backtest 경로에서 0으로 붕괴하지 않도록 live-only 가드 또는 ETF proxy가 동작.
5. KR REIT가 production `fetch_etf_price_batch`로 fetch된다(차단 조건 통과).
6. yfinance 신규 심볼 추가 후 기존 cross_asset 캐시가 전 구간 재페치되지 않는다(캐시 분리 검증).

## 10. 미해결 질문

1. **B9 신규 snapshot vs 기존 SpreadSnapshot 확장** — 둘 중 어느 형태로 fold-in할지(구현 계획에서 결정).
2. ~~**B1 수출 섹터 매핑** — ECOS `403Y002` 품목코드 확인 필요~~ → **해소(2026-06-09 라이브 검증)**: 반도체 30911AA·전지 31013AA·디스플레이 30921AA·화학 305AA·철강 3071AA 전부 fetch OK.
3. **칩 PPI staleness 허용폭** — 월간 ~2개월 lag을 daily 신호로 carry-forward할 때 허용 stale 일수.
4. **모기지 `MORTGAGE30US`** — production fred fetcher로 재확인(검증 환경 timeout).
5. **B9 CCC-OAS 채택 여부** — §8.1 보류. 라이브 전용 보조신호로 원하면 추가 가능(2023-06 이전 backtest는 HY-OAS와 동일값임을 명시 조건).

---

*관련: 진단 근거 [rebalancing-method.md](../../rebalancing-method.md) · Stage 1 [stage1. macro_quant.md](../../stage1.%20macro_quant.md) · Stage 2 [stage2. research.md](../../stage2.%20research.md) · Stage 3 [stage3. allocator.md](../../stage3.%20allocator.md) · 버킷 분류 [gaps_buckets.py](../../../tradingagents/skills/portfolio/gaps_buckets.py)*
