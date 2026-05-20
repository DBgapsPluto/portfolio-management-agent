"""Playbook calibration via historical backtest.

24-cell scenario framework의 cell별 optimal portfolio allocation을 historical
data로 검증/추정. hand-coded default를 empirical optimum으로 대체.

흐름:
  data.fetch_macro_quarterly + fetch_asset_returns_monthly
  → classify.assign_cells (각 분기를 (cycle, tail, kr) 좌표에 매핑)
  → optimize.fit_per_axis_grid (per-axis Sharpe maximization)
  → scripts/calibrate_playbooks.py → data/playbook_calibration.json
  → scenario_definitions.py auto-load.
"""
