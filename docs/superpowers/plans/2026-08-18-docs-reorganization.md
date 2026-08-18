# Docs Reorganization Implementation Plan — rev2

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. 절차 = 구현 → 스펙 리뷰 → 품질 리뷰.
>
> **rev2 (2026-08-18):** top-리포 관행 리서치 2건(일반 관행 + 퀀트/에이전트 도메인, ~25개 리포 실측) 반영. 사용자 재결정: ① 역사 문서 85편 = **트리에서 제거 + git 태그**(`docs/archive/` 폐기 — 선례 0 확인) + `LIMITATIONS.md` 증류 ② README = **영어 본문 + README-ko** (toss/es-toolkit 패턴). rev1의 배너 태스크는 폐기.

**Goal:** 문서를 star-지향 top-리포 관행(실측 검증)에 맞춰 재편: 현행 진실만 메인 트리에, 역사는 git 태그로, README는 영어 차별화-선도형으로 전면 재작성.

**근거 요약 (리서치 실측):** archive 무덤 선례 0 / PEP 1 "리비전 히스토리가 역사 기록" / 정직한-한계 문서는 자산(nautilus Soundness Pledge, ml4t what-this-is.md) / README 골격 = 로고→배지 3-5→한줄 피치→비주얼 1→Why→Quickstart→아키텍처 다이어그램 1→정직한 상태, 150-300줄 / 포크 모델 = TradingAgents-CN(31.2k★): 차별점 선도 + 헌정 섹션 + 업스트림 BibTeX / 성과 수치 없음 + 투자조언 아님·LLM 변동성 이중 헤지 / 한국어 전용 ~1.5k★ 천장.

---

## WP-1: 트리 재편 (T1–T4)

### T1: git 태그 + 현행 문서 이동 + 역사 문서 제거

- [ ] T1-0: **태그 먼저** — `git tag docs-archive-2026-08 HEAD` (제거 직전 상태 보존; README·ROADMAP에서 이 태그를 역사 접근 경로로 안내)
- [ ] T1-1: 현행 문서 git mv (kebab-case ASCII 개명):
  - `docs/rebalancing-method.md` → `docs/methodology/rebalancing.md`
  - `docs/stage5. mandate_validator.md` → `docs/methodology/mandate-validation.md`
  - `docs/stage1. macro_quant.md` 외 stage1 3편 → `docs/stages/stage1-*.md`
  - `docs/stage6. portfolio_manager.md` → `docs/stages/stage6-portfolio-manager.md`
  - `docs/pipeline-audit-2026-06-15.md` → `docs/audits/`
  - `docs/db-gaps-prerequisites.md` → `docs/setup/prerequisites.md`
  - specs 13편 → `docs/design/`: 06-02 병합, 06-03 quadrant-anchor, 06-04 5편, 06-07 rebalancing-engine, 06-09 2편, 06-16 etf-selection-hybrid, 06-20 bl-allocator, 06-23 confidence-scaled-prior
- [ ] T1-2: **역사 문서 git rm** — 나머지 `docs/superpowers/` 전량(specs 26 + plans 53; 본 플랜 파일은 실행 완료 후 마지막 커밋에서 제거), `docs/stage2. research.md`, `stage3. allocator.md`, `stage3-implementation-summary.md`, `stage4. risk_overlay.md`, `stage{1,2,3,4}_audit.md`, `stage5_6_audit.md`, `followup_issues.md`, `architecture-review-2026-05-24.md`, `db-gaps-test-plan.md`, `2026-05-28-pr2a-*.md`, `Factor_Model_Gemini_DeepResearch`, `수정 계획.txt`
- [ ] T1-3: 남은 문서 내 상호링크 전수 갱신 (제거 대상을 가리키던 링크는 태그 안내 각주 또는 삭제)
- [ ] T1-4: 커밋 `docs: current-truth tree — history preserved at tag docs-archive-2026-08`

### T2: LIMITATIONS.md (역사 85편의 증류 — 차별화 자산)

