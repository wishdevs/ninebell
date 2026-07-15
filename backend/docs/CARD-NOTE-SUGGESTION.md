# 법인카드 적요 추천 (계정 인지 적요)

카드 개입(HITL) 그리드에서 각 거래의 **적요**(비용 설명 문구)를 자동 추천하는 체계.
핵심 규칙: **적요는 (가맹점 × 예산계정) 조합으로 결정된다.** 같은 가맹점이라도 사람이 예산단위(=계정)를
바꾸면 그 계정에 맞는 적요로 실시간 재추천한다.

> 예: 네이버파이낸셜은 통계상 '해외출장 교통비'가 압도적이지만, 이 건이 '회의비'일 수도 있다.
> 사람이 예산단위를 회의비로 바꾸면 적요도 그 계정에 맞게 바뀌어야 한다.

---

## 1. 맥락 2개 — 배지가 달라지는 이유

적요가 **언제 채워지느냐**에 따라 경로가 둘이고, 화면 배지도 그에 따라 다르다.

| 맥락 | 언제 | AI | 사다리 |
|---|---|---|---|
| **① 초기 자동 프리필** | 카드 수집 시 배치로 자동 채움 | ❌ | learned → seed → category → heuristic |
| **② 실시간 재추천** | 사람이 개입 화면에서 **예산단위를 바꿀 때** | ✅ | learned → seed → **AI** → category → heuristic |

- ① 은 `card_collect` 노드(`collect.py`)가 배치로 태운다. **`allow_ai=False`** — 배치는 결정적 tier만(빠르고 저비용).
- ② 는 프론트 `LiveGridCard` onChange → `GET /me/note-suggest`(**`allow_ai=True`**). 사람이 트리거하는 경로만 AI opt-in.

---

## 2. 추천 tier (우선순위 순 — 첫 히트에서 반환)

리졸버: `app/services/card_learning.py :: suggest_note()`

| # | source | 뜻 | 매칭 키 | 저장소 |
|---|---|---|---|---|
| 1 | **learned** | 과거 **내가** 이 가맹점×계정에 확정한 적요 | (user_id, 가맹점, 계정) | `card_learned_notes` (개인) |
| 2 | **seed** | 3년치 **전사** 카드실적의 이 가맹점×계정 관례 | (가맹점, 계정) | `card_seed_notes` (전사) |
| 3 | **ai** | 위 둘 다 없는 **미학습 조합**을 (계정이름+가맹점)으로 Gemini 생성 | (가맹점, 계정) | `card_ai_notes` 캐시 (전사공유) |
| 4 | **category** | 그 **계정**의 전사 최빈 적요 (가맹점 무관) | (계정) | `card_seed_notes` GROUP BY |
| 5 | **heuristic** | 가맹점명 **키워드** 매칭 | (가맹점명) | `nodes/_shared.recommend_note` |
| 6 | **null** | 아무것도 못 찾음 | — | — |

**핵심:** AI는 3번 자리뿐이고, learned/seed(실이력)가 있으면 거기서 끊겨 **AI를 안 탄다.**

### AI tier 세부 (source `ai`)
- **게이트:** `allow_ai=True` **그리고** 계정 이름(`acct_name`)이 있을 때만 발화. 엔드포인트만 opt-in.
- **캐시 우선:** `card_ai_notes`에 (가맹점×계정)이 있으면 LLM 재호출 없이 즉시 반환.
- **생성:** 없으면 Gemini(`gemini-3.5-flash`, `thinking_budget=0`)로 계정 맞춤 적요 1줄 생성 → 캐시 저장(전사 공유).
- **폴백:** 키 없음/타임아웃/오류/빈 응답이면 조용히 category·heuristic으로 폴백(응답을 죽이지 않음).

---

## 3. 화면 배지

`SOURCE_META` in `src/components/live/LiveGridCard.tsx`

| 배지 | 색 | 뜨는 맥락 | resolver source |
|---|---|---|---|
| **학습** | 초록 | 초기 프리필 | learned |
| **전사** | 파랑 | 초기 프리필 | seed |
| **AI** | 강조색 | 실시간 재추천(미학습) | ai |
| **추천** | 노랑 | 실시간 재추천(AI 아닌 결정적) | learned·seed·category·heuristic |
| **기본** | 회색 | 즐겨찾기 기본지정 | default |

