# 단계 1 — Playwright codegen 녹화 운용

새 화면 자동화의 **입력**은 텍스트 플로우와 녹화 두 가지다. 텍스트가 *왜/무엇을*, 녹화가
*어디를 어떻게*를 준다. 이 문서는 녹화를 받아 PROCESS.md 초안까지 가는 방법과, 녹화가
**못 잡는 것**(그래서 여전히 프로브가 필요한 것)을 규정한다.

근거: 2026-08-07 전자결재 취소 e2e — 리포에 실측이 0이던 EAP(React) 화면을 녹화 한 번으로
메뉴 id·버튼·확인 다이얼로그까지 확정했다. 같은 일을 MD→헤드리스 실측 루프로 했다면 하루가
걸렸을 작업이 한 시간이 안 걸렸다. 반대로 리스트 **행 구조**는 녹화에 없어서 별도 진단
프로브(`li.listChk` 확정)가 필요했다 — 이 문서의 두 절이 정확히 그 두 경험이다.

## 1. 녹화 받기

사용자에게 실행을 요청한다(`!` 접두로 세션에서 바로 실행 가능):

```bash
cd backend && .venv/bin/playwright codegen "https://erp.ninebell.co.kr" \
  --target python-async -o e2e/artifacts/<flow>_codegen.py
```

- `--target python-async` — 리포의 e2e 규격(async Playwright)과 같은 형태로 나온다.
- 저장 위치는 `backend/e2e/artifacts/`(gitignore) 고정.
- **브라우저를 닫아야 파일이 저장된다.** 닫기 전까지는 빈 파일이다.
- 새 창(EAP `uc.ninebell.co.kr` 등)도 `expect_popup()` 으로 창별 기록된다 — 팝업 플로우에 특히 강하다.
- 여러 번 녹화할 때는 로그인 반복을 줄이려 `--save-storage=e2e/artifacts/<flow>_state.json`
  으로 세션을 저장하고 다음 녹화에서 `--load-storage` 로 재사용한다.

요청 시 **무엇을 클릭해야 하는지 순서를 함께 제시**한다(사용자가 헤매면 녹화가 지저분해진다).

## 2. 보안 — 녹화 파일에는 비밀번호가 평문으로 남는다

`page.get_by_placeholder("비밀번호를 입력하세요").fill("****")` 가 그대로 기록된다.

- `e2e/artifacts/` 밖으로 옮기지 않는다. **커밋 금지**(gitignore 이지만 `git add -f` 하지 말 것).
- 이식이 끝나면 녹화 파일을 삭제하거나 비밀번호 줄을 지운다.
- 이식한 스크립트는 반드시 env 주입(`E2E_USERID`/`E2E_PASSWORD`)으로 바꾼다 — 자격증명 비저장 규칙.

## 3. 녹화 → PROCESS.md 이식

녹화는 **좌표가 아니라 셀렉터**로 나온다. 그대로 쓰지 말고 다음처럼 승격한다.

| 녹화 산출물 | PROCESS.md 표기 | 비고 |
|---|---|---|
| `locator("#UBA1010_UBA").click()` | `검증: ✅` 메뉴 id(근거: `<flow>_codegen.py:19`) | 그대로 재사용 |
| `expect_popup()` 블록 | `검증: ✅` 새 창으로 열림(별도 Page) | `context.expect_page()` 로 이식 |
| `get_by_role("button", name="확인")` | `검증: ✅` 확인 다이얼로그 존재 | 텍스트 셀렉터는 리스킨에 약함 — 주석 남길 것 |
| `locator("span").filter(has_text="…")` | `검증: ❓` 행 선택 방법 | **행 구조는 별도 덤프 필요**(§4) |
| 좌표 클릭(캔버스 위) | `검증: ❓` 그리드 조작 | 녹화로 재현 불가(§4) |

이식 규율:
- 로그인은 녹화의 `fill/click` 대신 리포 프리미티브 `nbkit.patterns.login_flow.ensure_logged_in`
  으로 바꾼다(팝업 감시·공지 dismiss가 들어 있다).
- 메뉴 진입은 딥링크(`navigate_schema`)가 가능하면 그쪽이 우선 — 녹화의 클릭 경로는 폴백.
- 고정 `wait_for_timeout` 은 옮기지 않는다. 관찰 대기는 `nbkit.omnisol.verify` 규율(실시간 sleep)로.

## 4. 녹화가 못 잡는 것 — 여전히 프로브가 필요한 4가지

1. **캔버스 그리드(RealGrid) 셀 입력** — dews 그리드는 `<canvas>` 라 녹화에 무의미한 좌표만
   남는다. 셀 값·피커·숨은 백킹필드는 `dewsControl._grid` API 로만 다룬다
   (→ `erp-headless-grid-automation` 스킬).
2. **성공 판정 신호** — "저장이 실제로 됐는가"는 녹화에 없다. 모달·토스트·재조회 rowcount 등
   무엇을 보고 성공이라 할지는 프로브로 확정한다(이 판정이 없으면 팬텀 성공이 난다).
3. **타이밍·재시도** — 사람이 기다린 시간, 느릴 때의 상한, 실패 시 재시도 횟수는 기록되지 않는다.
4. **리스트/그리드 행 구조** — 클릭 한 번은 잡히지만, N행을 순회하려면 행 셀렉터·컬럼 매핑·
   상태 컬럼 파싱이 필요하다. DOM 덤프 프로브로 따로 확정한다.
   (실측: EAP 상신문서 리스트 = `li.listChk`, 제목은 `기안일` 아닌 span, 상태는 행 끝 `진행 (결재자)`)

## 5. 프로브 지시서에 쓰는 문장

단계 2 에서 prober 에 위임할 때, **중복 실측을 막기 위해** 두 줄을 반드시 넣는다:

```
녹화로 확정된 것(다시 확인하지 말 것): 메뉴 진입 경로 #UBA_UBA1000 → #UBA1010_UBA,
  문서 열기 = 제목 span 클릭 → 새 창, 확인 다이얼로그 = role=button name=확인
확인할 것: 리스트 행 셀렉터와 상태 컬럼, 행이 0건일 때의 화면, 처리 후 목록 갱신 여부
```
