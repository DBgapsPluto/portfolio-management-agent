# DB GAPS 투자대회 규정 요약 (자체 정리)

> 주최측 원문 자료(룰북 문서, ETF 리스트 xlsx, 버킷분류 xlsx)는 주최측 저작물이라 리포지토리에 동봉하지 않는다.
> 본 문서는 시스템 구현·검증에 필요한 수치·공식·제약을 **자체 언어로 재정리**한 것이며,
> 각 규정이 코드의 어느 상수/모듈로 강제되는지의 대응표를 겸한다.

## 1. 대회 개요

- 제12회 DB GAPS 투자대회. 운용 기간 **2026-06-01 ~ 2026-08-31 (3개월)**, 시작 자본 **10억 KRW**, 모의 MTS 계좌로 실시간 운용.
- 3인 1팀 구성, 주문은 팀장 계정으로만 가능. 타 팀과의 비중 협의·복제는 금지(적발 시 페널티).
- 투자 대상은 **국내 상장 ETF 188종**(개별 주식 직접 매매 불가). 해외 지수 추종 ETF도 국내 상장물이므로 정규장 **09:00–15:30**·원화 결제이며 시간외 거래는 없다.
- 코드 대응: 시작 자본 `capital_krw = 1_000_000_000` (`tradingagents/graph/trading_graph.py`), 유니버스는 주최측 ETF 리스트를 파싱한 `data/universe.json` (`gaps universe sync`).

## 2. 비중 제약 (mandate)

| 규정 (자체 요약) | 값 | 코드 상수 · 위치 |
|---|---|---|
| 위험자산(국내·해외 주식, FX·원자재) 합계 상한 | ≤ 70% | `HARD_RISK_ASSET_CAP = 0.70`, 위험 분류 `RISK_BUCKET_NAMES` — `tradingagents/skills/mandate/concentration_check.py` |
| 안전자산(국내·해외 채권, 금리연계 초단기채) | 상한 없음 | 위험 집합의 여집합으로 처리 |
| 단일 ETF 종목당 상한 | ≤ 20% | `HARD_SINGLE_CAP = 0.20` — 동 파일; 배분층은 `SINGLE_CAP` (`skills/portfolio/within_bucket.py`) |
| 세부 자산군(category)별 상한 | 아래 표 | `CATEGORY_CAPS` — 동 파일 (2026-06-08 `cfaaeda`로 주최측 세부 상한을 코드에 반영) |

`CATEGORY_CAPS` 세부값: 국내주식_지수 0.30 · 국내주식_섹터 0.15 · 해외주식_지수 0.30 · 해외주식_섹터 0.10 · FX 및 원자재 0.20 · 국내채권_종합 0.50 · 국내채권_회사채 0.30 · 해외채권_종합 0.50 · 해외채권_회사채 0.30 · 금리연계형/초단기채권 0.50.

위반 시 파이프라인은 결정론 repair(`risk_repair` / `category_repair` / `cluster_repair`)로 수선 후 `mandate_validator`가 재검증한다.

## 3. 회전율 규정 (미달 시 탈락 — 가장 중요한 시스템 제약)

- **정의**: 회전율 = (매수금액 + 매도금액) ÷ 평균자산, 평균자산 = (기초자산 + 기말자산) ÷ 2. 매수·매도 **양변 합산**(total trade volume) 기준이다.
  - 코드: `compute_trade_turnover` (`tradingagents/skills/mandate/turnover_check.py`) — 월누적(MTD) 집계용 동일 공식.
- **초기 세팅**: 대회 시작 후 **5영업일 이내 누적 80% 이상**.
  - 코드: `TURNOVER_FLOOR_INITIAL = 0.80` (`tradingagents/agents/validator/mandate_validator.py`), `tradingagents/monitor/turnover.py`의 initial < 0.80 경고.
- **월별 유지**: 6·7·8월 각각 **월 10% 이상**.
  - 코드: `TURNOVER_FLOOR_MONTHLY = 0.10` (동 파일); 리밸런스 엔진의 체결-명목 기반 MTD 추적·미달 예상 경고 (`tradingagents/rebalance/engine.py`, `reports/rebalance_plan.py`).
- 주최측 시스템은 미달을 사전 경고하지 않는다 → 팀이 자체 추적해야 하며, 위 MTD 추적이 그 대응이다. (모의 MTS는 API가 없어 체결 대사는 수동 CSV 추출 기반.)

## 4. 보고서 의무

- **투자 계획서** 1회 (제출 마감 2026-05-28, 지각 불가): 3개월 투자 철학·자산군별 전망·구체 전략. → 시스템 산출물 `philosophy.md`가 이 요구를 겨냥해 설계됨.
- **월간 운용 보고서** 3회 (6·7·8월): ① 수익률 원인 분석 ② 비중 변경의 논리적 근거 ③ 다음 달 전망·대응 전략. → `tradingagents/reports/monthly.py`.
- 외부 자료 복사-붙여넣기 금지 — 팀 자체 언어·논리로 재구성해야 함. 미제출/백지 제출은 탈락.

## 5. 평가 구조

1. **1차 컷**: 2026-08-31 종가 기준 누적수익률 **상위 30팀**.
2. **2차 종합심사**: 수익률 **30점** + 투자 철학 **70점** 합산 → 우수 10팀. 철학 심사의 핵심: 계획서 로직이 실제 운용에 일관 적용됐는가, 시장 충격 시 방어 논리, 표면적 분산이 아닌 **내부 상관관계 기반 단일 리스크 통제**.
3. **3차**: 상위 4팀 PT·토론.

→ 철학 70% 배점이 본 시스템의 설계 우선순위(결정론 mandate 준수, BL attribution, 상관 클러스터 cap과 correlation facts 리포팅)를 결정한 배경이다. `LIMITATIONS.md` §3 참조.

## 6. 원본 자료 ↔ 리포 산출물 대응

| 주최측 원본 (미동봉) | 리포에 남긴 것 |
|---|---|
| ETF 리스트 xlsx (188종) | 파싱 결과 `data/universe.json` — 새 xlsx 수령 시 `gaps universe sync --xlsx <path>`로 재생성 |
| 14-버킷 분류 xlsx | `universe.json`의 `gaps_bucket` 필드 + `tradingagents/skills/portfolio/gaps_buckets.py` 상수 (1회성 병합: `scripts/enrich_universe_gaps_bucket.py`) |
| 룰북 문서 | 본 요약 문서 |
