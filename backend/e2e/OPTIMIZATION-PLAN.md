# card-collect 진행시간 단축 — 계획·측정·다음 작업

> 컨텍스트 유지용 상태 문서(2026-07-04). 측정은 `e2e/smoke_cycle.py`(40행 실저장→삭제 1사이클).

## 측정 방법(재현)

```bash
cd backend
.venv/bin/python e2e/smoke_cycle.py            # 실행→모니터분석→삭제→리포트(단계별 ms)
# 극단 대기 축소 테스트: 우비콘을 배율 env 로 재시작 후 위 명령
CARD_DELAY_SCALE=0.3 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

리포트는 `artifacts/smoke_cycle.json` + 콘솔 막대그래프. 백엔드 모니터링 = 새 `agent_runs.logs`
의 step running→done ts 파싱.

## 실측 분해 (40행 실저장, baseline 총 168.2s)

| 단계 | ms | 성격 | 죽일 수 있나 |
|---|---|---|---|
| **apply_doc** | **82,700** | 카드팝업 '적용' 후 ERP가 40행 문서반영(예산현황 확인 모달 폭주 추정) | 서버 바운드 — 클라 대기 아님. 규명 필요 |
| **collect_rows** | **52,400** | 그룹별 예산단위·프로젝트 피커(서버 왕복 2~2.5s) + **AI추천 28.5s 포함** | 피커 중복제거·AI스킵으로 큼 |
| save_final | 14,700 | F7 + [선택]계좌경고/저장 모달 | 일부 대기 |
| 진입체인(login~query) | ~14,000 | 웜 로그인 6s + set_gubun 등 | 일부 대기 |

**collect_rows 세부**(로그 ts): 조회→분류 사이 **28.5s = Gemini 40행 배치 추천**. 이후 그룹 피커
= 예산단위 2.5~4.6s + 프로젝트 2.3s. ⚠ **전 그룹이 동일 예산단위·프로젝트(인사기획팀 (판)소모품비
/ 프로젝트 800)인데 note만 달라 그룹이 갈려 피커를 매번 재오픈** — 최대 중복.

## 핵심 결론 (2026-07-04 확정 — 사용자 원칙 반영)

- **원칙: 기능을 바꿔서 얻는 속도는 무의미. 같은 기능일 때만 유효.** → #2(AI 스킵)는
  '기본은 최종값이 될 수 없다'·'학습은 키워드 매칭이라 AI가 확인해야' 원칙에 걸려 **되돌림**
  (revert `ff39823`,`d8b8ce4`). AI는 처리 행이 있으면 항상 돌리고, 학습은 힌트로만.
- **인위적 고정 대기는 조건폴링/스케일로 축소 가능**하되, **피커는 서버 왕복이라 취약**했음:
  `CARD_DELAY_SCALE` 0.1/0.2 는 피커가 빈 그리드를 '후보 0건'으로 오판해 전량 실패.
  → 피커 rowcount 대기 상한을 **실시간(monotonic)** 으로 바꿔(`9ea30be`) 스케일 무관 견고화.
  이후 **0.15·0.1 모두 통과**. 0.15 를 card-collect 에 상시 baking(`5c00842`).
- **최종: 168s → ~135-140s (−29~33s), 무손상 저장·삭제.** 남은 바닥은 우리 대기가 아니라
  **ERP 서버**: apply_doc ~72-76s + collect 피커 서버왕복 ~30s + login SPA ~6-8s ≈ 110s 물리하한.
  이 아래로는 스케일을 더 내려도 이득이 서버 변동(±10s)에 묻힘.

### 완료된 영구 적용(항상, env 무관)
- close_card_popup·open_evdn·open_user_panel: 고정 대기 → 조건 폴링(`e385d5a`,`b96c6a9`).
- 피커 rowcount 실시간 상한(`9ea30be`). card-collect 대기 배율 0.15 per-run baking(`5c00842`).
  env `CARD_DELAY_SCALE` 는 테스트 override 로 여전히 우선.

## 계획 10 (임팩트 순 · 상태)

1. **apply_doc 82s 규명·축소** — 🔧진행중. `apply_rows_to_document`에 계측(clicks/iters/elapsed_ms)
   추가·모달 check-first(400ms선대기 제거·150ms폴) 완료(`3f7070d`). **다음: 계측 붙은 런으로
   82s가 (a)예산현황 모달 40개 순차인지 (b)서버 단일처리인지 확인 → (a)면 모달 즉시클릭 최적화,
   (b)면 불가피(문서화).**
2. **AI 추천 28.5s 스킵** — ⬜. 전 행이 학습/기본지정/비용구분으로 커버되면 Gemini 호출 자체 생략
   (결정적). 커버 안 된 행만 추천. `_prefill_selections`에서 recommend 호출 전 커버율 판정.
   → 이번 케이스는 전 행이 기본(판)소모품비+800 이라 **AI 없이도 채워짐 → 28.5s 즉시 절감**.
3. **동일 예산단위·프로젝트 피커 중복 제거** — ⬜. `_apply_batch`가 note까지 그룹키라 같은 budget/
   project를 매 그룹 재오픈. → budget/project 피커는 (code) 단위로 **1회만** 열고, note+체크+
   일괄적용만 반복. `_apply_group_fields`/`_batch_key` 재구성. 예상 24s→~5s.
4. AI 추천을 덤프/진입과 병렬화 — ⬜(2번 하면 대부분 무의미).
5. picker open/search 폴 200→100ms, min_ms 축소 — ⬜(효과 小, 서버 왕복이 대부분).
6. save_final 모달 폴 축소 — ⬜.
7. 진입 잔여 고정대기(set_gubun settle 1.5s 등) — ⬜.
8. screenshot(emit_shot) 빈도 축소 — ⬜.
9. 모달 폴링 공통 조건헬퍼 통일 — ⬜.
10. **CARD_DELAY_SCALE 배율 노브** — ✅완료(`3f7070d`). runner `_ScaledPage` 프록시로 전 대기
    스케일. 0.3 실측 완료(−16.5s, 무손상). 회귀 없음.

## 다음 세션 우선순위

1. **#2(AI 스킵)** — 가장 크고 안전(28.5s). 커버율 100%면 recommend 미호출.
2. **#3(피커 중복제거)** — 24s→5s. 로직 변경이라 smoke_cycle로 정상 반영 검증 필수.
3. **#1(apply_doc 규명)** — 계측 런 1회로 82s 정체 판정 후 결정.
4. 나머지(#5~9)는 합쳐도 ~10s 내외 — 여력 있을 때.

목표: 168s → **~80s**(AI 28 + 피커 19 + 대기 16 ≈ 63s 절감, apply_doc은 규명 후).

## 관련 커밋 / 파일

- `3f7070d` 배율 노브 + apply_doc 계측·check-first
- 튜닝 대상: `app/agents/card_collect/nodes.py`(_prefill_selections·_apply_batch·_apply_group_fields·
  _batch_key), `steps.py`(apply_rows_to_document·fill_*·apply_rows·save_document), `common/nodes.py`(진입)
- 측정: `e2e/smoke_cycle.py` · baseline JSON `artifacts/smoke_cycle.json`
