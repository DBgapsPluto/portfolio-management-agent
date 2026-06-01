"""Historical Stage 1 reconstruction for factor model β calibration (PR2a).

Sub-modules:
- fetcher_fred: FRED latest-vintage thin wrapper + parquet cache
- fetcher_alfred: ALFRED vintage-aware fetch (7 revising series) — Critical 1
- fetcher_yfinance: yfinance daily Close + parquet cache
- fetcher_pykrx: pykrx KR market data + parquet cache
- aggregate: daily/monthly → quarterly indicator panel + derived
- stage1_builder: date-parameterized minimal-proxy Stage 1 builder
- bucket_returns_8b: KRW basis 8-bucket quarterly returns

본 패키지는 PR1 의 production code (factor_estimators, factor_calibration)
를 그대로 호출. 단 factor_estimators 는 mode='historical' 로 호출.
"""