> **주의 1 (맥락 의존):** 실시간 재추천 경로에선 seed가 나와도 배지는 `전사`가 아니라 `추천`(노랑)으로 뜬다 —
> onChange가 `source === 'ai' ? 'ai' : 'lookup'` 으로만 구분하기 때문(`학습`/`전사`는 초기 프리필에서만).
>
> **주의 2 (배지 폴백):** 초기 프리필에서 tier가 `category`/`heuristic`이면, 프론트 `PrefillSource` 타입에 그 값이
> 없어 **`기본`(회색)으로 폴백**돼 뜬다(오해 소지). 필요 시 전용 배지 추가 또는 `추천`으로 매핑 검토.

---

## 4. 코드 체계 불일치와 시드 재키잉 (중요)

옛 기초자료(.xls)는 **5자리 계정과목 코드**(예: `51103` 복리후생비-석식), 현 ERP/프론트는 **9자리
`bgacctCd`**(예: `511003600`)를 쓴다 — **코드 체계가 달라 겹치지 않는다**(정상. 옛 기록 vs 현 ERP).
프론트는 9자리로 조회하므로, 시드를 9자리로 맞춰야 seed tier가 실제로 매칭된다.

- **재키잉:** `app/services/card_seed_remap.py :: remap_seed_notes_to_catalog()` — 시드의 안정 앵커인
  **계정 이름 + 제/판(코드 선두 5=제조·8=판관)**으로 현 카탈로그(`erp_code_catalog`, budget_unit)의 9자리
  `bgacctCd`에 재키잉. (측정: 1,470조합 중 91% 유니크 매핑, 나머지 총괄계정은 AI/category가 커버)
- **자동 재정렬:** budget_unit 카탈로그 동기화(`code_sync._sync_budget_units`) 완료 후 자동 호출 —
  ERP 코드가 또 바뀌어도 이름 기준으로 다시 정렬. 멱등.
- **수동 실행:** `python -m scripts.remap_seed_notes` (backend/ 에서).

이 재키잉이 **seed를 살려 AI 호출을 최소화**한다(과거엔 seed가 죽어 거의 모든 계정변경이 AI/heuristic으로 떨어짐).

---

## 5. 예시 (네이버파이낸셜)

| 예산단위(계정) | 결과 | source | 비고 |
|---|---|---|---|
| 해외출장비 (이력 많음) | 해외출장 숙박비(법인카드)-판매 | seed | 즉시·무료 |
| 회의비 (카드이력 없음) | 회의비(법인카드) | ai | 생성 후 캐시, 이후 즉시 |
| 도서구입비 (이력 없음) | 도서 구입비(법인카드) | ai | 계정마다 맞춤 |
| 이미 seed 있는 계정 | (그 관례) | seed | AI 안 탐 |

---

## 6. 관련 파일

| 역할 | 파일 |
|---|---|
| 리졸버 사다리 | `app/services/card_learning.py` (`suggest_note`, `_ai_note_*`) |
| 시드 재키잉 | `app/services/card_seed_remap.py`, `scripts/remap_seed_notes.py` |
| 카탈로그 동기화 훅 | `app/services/code_sync.py` (`_sync_budget_units`) |
| 단발 Gemini 호출 | `app/agents/common/gemini.py` (`gemini_generate_text`) |
| 엔드포인트 | `app/routers/me_codes.py` (`GET /me/note-suggest`) |
| 초기 프리필(배치) | `app/agents/card_collect/nodes/collect.py` |
| 데이터 모델 | `app/models/{card_learned_note,card_seed_note,card_ai_note}.py` |
| 마이그레이션 | `alembic/versions/{0019_card_account_notes,0020_card_ai_note}.py` |
| 프론트(실시간 재추천·배지) | `src/components/live/LiveGridCard.tsx`, `src/lib/api/me-codes.ts` |
| 테스트 | `tests/{test_card_note_suggest,test_card_seed_remap,test_card_account_notes}.py` |
