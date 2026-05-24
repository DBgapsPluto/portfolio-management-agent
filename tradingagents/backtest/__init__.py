"""Playbook calibration via historical backtest.

Legacy (pre-C5) — 24-cell scenario framework의 cell별 optimal portfolio
allocation을 historical data로 검증/추정. C5 (2026-05-23) 에서 24-cell schema
제거됨에 따라 본 calibration pipeline 의 *downstream consumer* (scenario_mapper
+ scenario_definitions) 가 사라짐. data/playbook_calibration.json 은 더이상
runtime 에서 사용되지 않음. 본 모듈은 historical (cycle/tail) per-cell Sharpe
optimization 의 *데이터 파이프라인* 으로 보존 — 향후 factor calibration 작업의
참조 코드 / 데이터 source.
"""
