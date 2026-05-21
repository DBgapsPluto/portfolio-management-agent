# Stage 2 Mega-PR Execution Decisions (2026-05-20)

> 조건부 결정의 외부 state. 모든 C1-C5 코드 변경은 본 표에 결정이 등록된 후에만
> 진행. 코딩 시점에 본 파일 Read 해서 인용. spec line 번호로 chain 추적.

| # | 항목 | 결정 | 근거 | 시각 | commit |
|---|---|---|---|---|---|
| D1 | β 옵션 (Issue #5) | _pending_ | variance n=20 결과 필요 | — | — |
| D2 | EMA λ (Issue #11) | _pending_ | flip rate + bond σ 필요 | — | — |
| D3 | Hysteresis on/off | _pending_ | flip rate 측정 후 | — | — |
| D4 | Method picker overheating | HRP | equity tilt + 분산. goldilocks 와 동등 처방. (spec §2 C1) | 2026-05-20T(C0) | _C1_ |
| D5 | C3 input pruning | _pending_ | ablation anchoring ratio 결과 | — | — |
| D6 | C5 philosophy.md narrative | _pending_ | stage2_diff.md 본 후 결정 | — | — |
| D7 | C4 KR β/α 회귀 fallback | _pending_ | KR 분기 data 보유 여부 | — | — |

## 사용 규칙

1. C2 결과 회수 직후 D1-D3, D5 결정 → 본 표 갱신 → commit (`chore(stage2): decisions update from variance + ablation`)
2. 코드 작성 시 본 파일 Read → 결정 row 인용 → 그 결정에 부합하는 코드만 작성
3. 결정 변경 필요 시 *새 row 추가* (덮어쓰지 말 것 — chain 추적용)
