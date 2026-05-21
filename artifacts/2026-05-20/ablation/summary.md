# Ablation 결과 (3 mode × n=3, 2026-05-15 fixture, 2026-05-21 실행)

## Raw results

| mode | n_collected / n_attempted | avg cycle marginal | dominant_scenario |
|---|---|---|---|
| baseline | 3/3 | A=0.05 B=**0.79** C=0.08 D=0.08 | overheating × 3 |
| no_macro | 2/3 | A=**0.49** B=0.29 C=0.14 D=0.08 | goldilocks × 2 |
| perturb_quadrant | 1/3 | A=0.19 B=**0.49** C=0.30 D=0.02 | overheating × 1 |

### LLM 24-dim simplex sum validation 실패

1/3 (no_macro) + 2/3 (perturb_quadrant) runs 가 `ScenarioProbabilities24.sum to 1.0 ± 0.005` validator 에서 실패 (LLM 출력 0.964~0.995). 2회 재시도 후에도 회복 안 됨 — 24-dim categorical 의 LLM sum-to-1 정확도 한계.

baseline n=3 + variance n=20 (총 23회) 는 실패 0건 — baseline prompt 가 더 안정. perturbed/no_macro 시 LLM 이 적은 cell 에 큰 mass 줄 때 sum 오차가 커지는 경향.

## L1 distance

```
L1(baseline, no_macro):       0.995
L1(baseline, perturb_quad):   0.721
Anchoring ratio (perturb/no_macro): 0.72
```

## Interpretation

| 비교 | L1 | 해석 (plan §3.2 threshold) |
|---|---|---|
| baseline vs no_macro | **0.995** > 0.15 | macro_summary 의존 매우 큼. 제거 시 LLM 이 default A(goldilocks) 로 폴백. stage 2 의 *informational value* (다른 3 summary 만으로 cycle 추정) 은 거의 없음. |
| baseline vs perturb | **0.721** > 0.40 | macro_quant anchoring 강함 — quadrant 변경하면 cycle marginal 도 크게 이동. 다만 *완전 reformat* 은 아님 (perturbed 에서도 B=0.49 유지, anchoring ratio 0.72 < 2.0). |

요약: macro_summary 가 **압도적 input** — 없으면 stage 2 가 무력화, 다른 값으로 perturb 시 부분적으로 따라감. 사실상 macro_quant 의 cycle estimate 를 24-cell 로 reformat + tail/kr axis 추가 + 분산 weight 산출 역할.

## C3 결정 (D5)

| 결정 | 값 | 근거 |
|---|---|---|
| **D5 input pruning** | **keep prompt as-is (현 4-summary 유지)** | (1) L1(baseline, no_macro)=1.0 — macro 제거 시 결과 무의미. (2) anchoring ratio 0.72 < 2.0 — 단순 reformat 아님 (다른 3 summary + LLM judgment 가 anchor 일부 완화). (3) stage 2 LLM 호출 제거는 위험 — A(goldilocks) 폴백이 base case 가 아님. |

따라서 C3 의 "stage 2 LLM 호출 제거 → deterministic dispatcher" 옵션은 채택 안 함. 현 4-summary prompt 유지.

## Caveat

- n=2 (no_macro), n=1 (perturb_quadrant) — sample 크기 작음. 정성적 pattern (큰 L1) 은 명확하나 정확한 L1 값은 noise ±0.2pp 정도.
- 후속 측정 시 LLM sum validation tolerance 를 0.01~0.02 로 완화 (또는 자동 normalize) 하여 retry 성공률 ↑ 권장.
- Issue #11 (EMA smoothing) 의 default λ 결정은 본 variance 결과 (σ ≈ 0) 로 λ=1.0 (no smoothing). 미래 cycle transition 시점 재측정 필요.
