# Stage 2 Mega-PR Execution Protocol

> **목적:** `2026-05-20-stage2-bottleneck-fix.md` plan 의 8시간+ 단일 세션 실행 시 환각 위험을 filesystem-based state 로 차단.

> **적용 범위:** Task 0 직후 C0 commit 으로 인프라 구축 → C1-C5 모든 task 에 의무 적용.

---

## 환각 실패 모드 (실제 위험)

| Failure mode | 메커니즘 | 결과 |
|---|---|---|
| Context decay | 8시간 누적, 시스템 prompt 압축 | C5 시점에 C1 결정 정확히 기억 못 함 |
| Phantom edit | "추가했지" 가정 — Read 로 검증 안 함 | merge 후에 edit 누락 발견 |
| Test pass 위조 | pytest 실행 없이 "PASS" 보고 또는 중간 FAIL 못 봄 | broken main |
| Background process 환각 | 결과 파일 도착 전 그럴듯한 숫자 생성 | 잘못된 근거로 결정 |
| Conditional decision 일관성 파괴 | "옵션 A 결정" 후 30분 뒤 옵션 B 코드 일부 섞임 | 결정과 코드 어긋남 |
| Spec drift | 미시 결정 누적, spec 미인용 | merged 후 spec 과 코드 불일치 발견 |

가드레일 없는 단일 세션 8시간 실행의 환각 누적 실패 확률 추정: ~50%. 아래 8 원칙 적용 시 5-10%.

---

## 8 원칙

### 1. Decision log 외부화

조건부 결정은 *결정 시점* 에 `artifacts/2026-05-20/decisions.md` 에 commit. 코딩 시점에 file Read.

**예시 (decisions.md):**
```markdown
# Stage 2 Execution Decisions (2026-05-20)

| 항목 | 결정 | 근거 | 시각 | commit |
|---|---|---|---|---|
| β 옵션 | A (β=1 고정) | variance bond σ = 4.2pp ≤ 3pp 미달 | 14:50 | <hash> |
| EMA λ | 0.4 | flip rate 12% > 5% → smoothing 필수 | 14:50 | <hash> |
| Hysteresis | off | EMA λ=0.4 만으로 σ 충분히 감소 | 14:50 | <hash> |
| Method picker overheating | HRP | equity tilt + 분산, goldilocks 와 동등 | 13:00 | <hash> |
| C5 narrative | 추가 | diff 작고 명확한 개선 | 18:00 | <hash> |
```

### 2. Verify-before-act

매 task 시작 첫 단계:
```bash
git status --short
git log --oneline -5
```
파일 변경 전 해당 파일 Read. 이미 본 파일도 commit 후 한 번 더 Read 권장 (특히 4+ commit 진행 후).

### 3. Test pass 의무 인용

✅ 옳은 보고:
```
$ pytest tests/unit/skills/test_research_scenario_mapper.py -v
...
======= 18 passed in 0.45s =======
```

❌ 잘못된 보고: "모든 test pass"

명령 실행 안 했으면 "검증 안 됨" 명시.

### 4. Background process status

`artifacts/2026-05-20/job_status.json`:
```json
{
  "variance_n20": {
    "pid": 1234,
    "started_at": "2026-05-20T13:30:00",
    "expected_done_at": "2026-05-20T14:50:00",
    "out_path": "artifacts/2026-05-20/variance/n20_run.json",
    "log_path": "artifacts/2026-05-20/variance/n20_run.log",
    "status": "running"
  },
  "ablation_baseline": {...}
}
```

결과 인용 *전* 의무:
```bash
ls -la artifacts/2026-05-20/variance/n20_run.json
tail -5 artifacts/2026-05-20/variance/n20_run.log
```
파일 없거나 log 가 미완이면 인용 금지.

### 5. Conditional decision 두 단계 분리

❌ 1-step:
> "variance bond σ 4.2 보이니 옵션 A 의 코드 작성"

✅ 2-step + commit boundary:
- **Step A**: variance JSON Read → `decisions.md` 갱신 → `git commit decisions.md`
- **Step B**: 새 task — `decisions.md` Read → 옵션 A 코드 작성

두 단계 commit 분리. trace 상 양쪽 검증 가능.

### 6. Cross-commit boundary 회귀

각 commit (C1-C5) 직후 의무:
```bash
pytest tests/unit/ -q --timeout=30 2>&1 | tail -3
pytest tests/integration/ -q --timeout=120 2>&1 | tail -3
```

출력의 마지막 3줄 commit body 또는 `artifacts/2026-05-20/regression_log.md` 에 보관:
```markdown
## Post-C1 regression
- unit: ===== 463 passed, 2 skipped in 12.34s =====
- integration: ===== 24 passed in 45.67s =====
```

### 7. Subagent 제한적 활용

✅ 허용:
- Explore subagent 로 "이 commit 의 diff 가 spec §2 C3 에 부합?" read-only 검증
- 잘 분리된 boilerplate (예: scripts/regress_stage2_baselines.py 의 OLS 보일러플레이트)

❌ 금지:
- β 옵션 A/B/C 결정 위임
- variance/ablation 결과 해석 위임
- cross-commit 일관성 검증 (예: overheating method 가 method_picker 와 method_choice 모두 일관?)

### 8. Spec 인용 line 번호

코드 주석에 chain 추적:
```python
# C3 Issue #5 처방 (spec §2 C3 line 134, decisions.md L4).
# variance n=20 bond σ = 4.2pp ≤ 3pp 미달 → 옵션 A (β=1 고정).
_BETA_FIXED = 1.0
```

나중에 "왜 β=1?" 의문 시 spec line → decisions.md → variance JSON chain 추적 가능.

---

## C0 commit 산출물

본 protocol 을 enforce 하기 위해 `artifacts/2026-05-20/` 디렉토리에 다음 placeholder 생성:

1. **`decisions.md`** — 빈 결정 표 (위 §1 형식)
2. **`job_status.json`** — `{}`
3. **`regression_log.md`** — 빈 헤더 + post-C0 baseline
4. **`docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md`** — 본 문서

`regression_log.md` 의 baseline:
```markdown
# Stage 2 Mega-PR Regression Log (2026-05-20)

## Post-C0 baseline (pre-changes)
$ pytest tests/unit/ -q --timeout=30 2>&1 | tail -3
<...>

$ pytest tests/integration/ -q --timeout=120 2>&1 | tail -3
<...>
```

이 baseline 이 C5 종료 시점에도 0 regression (skip 제외) 유지되어야.

---

## Task 별 enforcement checklist

각 task 시작 시 확인:
- [ ] `git status --short` 실행
- [ ] 변경할 파일 Read (혹은 직전 task 출력으로 충분?)
- [ ] decisions.md 의존 결정 있다면 Read

각 task 종료 시 확인:
- [ ] 변경 파일 diff 검토
- [ ] 관련 test 실행 + raw output 인용
- [ ] commit boundary 인 경우 회귀 + regression_log.md 갱신

---

## 사용자 보고 형식

각 commit 종료 시 user-facing report:
```
## C{N} 완료 (commit: <hash>)

변경:
- {file}: {1줄 요약}

테스트:
$ pytest <command>
<last 3 lines>

결정 (있을 시):
- {decisions.md L?}: {요약}

다음: C{N+1} ({이름})
```

이 형식이 사용자가 환각/실패를 즉시 catch 할 수 있게 함.
