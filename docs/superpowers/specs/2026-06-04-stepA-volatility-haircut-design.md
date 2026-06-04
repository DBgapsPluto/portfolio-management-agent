# Step A 변동성 haircut 설계 (#1)

**작성일:** 2026-06-04
**상태:** 설계 확정 (구현 대기)
**관련 비판:** 심사평 — "유가가 전쟁으로 불안정한데 비중(8.9%)이 높다 / 현재 시황이 비중에 반영 안 됐다."

---

## 1. 배경 — 문제와 철학

2026-05-29 결과물의 유가(WTI원유선물) ~8.9%는 **버그가 아니다**: Step A 앵커 baseline(growth_inflation의 b8=0.09) + LLM이 유가를 인플레/지정학 헤지로 의도 보유(key_risks에 "지정학→유가 자극" 명시). 그러나 사용자 우려는 타당하다 — **고변동 단일 선물에 9%는 리스크 과다**.

"전쟁이니 유가 줄여라"(GPR 조건부)는 모델의 헤지 논리와 충돌한다. 대신 채택한 철학(사용자 승인):

> **변동성 기반 haircut** — "변동성이 큰 자산은 작게 들어라." 방향 베팅(alpha)이 아니라 **리스크 일관성** 강제. Step B의 "수익 베팅 아닌 리스크 일관성" 철학과 동일. 현재 실현변동성에 반응(유가 잠잠하면 덜 깎고, 불안정하면 더 깎음)하므로 "현재 시황 미반영" 비판도 해소.

데이터 가용: `state["technical_report"].factor_panel[ticker].realized_vol_60d`(종목별 60일 연율 실현변동성)가 Stage 1에서 이미 계산됨 → 신규 fetch 불필요.

---

## 2. 범위

**In scope:** Step A에서 LLM tilt 투영 직후 bucket_weights에 결정론적 변동성 haircut 적용 — 고변동 버킷 축소 → 저변동 버킷 재배분. attribution 기록.

**Out of scope:**
- 전면 risk-parity 재작성(앵커/LLM 구조 보존 — 한쪽 haircut만).
- 종목 선정(Step B)·종목내 배분 변경(없음).
- GPR/지정학 조건부 로직(철학적으로 배제).
- threshold/FLOOR 백테스트 튜닝(상수는 v1 시드, 확장).

---

## 3. 컴포넌트 — 순수 함수 (신규 `tradingagents/skills/portfolio/vol_haircut.py`)

```python
_VOL_HAIRCUT_FLOOR: float = 0.6      # 최대 40% haircut (버킷 완전 삭감 방지)
_VOL_HAIRCUT_MARGIN: float = 0.2     # ref 대비 20% 초과 시에만 haircut (노이즈 방지)
_MIN_VOL_REDISTRIB: float = 0.03     # 재배분 가중의 vol floor (cash 과집중 방지)


def bucket_volatility(
    pool: dict[str, list[str]],
    vol_of: dict[str, float | None],
    aum: dict[str, float],
) -> dict[str, float]:
    """버킷별 vol = 풀 ETF realized_vol_60d 의 AUM-가중 평균. vol 없는(None) 종목 skip.

    버킷에 유효 vol 종목이 0개면 결과에서 생략(haircut 대상 아님).
    """
    out: dict[str, float] = {}
    for b, tickers in pool.items():
        num = den = 0.0
        for t in tickers:
            v = vol_of.get(t)
            if v is None or v <= 0:
                continue
            a = max(aum.get(t, 0.0), 0.0)
            num += a * v
            den += a
        if den > 0:
            out[b] = num / den
    return out


def apply_vol_haircut(
    bucket_weights: dict[str, float],
    bucket_vol: dict[str, float],
    floor: float = _VOL_HAIRCUT_FLOOR,
    margin: float = _VOL_HAIRCUT_MARGIN,
) -> dict[str, float]:
    """한쪽(one-sided) 역변동성 haircut + 저변동 재배분. 합 보존.

    ref_vol = 현재 bucket_weights 로 가중한 평균 버킷 vol(= 포트폴리오 평균 vol, self-calibrating).
    vol > ref·(1+margin) 인 버킷만 factor = max(floor, thr/vol) 로 축소(thr=ref·(1+margin),
    임계에서 연속). freed = Σ 축소분 → 저변동(vol<ref) 버킷에 (현재비중 / max(vol, MIN)) 비례 배분.
    vol 데이터 없으면 무변경.
    """
    present = {b: bucket_vol[b] for b in bucket_weights if b in bucket_vol}
    wsum = sum(bucket_weights[b] for b in present)
    if not present or wsum <= 0:
        return dict(bucket_weights)

    ref = sum(bucket_weights[b] * present[b] for b in present) / wsum
    thr = ref * (1.0 + margin)

    out = dict(bucket_weights)
    freed = 0.0
    for b in present:
        if present[b] > thr:
            factor = max(floor, thr / present[b])
            new = out[b] * factor
            freed += out[b] - new
            out[b] = new
    if freed <= 1e-12:
        return out

    # 재배분 수혜: 저변동(vol<ref) 버킷, 가중 = 현재비중 / max(vol, MIN). 없으면 fallback.
    recips = {b: out[b] / max(present[b], _MIN_VOL_REDISTRIB)
              for b in present if present[b] < ref and out[b] > 0}
    base = sum(recips.values())
    if base <= 1e-12:
        recips = {b: out[b] for b in present if present[b] <= thr and out[b] > 0}
        base = sum(recips.values())
    if base <= 1e-12:
        return out   # 수혜처 없음 → freed 잔여(하류 renorm 처리)
    for b, wgt in recips.items():
        out[b] += freed * wgt / base
    return out
```

