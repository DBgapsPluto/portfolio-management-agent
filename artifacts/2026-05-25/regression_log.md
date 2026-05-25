# PR2b Regression Log

매 commit 직후 본 파일 에 entry 추가:
- Commit ID + message
- Unit test result (passed/failed count)
- Integration test result (passed/failed count)
- Δ from previous commit
- 0 new failure 검증

## Baseline (post PR2a merge / pre PR2b C0, 2026-05-25)

```
$ uv run python -m pytest tests/unit/ -q
2 failed, 787 passed, 7 warnings in 84.94s

$ uv run python -m pytest tests/integration/ -q
18 failed, 28 passed, 1 warning in 49.37s
```

Pre-existing fail (PR2a post-merge baseline):
- Unit: test_technical_analyst_returns_report, test_select_etf_candidates_populates_attribution
- Integration: test_eval_systemic_score (8 variants) + test_eval_regime_classifier (8 variants) + test_plan_pipeline_mock + test_5_28_dry_run

## Post-C0 (chore: scaffolding)
[fill at C0 commit time]
