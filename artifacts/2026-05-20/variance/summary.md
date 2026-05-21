# Variance 측정 결과 (n=20, 2026-05-15 fixture, 2026-05-21 실행)

## Core metrics

| metric | 값 | 임계 (plan §3.1) |
|---|---|---|
| Dominant cycle flip rate | **0%** (20/20 모두 B) | > 5% → smoothing 필수 |
| Dominant cycle prob σ | 6.5pp (raw B marg σ) | > 5pp → β 재검토 |
| Bond weight σ | **0.3pp** | > 3pp → EMA/smoothing |
| FX_commodity weight σ | **0.2pp** | > 3pp → EMA/smoothing |
| Global_equity σ | 0.6pp | 참고용 |
| KR_equity σ | 0.6pp | 참고용 |
| Effective cycle B (post-sharpening) | **mean 99.2%, range [96.3, 100]** | β=2.38 sharpening 효과 |

## Raw cycle marginals (n=20)

| cycle | mean | std | range |
|---|---|---|---|
| A | 4.4% | 1.6 | [2.2, 9.0] |
| **B** | **83.2%** | **6.5** | **[72.0, 95.9]** |
| C | 6.5% | 4.2 | [0.4, 15.2] |
| D | 5.7% | 2.4 | [0.5, 9.0] |

## Interpretation

LLM stochasticity 가 **portfolio 수준에서 사실상 0** — 매주 portfolio 가 LLM noise 로 흔들린다는 가설은 본 measurement 로 기각.

원인 분석:
1. B-cycle dominance 가 raw 단계에서도 82% — 다른 cycle 로 flip 할 여지가 거의 없음.
2. β-sharpening (slope=3.0, p_dom=0.83 → β=2.59) 가 raw B 0.83 을 effective 0.99 로 압축 → 24-cell cross-effect 가 portfolio 에 도달하지 못함.
3. macro_quant anchoring 이 매우 강한 효과 (ablation 참조) — LLM 이 사실상 macro_summary 의 1:1 reformat 으로 수렴.

## C3 결정 (D1, D2, D3)

| 결정 | 값 | 근거 |
|---|---|---|
| **D1 β 옵션** | **A (β=1 고정)** | bond σ 0.3pp ≪ 3pp, flip 0% — sharpening 자체가 불필요. 현 β=2.38 sharpening 은 24-cell 의 cross-effect 를 통째로 짓누름. |
| **D2 EMA λ** | **1.0 (no smoothing)** | variance 가 0 에 가까움 — EMA 가 줄일 noise 없음. λ<1.0 추가는 magic number. 다만 *infrastructure* (state 통과) 는 구축, λ=1.0 default. |
| **D3 hysteresis** | **off** | flip 0% — hysteresis 가 trigger 될 일 없음. |

본 결정은 2026-05-15 fixture 한 시점의 측정. 추후 cycle transition 시점 (예: 2027 Q2 inflation peak) 에 variance 재측정 → λ 재평가 권장.