검증 직관(유가 vol~0.38, ref~0.18, thr~0.216): factor=max(0.6, 0.216/0.38)=0.6 → b8 9%→5.4%, freed 3.6% → 채권·현금(저vol) 재배분.

---

## 4. 데이터 흐름 — wiring (`trader_allocator.py`)

Step A에서 `bucket_weights = project_to_band(...)` **직후**, `_clamp_to_pool_capacity` **직전**에 삽입:

```python
from tradingagents.skills.portfolio.vol_haircut import bucket_volatility, apply_vol_haircut

# project_to_band 직후:
tr = state.get("technical_report")
fp = getattr(tr, "factor_panel", None) or {}
vol_of = {t: getattr(fp.get(t), "realized_vol_60d", None) for t in aum}
pool_tickers = {b: [e.ticker for e in pool.get(b, [])] for b in bucket_weights}
bucket_vol = bucket_volatility(pool_tickers, vol_of, aum)
bucket_weights = apply_vol_haircut(bucket_weights, bucket_vol)
bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)   # 기존
```

`allocation_attribution`에 투명성 기록:
```python
attribution["vol_haircut"] = {
    "ref_vol": <ref>, "bucket_vol": bucket_vol,
}
```
> ref/세부 factor는 `apply_vol_haircut`가 내부 계산하므로, attribution 단순화를 위해 `bucket_vol`만 기록(필요 시 ref도). 재배분 후 bucket_weights는 기존 `bucket_target`로 그대로 노출되어 변화가 드러난다.

---

## 5. 에러 처리

| 상황 | 동작 |
|---|---|
| `technical_report` 없음 / `factor_panel` 비어있음 | `vol_of` 전부 None → `bucket_vol` 빈 dict → `apply_vol_haircut` 무변경(no-op). |
| 일부 버킷만 vol 결측 | 해당 버킷은 haircut/재배분 대상에서 제외(present 미포함), 나머지는 정상. |
| 모든 vol 동일 | ref=vol → thr>vol → haircut 0 → 무변경. |
| 재배분 수혜처 없음 | freed 잔여 → 하류 renorm. |
| cash 등 vol≈0 | 재배분 가중에 `max(vol, _MIN_VOL_REDISTRIB)` floor로 과집중 방지. |

순수 함수, 예외 없음. 70% 리스크캡과 시너지(고변동=대개 위험자산 축소 → realized risk↓ → risk-repair 덜 binding).

---

## 6. 테스트

**단위 (`tests/unit/skills/portfolio/test_vol_haircut.py`):**
- `bucket_volatility`: AUM-가중 평균; None/0 vol skip; 유효 vol 0개 버킷 생략.
- `apply_vol_haircut`:
  - 고변동 버킷 축소 + FLOOR 준수(40% 초과 삭감 안 됨).
  - 저변동 버킷 무변경(factor=1).
  - freed가 저변동 버킷에 재배분 + **합 보존**.
  - vol 균일 → 무변경. bucket_vol 빈 dict → 무변경(no-op).
  - vol≈0 cash 과집중 방지(MIN floor).

**통합 (`tests/unit/agents/trader/test_trader_allocator.py`):**
- technical_report(factor_panel)에 b8 고vol 주입 → b8 bucket_target 비중이 haircut 없을 때보다 감소.
- technical_report 없음 → bucket_target 무변경(회귀 보장).

**E2E:** 2026-05-29 재실행 → 유가(b8) 비중 ~9% → ~5-6%로 감소, validation 통과, risk≤70% 유지.

---

## 7. 확장 항목 (v1 제외)
1. FLOOR/MARGIN/MIN 백테스트 튜닝.
2. ref_vol을 median 등 대안으로 robustness 비교.
3. 60d 외 다중 horizon(20d/60d) blend.
4. attribution에 per-bucket haircut factor 상세 노출(현재 bucket_vol만).
