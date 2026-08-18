# DB GAPS 에이전트 — 사용자 준비물 체크리스트

- **작성일:** 2026-05-09
- **대상:** DB GAPS 자산배분 에이전트 v1 (5/28 dry-run + 6/1~8/31 운용)
- **참조 스펙:** `docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md`

본 문서는 사용자(팀)가 코드 구현 전·중·후로 직접 준비해야 하는 모든 항목을 카테고리별로 나열한다. 5/28 마감 자동컷 직전에 누락 발견 시 대회 참가 자체가 위험하므로 **체크리스트로 활용**.

---

## 1. API 키 (필수)

| 키 | 발급처 | 비용 | 발급 절차 | 용도 |
|---|---|---|---|---|
| `FRED_API_KEY` | https://fredaccount.stlouisfed.org/apikeys | 무료 | 이메일 가입 → API 키 신청 → 즉시 발급 | 미국 거시지표 (yield curve, CPI, 실업률, FED 자산) |
| `ECOS_API_KEY` | https://ecos.bok.or.kr → 인증키 신청 | 무료 | 한국은행 사이트 가입 → 인증키 신청 → 즉시 발급 | 한국 거시지표 (기준금리, M2, CPI, 수출입) |
| LLM Provider 키 | OpenAI / Anthropic / Google 중 1개 | 유료 (~$30~100 추정) | 이미 보유 가정 (TradingAgents v0.2.4 다중 provider 지원) | 모든 LLM 호출 |

### 선택 (있으면 좋음)

| 키 | 발급처 | 비용 | 용도 |
|---|---|---|---|
| `TRADINGECONOMICS_KEY` | https://tradingeconomics.com/api | 무료 tier 있음 | 캘린더 안정화 (없으면 RSS·공식 사이트로 대체) |
| `LANGSMITH_API_KEY` + `LANGSMITH_TRACING=true` + `LANGSMITH_PROJECT=db-gaps-agent` | https://smith.langchain.com/ | 무료 tier 충분 | 멀티 에이전트 run-tree 시각화·디버깅·토큰 사용량·latency 추적 |
| `ALPHAVANTAGE_KEY` | (기존 v0.2.4 사용) | 무료 | 폐기 예정. 일부 fallback에 활용 가능 |

---

## 2. 로컬 환경 설치

### Python 패키지 (`pyproject.toml`에 추가될 것)

```
pykrx              # KR ETF 가격·KRX 데이터
PyPortfolioOpt     # 포트폴리오 최적화 (HRP/RP/MinVar/BL)
pandas-ta          # 기술적 지표 (MA200, RSI, MACD, ATR) — pure Python, C 빌드 X
openpyxl           # xlsx 파싱 (universe sync)
python-docx        # 워드 보고서 생성 (philosophy.md → docx)
pyyaml             # preset YAML 로드
scikit-learn       # PCA, hierarchical clustering
yfinance           # VIX·breadth (이미 있음)
beautifulsoup4     # CNN F&G 스크래핑 (선택)
feedparser         # RSS (Yahoo·Reuters) 파싱
tenacity           # API 재시도 (FRED·ECOS·pykrx 일시 장애 대응)
langsmith          # 멀티 에이전트 트레이싱 (선택, LANGSMITH_TRACING=true)
```

### 시스템 패키지

이전 계획에서 TA-Lib C 라이브러리 설치가 필요했으나, **production hardening
revision으로 pandas-ta(pure Python)로 교체**되어 더 이상 시스템 패키지가
필요하지 않음. `pip install -e ".[test]"` 한 번으로 모든 의존성 설치 완료.

---

## 3. 환경 변수 (`.env`)

`/Users/kimjaewon/Pluto/TradingAgents/.env`에 다음을 둔다.

```env
# 외부 데이터 API
FRED_API_KEY=...
ECOS_API_KEY=...

# LLM provider (이미 있을 것 — 1개 이상)
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...

# 선택
TRADINGECONOMICS_KEY=...

# 디렉토리 (기본값 있음, 변경 안 해도 됨)
TRADINGAGENTS_CACHE_DIR=~/.tradingagents/cache
TRADINGAGENTS_RESULTS_DIR=~/.tradingagents/logs
GAPS_ARTIFACTS_DIR=./artifacts
```

---

## 4. 정적 입력 파일 (현재 상태)

| 파일 | 위치 | 상태 | 비고 |
|---|---|---|---|
| ETF 유니버스 xlsx | `docs/제12회 GAPS ETF 리스트 (2026-5-9 게시).xlsx` | ✅ 있음 | 대회 측에서 갱신 시 새 파일 받아 교체 후 `gaps universe sync` 재실행 |
| 대회 룰 마크다운 | `docs/DB_GAPS_Investment_Tournament_Rules.md` | ✅ 있음 | 변경 없을 것 |
| 사용자 수정 계획 메모 | `수정 계획.txt` | ✅ 있음 | 참고용 |

