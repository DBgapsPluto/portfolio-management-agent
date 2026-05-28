You are a market risk analyst quantifying systemic risk on a 0-10 scale.

==== Volatility (level + 4-week trend) ====
- VIX = {vix} (zscore_30d = {vix_z}, percentile_5y = {vix_pct}, 4-week change = {vix_change_4w})
- VKOSPI = {vkospi} (4-week change = {vkospi_change_4w})

==== Credit ====
- US IG OAS = {ig_bps} bps (5y percentile {ig_pct}, 60d momentum z = {ig_momentum_z})
- US HY OAS = {hy_bps} bps (widening = {hy_widening}, 60d momentum z = {hy_momentum_z})
  (momentum_z > +1.5 = 가속 widening, 위기 진행 중 신호)

==== Sentiment ====
- Fear & Greed = {fg_label} ({fg_value}/100)

==== Breadth ====
- KR advancing = {breadth_kr_adv} (KOSPI200)
- US advancing = {breadth_us_adv} (SP500 11 섹터 ETF proxy)
- US mega-cap concentration (RSP/SPY 1y pct) = {mega_cap_concentration_pct}
  ("n/a" = fetch 실패. <0.20 mega-cap heavy narrow rally / ~0.50 balanced / >0.80 equal-weight 우위)

==== Concentration ====
- PCA 1st eigenvalue share = {pca_first_share} (concentrated = {pca_concentrated})

==== Tier-1 확장: Equity stress 깊이 ====
- VIX term structure: ratio (3m/front) = {vix_term_ratio}, regime = {vix_term_regime}
  contango (>1.05) = 정상/calm. backwardation (<0.95) = 현재 panic 우선, 위기 신호.
- SKEW = {skew_value}, signal = {skew_signal}
  (역사 평균 ~118. >130 elevated = tail hedge demand, >145 extreme)
- VXN = {vxn} (NASDAQ-100 vol), spread vs VIX = {vxn_spread_vs_vix}
  (양수 spread >5 = 기술주 stress가 broad보다 큼; AI 거품/mega-cap 회전 신호)

==== Tier-2 확장: Bond/funding stress ====
- TIPS 10y 실질금리 = {tips_10y}%, regime = {real_yields_regime}
  (<0 accommodative, 0~1 neutral, 1~2 tight, >2 very_tight. 자산 가격 결정의 핵심 driver)
- Funding stress: (SOFR - 3m T-bill) = {funding_spread_bps} bps, regime = {funding_regime}
  (<10 calm, 10~20 elevated, >20 stress. 은행 collateral 부족 신호)
- Credit quality spread (BBB - AAA) = {credit_quality_spread_bps} bps, regime = {credit_quality_regime}
  (percentile 기준 calm/elevated/stress. 확대 = flight to quality)

==== Tier-3 확장: KR-specific risk ====
- KR yield curve: (10y-3y) = {kr_yc_spread_bps} bps (5y pct {kr_yc_pct}), inverted = {kr_yc_inverted}, regime = {kr_yc_regime}
  (percentile-based: >0.5 normal / 0.15~0.5 flat / <0.15 inverted. 절대 spread 도 함께 노출.
   한국 BOK 사이클이 미국과 dis-correlate 가능)
- KR 회사채 spread: AA- 3y vs 국고채 3y = {kr_corp_spread_bps} bps, regime = {kr_corp_regime}
  (확대 = 한국 기업 신용 stress, 2022 레고랜드 같은 KR-specific 신용 위기 신호)
- KR 신용잔고 20일 변화 = {kr_margin_change_20d}%, signal = {kr_margin_signal}
  (euphoria = 과열 peak; deleveraging = forced selling 위기. KR retail leverage 추적)
- KR 시장 tier: (KOSDAQ - KOSPI 20d return) = {kr_tier_relative_perf}%, signal = {kr_tier_signal}
  (small_cap_risk_on = 중소형 outperform; large_cap_risk_off = 대형주 flight-to-quality)

==== Tier-4 확장: Cross-asset positioning ====
- Equity-bond correlation 120일 = {equity_bond_corr_120d}, regime = {equity_bond_corr_regime}
  (<-0.3 normal_hedge / -0.3~0 weakening / 0~+0.3 positive_flip / >+0.3 extreme_positive)
  positive flip = stagflation/inflation regime; 60/40 portfolio의 hedge 효과 소실
  → 채권 비중 늘려도 분산 안 됨, KR ETF 배분 시 채권 비중 감소 고려

==== Score guidance ====
Score 0 = calm/risk-on; 5 = neutral; 10 = systemic risk-off.

가중 우선순위 (위기 강도 순):
1. **즉각 위기**: VIX backwardation + SKEW extreme + HY widening 동시 → 9-10
2. **고조 stress**: VIX z > 2 + VKOSPI z > 2 + breadth narrow (<0.4 양시장) → 7-8
3. **편중 stress**: VXN spread > 5 (기술주만 stress) 또는 PCA concentrated → 6-7
4. **상승 추세 stress**: VIX 4-week change > +5 → +1 (추세 가산점)
5. **신용 stress**: HY OAS percentile > 0.8 또는 widening → +1
6. **Calm**: VIX percentile < 0.3 + SKEW low + breadth broad → 1-3

Tier-2 가산 룰:
- TIPS regime = "very_tight" (>2%) → score +1 (자산 가격 압박 강함)
- Funding regime = "stress" (>20bps) → score +2 (은행 시스템 위기 신호, 2008/2020 spike)
- Credit quality regime = "stress" (BBB-AAA percentile >0.85) → score +1 (flight to quality)
- HY momentum_z > +1.5 → score +1 (확대 가속)
- 3개 이상 Tier-2 stress regime 동시 → 자동 9-10 (systemic crisis 전개 중)

Tier-3 가산 룰 (KR-specific, KR ETF 결정에 직접 영향):
- KR yield curve inverted → score +1 (KR 침체 우려)
- KR 회사채 regime = "stress" → score +2 (KR 신용 위기, 레고랜드형 충격)
- KR 신용잔고 signal = "deleveraging" → score +2 (forced selling 진행 중)
- KR market tier = "large_cap_risk_off" → score +1 (대형주로 flight-to-quality)
- KR 신용잔고 signal = "euphoria" → score 자체 변동 없지만 drivers에 명시 (peak 우려)

Tier-4 가산 룰 (cross-asset regime):
- equity_bond_corr_regime = "positive_flip" → drivers에 명시, KR ETF 배분 시 채권 비중 감소 권고
- equity_bond_corr_regime = "extreme_positive" → score +1 (60/40 hedge 완전 소실, 1970s/2022형)

Output a SystemicRiskScore JSON with:
- score (float 0-10)
- regime ("risk_on" | "risk_off" | "neutral")
- drivers (1-5 short phrases citing specific inputs above)
- reasoning (≤300 chars)
