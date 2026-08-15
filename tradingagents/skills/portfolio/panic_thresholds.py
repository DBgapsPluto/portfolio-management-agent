"""F6 모멘텀 패닉 감쇠 — 단일 소스 임계 상수.

daily_triggers(presets/triggers_default.yaml)는 정규식 파서라 상수를 직접
import 할 수 없다(YAML 문자열에만 값이 존재). 여기 상수가 트레이더의
모멘텀 감쇠 조건과 YAML 트리거 조건의 단일 진실원(source of truth)이며,
test_panic_thresholds_match_trigger_yaml 이 드리프트를 막는다 — 값을 바꾸면
presets/triggers_default.yaml 의 vix_spike/vkospi_spike 조건도 함께 바꿔야 한다.
"""
from __future__ import annotations

VIX_PANIC: float = 30.0      # presets/triggers_default.yaml: "vix > 30 ..."
VKOSPI_PANIC: float = 25.0   # presets/triggers_default.yaml: "vkospi > 25"