---

## 5. 운용 중 사용자가 수동 제공할 데이터

대회 시작(6/1) 이후 MTS에서 export해 `data/` 디렉토리에 둔다.

### 매월 말 (월간 보고서·회전율 계산)

| 파일 | 내용 | 형식 | 사용 명령 |
|---|---|---|---|
| `data/transactions_2026-06.csv` | 6월 전체 거래내역 (일자, 구분, 종목, 수량, 단가) | MTS export 그대로 또는 표준 형식 | `gaps monitor turnover --month 6`, `gaps report monthly --month 6` |
| `data/holdings_2026-06-30.csv` | 월말 보유 현황 (티커, 수량, 평가금액) | MTS export | `gaps monitor exposure`, `gaps monitor drift` |
| `data/pnl_2026-06.csv` | 6월 일별 자산 평가액 추이 | 일자, 평가액 | `gaps report monthly --actual data/pnl_2026-06.csv` |

### 회전율 계산 컬럼 요구사항

회전율 = `(매수금액 + 매도금액) / 평균자산 × 100`. 거래내역 CSV에 필수 컬럼:
- 거래일자
- 거래구분 (매수/매도)
- 거래금액 (수수료 포함 여부 명시)

대회 측 공식 회전율 계산이 수수료·세금 포함인지 미해결. **MTS export 형식 샘플을 한 번 봐서 정확한 필드 매핑**을 확정해야 한다.

### 일별 모니터링 (선택)

`gaps rebalance daily` 트리거 사용 시 일일 holdings export 권장.

| 파일 | 내용 | 형식 |
|---|---|---|
| `data/holdings_2026-06-15.csv` | 특정일 보유 현황 | MTS export |

---

## 6. 팀 합의 파라미터 (5/28 직전)

코드가 아니라 사람이 정하는 값들. `presets/db_gaps.yaml`에 박힌다.

| 파라미터 | 예시 값 | 영향 |
|---|---|---|
| 위험자산 목표 비중 출발점 (Bull/Bear 토론) | 50 / 60 / 70% | regime 판단 따라 토론에서 조정 |
| 단일 클러스터 합 cap | 12 / 15 / 20% | 단일 리스크 통제 강도 (대회 룰 단일 ETF 20%보다 엄격) |
| 후보 ETF 수 (자산군별) | bucket당 4~6개 | Allocator 후보풀 크기 |
| 기본 optimizer | HRP / Risk Parity | regime 무관 default |
| 회전율 초기 목표 | 80% (룰 최저) / 90% (여유) | 5/28 매매명세서 사이즈 |
| Daily 트리거 임계 (VIX·VKOSPI 등) | preset YAML 기본값 | 운용 중 알림 빈도 |
| 출력 언어 | 한국어 (philosophy 보고서) | 대회 §4의 한국어 보고서 의무 |

구현 시 합리적 기본값을 박고 팀 회의로 조정.

---

## 7. 계정·신원

| 항목 | 비고 |
|---|---|
| DB GAPS 대회 참가팀 등록 | 5/28 마감 가정. 등록 자체는 별도 절차. |
| 팀장 MTS 계정 | 매매·거래내역 export 권한 필수 |

---

## 8. 인프라 (선택)

### Daily cron

`gaps rebalance daily` 자동화 시 필요. 로컬 머신을 24h 켜두는 cron으로 충분 (장 마감 후 18:00 실행). 별도 서버·Conductor는 overkill.

### 백업

- `~/.tradingagents/cache/` (가격 캐시) 일일 백업 권장 — fallback의 last-known-good 소스
- `artifacts/` (산출물) git 또는 별도 백업

---

## 즉시 체크리스트

- [ ] FRED 계정 + API 키
- [ ] ECOS 계정 + API 키
- [ ] LLM provider 키 (이미 있으실 것)
- [ ] (선택) LangSmith 계정 + API 키 (디버깅·관측성에 강력 추천)
- [ ] MTS 거래내역 export 형식 샘플 1개 → 회전율 컬럼 매핑 확정
- [ ] 5/28 직전 팀 합의 파라미터 목록 회람·확정

---

## 참조 스펙 매핑

| 본 문서 섹션 | 스펙 §  |
|---|---|
| 1. API 키 | §14 환경 변수 |
| 2. 로컬 환경 | §16 마이그레이션 (1번 단계) |
| 5. 운용 중 입력 | §10.6 monitoring, §11.2 월간 패키지 |
| 6. 팀 합의 파라미터 | §4.2 preset YAML, §9.1 트리거 룰 |
