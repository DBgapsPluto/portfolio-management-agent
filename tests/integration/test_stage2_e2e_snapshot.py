"""Stage 2 e2e snapshot — stubbed out (C4 of 2026-05-22 factor model PR).

원본 test 는 24-cell `_blend_with_prior` / `_apply_hysteresis` / `_EMA_LAMBDA` /
`_HYSTERESIS_DELTA` / `scenario_mapper.map_probs_to_bucket` 에 의존했으나,
C4 에서 `research_manager.py` 가 factor-model pipeline 으로 전면 rewrite 되며
해당 symbol 들이 제거됨. C5 에서 24-cell schema 전체 제거 시 본 파일도 함께 삭제 예정.

대체 e2e cover: `tests/integration/test_stage2_factor_model_e2e.py`.
"""
import pytest

pytest.skip(
    "Obsolete 24-cell snapshot — replaced by tests/integration/"
    "test_stage2_factor_model_e2e.py. Slated for removal in C5.",
    allow_module_level=True,
)
