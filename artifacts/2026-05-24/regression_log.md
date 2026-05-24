# PR2a Regression Log

매 commit 직후 본 파일 에 entry 추가:
- Commit ID + message
- Unit test result (passed/failed count)
- Integration test result (passed/failed count)
- Δ from previous commit (new fail or new pass)
- 0 new failure 확인

## Baseline (post PR1 merge 3572d03 / pre PR2a C0, 2026-05-24)

```
$ uv run pytest tests/unit/ -q
2 failed, 741 passed, 6 warnings in 79.70s

  FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
  FAILED tests/unit/skills/test_portfolio_attribution.py::test_select_etf_candidates_populates_attribution

$ uv run pytest tests/integration/ -q
18 failed, 26 passed, 2 warnings in 18.66s

  FAILED tests/integration/test_5_28_dry_run.py::test_5_28_dry_run_produces_artifacts
  FAILED tests/integration/test_eval_regime_classifier.py::test_regime_classifier_accuracy[…] × 8
  FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[…] × 8
  FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
```

Pre-existing fail: **2 unit + 18 integration** (post PR1 merge baseline).

NOTE: Plan 의 "3 unit failed" 예상치는 pre-PR1-merge 기준. PR1 merge (3572d03)
후 unit fail 이 3→2 로 감소. 본 baseline 이 PR2a 의 ground truth.

## Post-C0 (chore: execution safeguards) — commit 88621df

```
$ uv run pytest tests/unit/ -q
2 failed, 741 passed, 6 warnings in 74.42s

$ uv run pytest tests/integration/ -q
18 failed, 26 passed, 2 warnings in 16.64s
```

Δ from baseline: **0 new failure, 0 new pass**. Identical to baseline.

C0 의 모든 변경 (artifacts scaffolding + .gitignore 1줄) 은 production code
미수정 — regression 영향 없음 확인.

Status: PASS. C1 진행 가능.