- [ ] T2-1: 루트 `LIMITATIONS.md` (영어) — 소스는 기존 감사 문서만(창작 금지): ① what-this-does-NOT-promise (백테스트≠실주문, 체결·비용 단순화, 3개월 대회 표본) ② 방법론 정직 공시(비-canonical BL 명명, δ·τ inert, prior-Σ 선택, 액티브셰어 25% 실체, c 상한 ~0.80, Σ 주간·KRW 창 선언) ③ 실증 한계(followup #31: "edge는 factor-timing이 아니라 철학·리스크 규율" 인용, 침체 표본 1개) ④ 알려진 미해결(roadmap 링크)
- [ ] T2-2: 커밋

### T3: 유지 문서 위생

- [ ] T3-1: `setup/prerequisites.md` 개인 경로 스크럽 · `design/` 13편 stale 헤더→"구현 완료(커밋 범위)" · stages/stage1 문서의 "Stage 4로 전달" 류에 제거 각주 · 깨진 참조 수정
- [ ] T3-2: 커밋

### T4: 대회 자료 대체 (rev1과 동일)

- [ ] T4-1: `docs/competition-rules-summary.md` 자체 요약(수치·공식·코드 상수 대응표, 원문 인용 금지) — 한국어 유지
- [ ] T4-2: 원본 3개 git rm (규칙 md + xlsx 2)
- [ ] T4-3: 코드 접점 문구 갱신 — `gaps_buckets.py` docstring, universe sync 안내 메시지, `turnover_check.py` 인용 경로
- [ ] T4-4: 커밋 + `pytest tests/ -q -m "not eval and not network"` 무해 확인

## WP-2: 정면 문서 (T5–T7)

### T5: README 전면 재작성 (영어) + README-ko + 아키텍처 다이어그램

- [ ] T5-1: `assets/architecture.svg` 자체 제작 — README용 단일 다이어그램(파이프라인: 4 analysts → research → BL allocator(confidence prior→views→MQU) → repair → validator → 3 outputs; 라이트/다크 모두 가독, currentColor 불가한 GitHub 렌더 특성상 중립 회색+포인트 1색). 업스트림 브랜딩 이미지 전량 git rm (`assets/TauricResearch.png`, `wechat.png`, `analyst.png`, `researcher.png`, `risk.png`, `trader.png`, `schema.png`, `assets/cli/` 4편)
- [ ] T5-2: `README.md` (영어, 150–300줄, 리서치 골격 준수):
  로고 없이 타이틀+한줄 피치("Multi-agent asset-allocation system for Korean ETFs — Black-Litterman engine with LLM relative views, deterministic mandate enforcement") → 배지 3-4(license, python, tests-local 표기, ko-readme 링크) → **차별점 문단**(vs upstream: Korean ETF universe, KRW-numeraire weekly Σ, confidence-scaled BL prior, deterministic compliance & repair) → architecture.svg → Why(대회 배경 1문단 + 철학 70% 채점이 낳은 설계) → Quickstart(설치→키→`gaps plan` 3단계) → Features(불릿) → How it works(단계별 2-3줄씩, 수식 금지, methodology/ 링크) → **Project status**(정직: 대회 기간 운용된 리서치 코드, 유지보수 범위) → Docs 안내(docs/는 한국어임을 명시) → **Limitations 링크** → **Acknowledgements**(TauricResearch/TradingAgents 헌정 문단 + 업스트림 BibTeX 유지) → **Disclaimer**(투자조언 아님 + LLM 변동성) → License
  **금지**: 성과 수치, 삭제된 스택(NCO/HRP/ENB) 언급, "canonical BL" 주장(→ "regime-conditional reference portfolio + BL view engine")
- [ ] T5-3: `README-ko_kr.md` — 영어판 충실 번역(현 한국어 README의 정확한 부분 재활용 가능하나 §3 구스택 서술은 폐기), 양쪽 상단에 상호 언어 링크
- [ ] T5-4: 커밋

### T6: ROADMAP·CHANGELOG·버전

- [ ] T6-1: 루트 `ROADMAP.md`(영어) — 다이얼 ON 전환(+daily x12), Phase D 구경로 삭제, decide-tier 방법론 항목, 리팩터 목록, MTD 케이던스. `TODOS.md` git rm
- [ ] T6-2: CHANGELOG `[0.4.0] - 2026-08-18` (6월 BL 재작업 + 8월 F1–F6 + docs 재편) · 버전 통일 0.4.0 (`pyproject.toml` name/description 현 정체성으로, `cli/main.py`)
- [ ] T6-3: 커밋

### T7: 검증

- [ ] T7-1: 링크 체커(전 md 상대 링크 + 이미지 경로) → 깨진 링크 0
- [ ] T7-2: `grep -rn "NCO\|HRP\|method_picker\|bl_views\|ENB" README.md README-ko_kr.md docs/` → 0 (LIMITATIONS의 의도적 언급 제외)
- [ ] T7-3: 전체 스위트 무해 확인 · README 주장-코드 대조는 품질 리뷰 필수 항목
- [ ] T7-4: 본 플랜 파일 git rm (역사 완결 — 태그에 보존됨)

## 리스크
| 리스크 | 완화 |
|---|---|
| 태그가 push 안 되면 역사 접근 불가 | 마무리 보고에 `git push origin docs-archive-2026-08` 명시 |
| 영어 README의 사실 오류 | 소스를 검증된 세션 산출물(파이프라인 문서·감사)로 한정, 품질 리뷰 주장-코드 대조 |
| universe sync xlsx 부재 | T4-3 안내 + universe.json 동봉 유지 |
| SVG가 GitHub 다크모드에서 깨짐 | 중립 팔레트 단일 테마로 제작(양쪽 가독) |
