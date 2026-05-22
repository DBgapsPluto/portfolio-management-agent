# Historical Anchor Catalog

Stage 3 (allocator) 평가용 역사적 기준점 모음. 각 anchor는 **사후적으로 광범위 합의가 있는 시점**의 입력 데이터 + 그 때 portfolio가 가졌어야 할 특성을 명시.

## 핵심 원칙

1. **사후 합의 ≠ 객관 진실** — 다만 단일 작성자의 직관보다 훨씬 robust한 ground truth proxy
2. **anchor마다 출처 명시** — 어떤 시장 참여자/문헌이 그 시점에 무엇이 옳다고 했는지
3. **여러 anchor에 분산** — 한두 anchor에 과적합하지 않게 cross-validation
4. **검증 가능한 명제** — "gold ≥ 5%", "위험자산 ≤ 50%" 같이 측정 가능한 조건

## 파일 구조

```
data/historical_anchors/
├── README.md                          # 이 파일
├── _schema.json                       # JSON Schema
├── 2023-10_overheating.json
├── 2024-03_goldilocks.json
├── 2024-08_yen_carry.json
├── 2024-11_kr_boom.json
└── 2025-04_tariff_shock.json
```

## 각 anchor의 의미적 구성

```jsonc
{
  "anchor_id": "2024-08_yen_carry",
  "as_of_date": "2024-08-15",
  "title": "엔 캐리 트레이드 청산 / 단기 systemic tail",
  "description": "2024-08-05 닛케이 -12% 폭락. VIX 65 spike. 단기 deleveraging 위기.",
  "consensus_reasoning": "...",       // 출처 포함
  "sources": ["Howard Marks memo Q3 2024", "Bridgewater All-Weather review", ...],

  // Stage 1 출력의 합의된 값
  "stage1": {
    "regime":    { "quadrant": "growth_disinflation", "confidence": 0.55 },
    "systemic":  { "score": 7.2, "regime": "risk_off" }
  },

  // Stage 2 출력의 합의된 값
  "stage2": {
    "dominant_cell": "A_T_F",
    "conviction":    "medium",
    "bucket_target": {
      "kr_equity":     0.10,
      "global_equity": 0.20,
      "fx_commodity":  0.20,
      "bond":          0.25,
      "cash_mmf":      0.25,
      "bond_tips_share": 0.30
    }
  },

  // Stage 3이 충족해야 할 사후 검증 조건
  "expected_stage3": {
    "acceptable_methods": ["min_variance", "risk_parity"],
    "min_sub_category_weights": {
      "us_treasury": 0.05,
      "kr_treasury": 0.03
    },
    "max_sub_category_weights": {
      "us_high_yield": 0.0,
      "em_bond":       0.02
    },
    "required_sub_categories": ["us_treasury", "mmf_kr"],
    "forbidden_sub_categories": ["us_high_yield"],
    "min_unique_sub_categories": 6,
    "max_single_weight":         0.20,
    "risk_asset_max":            0.50
  }
}
```

## anchor 검증 결과 해석

evaluator는 각 anchor에서 **여러 축의 통과/실패**를 보고:

| 축 | 통과 조건 |
|---|---|
| `method_ok` | Stage 3 선택 method ∈ acceptable_methods |
| `required_present` | 각 required_sub_category가 weight > 0인 ETF로 포함됨 |
| `forbidden_absent` | forbidden_sub_category 비중 = 0 |
| `min_weights_met` | 각 sub_category 합 ≥ min 임계 |
| `max_weights_met` | 각 sub_category 합 ≤ max 임계 |
| `diversity_ok` | unique sub_category 수 ≥ min |
| `risk_asset_ok` | 위험자산 합 ≤ risk_asset_max |

**단일 점수가 아니라 7축 보고서**. 어느 축에서 통과·실패했는지 명시 → 단일 metric의 함정 회피.

## 카탈로그 운영 원칙

- anchor 추가 시 PR review 형태로 합의 강화 (혼자 추가 X)
- 매년 1~2개씩 누적 (regime/cycle 다양화)
- anchor의 expected 값이 시간에 따라 안 바뀌어야 정상 (불변 사실 기반)
- anchor가 틀렸다고 판명되면 archive하되 삭제 X (이력 보존)
