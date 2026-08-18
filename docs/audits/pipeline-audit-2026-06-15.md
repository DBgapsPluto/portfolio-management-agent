# 전체 파이프라인 검증 — 2026-06-15

> 브랜치 `rework/pipeline-methodology` 착수 시점의 라이브 파이프라인 정합성·방법론 감사.
> 방법: stage별 병렬 감사 7건 + warn/risk 발견 28건 적대적 재검증(confirmed/partly 25, refuted 3).
> 기능 검증: unit 1046 pass / mock E2E 2 pass / integration 53 pass (실패 2건은 Windows 환경 한정 — `/tmp`, pykrx#21).
> 평가 기준: 대회 목표 = 투자철학 70% + 수익률 30%, top-down 매크로 배분, 의무사항 결정론 준수.

## 0. 한 줄 결론

라이브 파이프라인은 **돌아가고 의무사항도 준수**하지만, **광고된 아키텍처(README)와 실제 코드가 크게 다르다.** 정교한 옵티마이저 스택(BL/NCO/HRP/shrinkage/ENB)과 retry→fallback 방어망은 대부분 **dead code 또는 도달 불가**이고, 실제 배분은 *quadrant 앵커 → LLM tilt → 밴드 투영 → AUM 가중 → cap 수선*의 결정론 경로다. 이 단순 경로 자체는 70%-철학 대회에 오히려 방어 가능하지만, ① 즉시 고쳐야 할 라이브 버그 군집과 ② "근거 없는 매직넘버 + 안 도는 옵티마이저"라는 신뢰성 갭이 있다.

## 1. 핵심 메타발견 — 광고 ≠ 라이브

| README/docs가 말하는 것 | 라이브 코드의 실제 | 증거 |
|---|---|---|
| HRP/Risk Parity/Min-Var/**Black-Litterman** method 선택 | `method_picker` 삭제됨(6/3). 배분은 `OptimizationMethod.AUM_WEIGHTED` 하드코딩 | trader_allocator.py:279,319 |
| **NCO** 상관 군집 최적화로 집중 분산 | `compute_nco_weights` **라이브 caller 0** (테스트만) | nco.py:125 |
| **Ledoit-Wolf + QIS** shrinkage | `compute_robust_cov`의 유일한 라이브 호출은 fallback의 min-vol뿐 | conditional_logic.py:49 |
| **BL views** 시나리오 rulebook 주입 | `generate_bl_views` **라이브 caller 0**; rulebook은 삭제된 8-bucket 키 사용(14-bucket과 불일치) | bl_views.py:84,17-54 |
| **ENB** 제약 fallback | `select_by_enb_greedy` **라이브 caller 0** | factor_scorer.py:517 |
| validator→retry(≤2)→fallback 방어망 | **retry 카운터가 증가 안 됨** → 무한 retry → GraphRecursionError. fallback 도달 불가 | conditional_logic.py:18, agent_states.py:77 |

→ **dead 옵티마이저 코드 + 거짓 docstring**(삭제된 `portfolio_allocator`/`method_picker` 참조)이 트리에 남아 있다. philosophy.md가 BL/NCO를 인용하면 *안 도는 방법론을 주장*하는 셈 — 코드 검수 시 70% 철학 점수에 역효과.

## 2. Stage별 건전성

| Stage | 판정 | 요지 |
|---|---|---|
| Stage 1 macro_quant + market_risk | **mostly-sound** | 4사분면 프레임 자체는 교과서적·방어가능. 단 regime은 결정론 backstop 없는 순수 LLM 1콜, confidence 미보정, systemic_score는 LLM이 합산하는 임의 가중치 |
| Stage 1 technical + macro_news | **mostly-sound** | momentum 정의는 PIT-clean. 단 뉴스 cutoff가 `utcnow()`(as_of 아님) → 백테스트 look-ahead; SAVE 카드가 랭킹 후 합쳐져 내러티브 미도달; 상관군집이 momentum top-5 풀로만 구성 |
| Stage 2 research_cluster | **questionable** | bull/bear/manager가 동일 입력·rebuttal 없는 단일 패스 = 값비싼 reformat. risk_tilt 5단 enum에 시계열 smoothing/hysteresis 없음(whipsaw) |
| Stage 3a anchor + modifiers + 선정 | **questionable** | QUADRANT_BASELINE·델타 전부 "v1 시드" 매직넘버(근거 없음). growth_inflation 앵커는 검증자 정의로 risk=0.73 → 70% cap **사전 위반**, repair에 의존. camp(방어/성장) vs mandate(위험/안전) **이중 비정합 taxonomy** |
| Stage 3b BL + optimizer + projection | **questionable** | 옵티마이저 스택 전부 dead. 라이브는 AUM 가중뿐 → **보유 종목 단위 위험분산 없음**. mandate 준수는 L2-최적 투영이 아니라 3-pass 휴리스틱 repair |
| Stage 5/6 validator + fallback + 산출물 | **questionable** | retry 카운터 버그로 fallback 도달 불가. fallback/emergency가 category·cluster·turnover 미보장하면서 `validation_passed=True` 자기 도장. philosophy.md 숫자 **프로그램적 검증 0**(환각 가능) |
| 리밸런싱 엔진 + 데이터층 | **questionable** | 방어 오버레이가 no_trade_band에 막혀 0.55~0.70 구간에서 **무력**(6/14 전량 HOLD의 진짜 원인). reassess tier 크래시, VKOSPI 트리거 death, prev_target 공백, monthly 수동-only |

## 3. 즉시 고쳐야 할 라이브 버그 (rewrite와 무관하게 위험)

| # | 심각도 | 버그 | 증거 | 영향 |
|---|---|---|---|---|
| B1 | **risk** | `allocation_attempts`가 어떤 노드도 증가시키지 않음 → 검증 실패 시 retry 무한루프 → GraphRecursionError로 런 abort. fallback 영구 도달 불가 | conditional_logic.py:18, agent_states.py:77,137, trader_allocator.py:315-321 | 결정론 repair가 못 막는 위반(turnover/cluster) 발생 시 **런 전체 중단** |
| B2 | **risk** | 방어 오버레이가 risk 0.55~0.70 구간에서 no_trade_band(50bp)에 막혀 0 trade. band 예외가 0.70 HARD cap에만 묶여 0.55 target엔 무효 | engine.py:84-89 vs default_config.py:58 | 일일 방어 레이어가 **사실상 inert** (6/14 현상) |
| B3 | **risk** | reassess tier가 디렉터리 경로를 파일로 `read_text()` | weekly_tilt.py:47-49 | regime-shift 리밸런싱 fire 시 **크래시** (현재는 트리거 미발동으로 잠복) |
| B4 | **risk** | daily가 portfolio.json 미출력 → `prev_target={}` → drift 평가가 current 기준으로 오작동, cluster stale | daily_full.py:77-79, rebalance_plan.py | drift 티어 발동 시 잘못된 앵커 |
| B5 | **warn** | VKOSPI 트리거 death — sentinel 0.0 < 25 영구 False | volatility.py:22-26, triggers_default.yaml:6 | emergency_defensive가 VIX 단독 의존(한국 신호 소실) |
| B6 | **risk** | fallback/emergency가 single-cap만 보장하면서 category(5×0.20 in 1 cat)·cluster·turnover 위반 가능 + `validation_passed=True` 자기 도장, 재검증 없음 | conditional_logic.py:50-73,132-170 | "방어망"이 정작 필요할 때 모든 규칙 우회 |
| B7 | **warn** | 뉴스 cutoff·랭킹이 `as_of` 아닌 `utcnow()` 사용 | news_macro.py:63,75, ranker.py:60 | 백테스트 look-ahead·재현불가 |
| B8 | **risk** | philosophy.md 숫자 검증 0 (길이 ≥4000자만 체크). 프롬프트 "숫자는 입력에서만" = 지시뿐 | philosophy.py:71,272-292 | **70% 철학 점수** — trace에 없는 regime/VIX/weight 환각 가능 |

> B1·B2는 ops 워크플로우의 6/14 분석과 교차확인됨. B3~B8은 단일 감사(미재검증)이나 file:line이 구체적이라 신뢰도 높음.

## 4. 방법론 적절성 — rewrite 검토 대상

1. **매직넘버 앵커/델타 (philosophy/risk).** QUADRANT_BASELINE(4×14)·RISK_TILT_AMOUNT·CREDIT/FX_MODIFIER 전부 근거 없는 라운드넘버. *역설*: 1970+ 데이터로 cycle×tail을 Bayesian shrinkage + walk-forward로 적합하는 **캘리브레이션 하베스트(`scripts/calibrate_playbooks.py` → `data/playbook_calibration.json`, 6/15 재생성)가 이미 존재하나 라이브 앵커에 미연결**(backtest 전용, 4-asset 공간이라 14-bucket과 미매핑). → 다리 놓으면 "1970+ 검증 연구에 앵커" 스토리 확보.
2. **regime 분류가 결정론 backstop 없는 순수 LLM 1콜.** 프롬프트에 이미 실행 가능한 임계(Sahm/CFNAI/곡선역전/NFCI, 3% CPI)가 산문으로 있음 → Python rules-vote로 계산해 LLM이 *조정*하게 + 둘 다 로깅하면 재현성·감사성↑.
3. **systemic_score 0-10이 LLM 합산 임의 가중치이고 배분을 거의 안 움직임.** → 표준화 z-score 가중합(고정·문서화 가중치) 결정론 composite로 교체, 선택적으로 risk_tilt/리스크예산에 결정론 연결.
4. **bull/bear/manager 디베이트 = 값비싼 reformat.** 동일 입력·rebuttal 없음·단일 패스. → 균형 전략가 단일 콜로 축소(비용 2/3↓, 변동성↓, 내러티브 동등) **또는** 진짜 적대적(분리 증거·rebuttal 라운드·논거 점수)으로. 단, live risk_tilt 경로 ablation 먼저.
5. **risk_tilt에 시계열 smoothing/hysteresis 없음.** 매주 stateless 재도출 → whipsaw. enum hysteresis(1단계/run, 하드 regime 변화 시만) 권장. (실제 진폭은 ±2.5~5pp로 stale 문서의 15-20pp보다 작음.)
6. **이중 비정합 risk taxonomy.** 14-bucket camp(방어/성장) ≠ mandate 8-bucket(위험/안전): A4 안전통화·A5 금=mandate-RISK, B9 하이일드=mandate-SAFE. philosophy.md가 둘을 나란히 LLM에 줘 자기모순 가능. → 단일 canonical 정의 또는 명시적 crosswalk.
7. **상관군집 cap이 momentum top-5 풀로만 계산** → 보유 중 non-top ETF의 집중은 cap에 안 보임. mandate 과소집행. → 실제 보유 집합으로 군집.
8. **방어 오버레이가 macro view 무시한 무딘 55% 일괄 cut.** 모든 위험자산 동일 비율 축소, 자유분은 비례 분배. → 리스크 예산 = f(systemic_score, regime), 고베타/충격 섹터부터, regime 선호 안전자산으로 water-fill.
9. **트리거 임계가 raw 레벨(VIX>30 등) 매직넘버.** VolatilitySnapshot이 이미 percentile_5y/zscore 계산함 → 백분위/z 기반 self-normalizing 트리거.
10. **보유 단위 위험분산 부재.** AUM 가중은 사이즈/유동성 tilt일 뿐, 공분산 인지 없음. → (결정) 순수 결정론 AUM 유지 vs NCO/공분산 인지 최적화를 메인 경로로 승격.

## 5. 건드리지 말 것 (재검증서 refuted / 방어가능)

- `_clamp_to_pool_capacity` under-investment — 전 14버킷 키가 풀에 남아 용량 38.0, 도달 불가. (refuted)
- "3 델타 합산이 상쇄/증폭" — 각 modifier가 self-funded net≈0, 라이브 net_raw_sum≈0. tilt도 작음(≤0.05). (refuted)
- NCO max-sharpe div-by-zero — 수학적으론 실재하나 dead code(라이브 caller 0). (refuted)
- manager가 baseline 숫자를 못 봐 "ungrounded" — risk_tilt가 ordinal enum이고 코드가 baseline-상대 산술 수행, regime 라벨은 macro_summary에 이미 있음. ordinal 설계는 건전. (오버리치)
- skip-1m momentum의 "tiny N" — 라이브 category는 10개·최소 7개(2-6 아님)이고 ranking이 배분에 미연결. (오버리치)

## 6. 권고 — rewrite 순서

**Phase 0 (rewrite 무관, 지금):** B1·B2·B3·B6 = 라이브 안정성 직결. dead 옵티마이저(nco/bl_views/enb)·거짓 docstring·미사용 force_method 정리 → 코드와 주장 일치.

**Phase 1 (근거화):** 캘리브레이션 하베스트를 14-bucket 앵커에 연결(매직넘버→파생값); regime rules-vote backstop; systemic_score 결정론 composite.

**Phase 2 (구조 결정):** ① 순수 결정론 AUM 철학을 정식 채택하고 옵티마이저 잔재 삭제, vs ② NCO/공분산 인지 최적화를 메인 경로로 승격. + risk taxonomy 단일화, 상관군집 cap을 보유 집합으로, 방어 오버레이 regime-aware화.

**Phase 3 (철학 점수 방어):** philosophy.md를 구조화 facts 블록 + 숫자 cross-check로 grounding; trade_plan 현금 잔여 행.

**운영(병행):** 7·8월 ≥10% 월간 회전율 floor — monthly_full을 cron화하거나 회전율 미달 시 escalate. (모의 HTS/MTS는 API 불가 → 체결 reconciliation은 수동 CSV.)

---

## 7. Phase 0 적용 내역 (브랜치 `rework/pipeline-methodology`, 2026-06-15)

> 결정: **버그 + dead code만**, 방법론 rewrite는 보류. Stage 3는 **결정론 AUM 철학 정식 채택**.
> 전체 테스트 1076 pass / 환경 한정 2 fail(`/tmp`, pykrx#21) — 신규 실패 0.

| 항목 | 적용 | 파일 |
|---|---|---|
| **B1** retry 카운터 | allocator 노드가 `allocation_attempts`를 실행마다 +1 → retry→fallback 정상 종료 | trader_allocator.py |
| **B3** reassess 크래시 | `weekly_tilt`가 디렉터리→`portfolio.json` 해석 + 부재 guard | weekly_tilt.py |
| **B6** fallback 자기도장 | normalizer·emergency가 `validate_concentration`+`correlation` 재검증 후 정직한 `validation_passed`; emergency 바스켓을 distinct 카테고리로 분산(≥6) | conditional_logic.py (+test) |
| **B2** 방어 오버레이 무력화 | no_trade_band 예외를 0.70 하드캡이 아닌 **실제 target risk**에 연동 → 0.55~0.70 구간 de-risking 실제 실행 | engine.py (+회귀테스트 2) |
| **B4** prev_target 공백 | daily run이 `daily_state.json`(realized weights+clusters) 지속, `_load_prev`/`_load_clusters`가 읽음 | daily_full.py |
| **B7** 뉴스 look-ahead | cutoff·recency 앵커를 `utcnow()`→**`as_of`(EOD)**, as_of 이후 항목 drop, 로컬 TZ 정합 | news_macro.py, ranker.py, macro_news_analyst.py (+회귀테스트) |
| **dead code** | `nco.py`·`bl_views.py`·`kr_residual_signals.py`·`conditional_stress.py` + 전용 테스트 3개 삭제, method_picker 참조 stale docstring 5건 정정 | (–1117 LOC) |

**보류(후속 권장):**
- **B5** VKOSPI 트리거 death — 대체 KRX 소스 부활은 라이브 검증 필요(오프라인 불가). market_risk sentinel 0.0→'n/a' 렌더링도 함께.
- **B8** philosophy.md 숫자 grounding(구조화 facts + 숫자 cross-check) — 70% 철학 점수 최대 레버리지지만 philosophy rewrite와 겹쳐 보류.
- **force_method** 필드는 inert로 문서화만(제거는 시그니처 blast radius로 보류).
