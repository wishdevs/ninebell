# OMNISOL_NOTES — 더존 OmniEsol 브라우저 자동화 노하우

nbkit 이 인코딩한 옴니솔(더존 ERP) 화면 조작 노하우 요약. 원천은 ninebell-bak 의 실측
경험 문서(`docs/collection-strategies.md`, `experience-grid-data-extraction.md`,
`flow-ninebell-*.md`)와 검증된 그래프 노드다. **여기 적힌 함정을 어기면 조용히 실패한다.**

> 원칙: (1) 모든 더존 상호작용은 헤드리스 브라우저(Playwright)로만 — 내부 API 직접호출 금지.
> (2) 자격증명 비저장 — 매 작업마다 1회 로그인 → 작업 → 즉시 폐기.
>
> ⚠ (1)의 예외 — **읽기전용 마스터 코드 카탈로그 수집**(예산단위·프로젝트·거래처)은 순수 HTTP
> API 로 하는 것을 우선한다(사용자 승인 2026-08-28, 실측: `backend/e2e/api_discovery_http_repro.py`).
> `app/erp/api_client.py` 가 `POST /api/CM/AccountService/login` 으로 access_token(JWT)을 받아
> `x-authenticate-token` 헤더로 코드도움 서비스(H_*_list)를 직접 호출한다. **실패 시 기존
> 브라우저 코드피커 경로로 자동 폴백**하며, `ERP_API_SYNC_ENABLED=false` 로 강제 브라우저 전환도
> 된다. 이 예외는 **읽기전용 수집에 한정**한다 — 전표·발주·상신 등 쓰기/자동화 흐름은 여전히
> (1) 그대로 브라우저 전용이다(저장·상신을 API 로 하지 않는다).
>
> ⚠ 조직구분(org_unit)은 완전 browserless 가 **불가**하다. 조직도 트리 API 는 ERP 가 아니라
> **Wehago 포탈(uc.ninebell.co.kr) `POST /gw/APIHandler/gw102A01`** 이고, 인증이
> `Authorization: Bearer <authToken>`(ERP 로그인 JWT 의 authToken 클레임) + `session-id` +
> `wehago-sign`(브라우저 위젯이 계산, 리버싱 불가)이다. 그래서 **하이브리드**로 간다 —
> 브라우저로 조직도를 한 번 열어 위젯이 쏜 gw102A01 요청 헤더를 캡처 → `isTreeAllOpen:true` 로
> 재요청(page.request)해 전량 트리를 받는다(`app/services/org_sync.fetch_org_tree`). 이게 DOM
> 스크레이프의 Kendo lazy-load 누락(미펼친 팀)까지 해소한다. 실패 시 DOM 스크레이프 폴백.

---

## 1. RealGrid 은 캔버스다 (DOM 아님)

더존 그리드는 `<table>`/`<div>` 행이 아니라 **`<canvas>` 로 렌더**된다(상용 RealGrid +
더존 dews 래퍼). DOM 스냅샷·텍스트 셀렉터·좌표 추출이 **통하지 않는다**. `getCellRect` 도 null.

그리드 인스턴스는 **jQuery data** 로 잡는다:

```js
$(".dews-ui-grid").eq(i).data("dewsControl")._grid          // RealGrid GridView
$(".dews-ui-grid").eq(i).data("dewsControl")._grid.getDataSource()  // DataProvider
```

- 그리드 순서: `[0]`=마스터, `[1]`=디테일, `[2]`=항목. 팝업은 자체 그리드를 가진다.
- 유용 메서드: `getRowCount` / `getJsonRows` / `getValues` / `setCurrent` / `setSelection` / `showEditor`.

→ nbkit: `grid/provider.py`(GridProvider), `omnisol/js_lib.py`(모든 in-page JS).

## 2. `getJsonRows(start, end)` 는 **END-INCLUSIVE** (off-by-one)

20행을 원하면 `getJsonRows(0, 19)`. 실수로 `(0, 20)` 하면 **21행**이 되어 다음 행(예 0025)이
끼어드는 off-by-one 버그(collection-strategies 실측: S1/S3/S8 에서 0025 끼어듦).

→ nbkit: **정규화를 `grid/validation.py` 한 곳에** 둔다.
`normalize_range(start, count, total) → (start, end_inclusive, take)`.
`GridProvider.get_rows(start, count)` 는 이 정규화를 거쳐 항상 정확한 행수를 준다. 호출자는
end-inclusive 를 신경 쓸 필요가 없다. `validation.validate_master_count` 가 과수집을 검출.

## 3. 수집 전략: 병렬 함수호출(빠름) vs 키보드(견고)

`grid/strategies.py` — `CollectionStrategy` = `PARALLEL_AJAX` / `KEYBOARD_FALLBACK` / `AUTO`.

### 방법 A — PARALLEL_AJAX (권장, ~150ms/20행)
- 마스터: provider 에서 즉시 일괄(`getJsonRows`, 네트워크 0).
- 디테일: 앱 dataSource **transport URL 로 `$.ajax` 병렬**. 앱 전역 ajax 설정이 인증
  헤더(JWT)를 **자동 주입** → 401 없음, 네트워크 가로채기 아님, fetch 위조 아님.
- 디테일은 **행당 1요청 고정**(멀티부모 콤마 불가). 마스터별 병렬 발사.
- ⚠ 현재 JS(`js_lib.collect_master_detail_js`)는 검증된 **BOM 형태**(`_uid`/`INVTRX_RSV_NO`/
  `close_yn`) 대상. 다른 화면이 생기면 그 빌더를 확장.

### 방법 B — KEYBOARD_FALLBACK (앱이 함수호출 막았을 때, 견고)
- 원리: 실제 입력으로 마스터 행을 이동시키면 앱이 디테일을 화면에 띄운다 → 그 디테일
  그리드를 직접 읽는다. 캐시·서명·가로채기와 무관.
- **함정(핵심)**:
  1. `setCurrent()`(JS)·좌표 클릭은 **디테일 로딩을 트리거하지 않는다.** 디테일 로드
     핸들러는 **실제 키보드 입력(trusted)** 에만 반응 → `page.keyboard.press("ArrowDown")`.
  2. 앱이 디테일을 **캐시**한다(한 번 본 행은 재요청 안 함).
  3. 페이지 리로드로 캐시를 못 비운다(주입 후크도 사라짐).
- 검증된 루프: `setCurrent(0)`(앵커) → 첫 행 **실클릭**(포커스+행0 로드) → 행마다
  [디테일 읽기 → **실제 ArrowDown**]. 누락 시 `ArrowUp→ArrowDown` **지글**. 행당 dwell ~1.5s.

→ nbkit: `browser/frames.py`(`press_arrow_down`/`jiggle`), `strategies.py`(`_keyboard_fallback`).

## 4. 사용자유형 전환은 **실제 마우스 클릭**으로만

옴니솔은 사용자유형(인사/회계)에 따라 접근 모듈이 다르다(인사→IM 재고, 회계→FI 재무회계).

⚠ **JS `.click()` / Kendo 위젯 `.value()` 는 더존 변경적용 핸들러를 못 깨운다** — select
값만 바뀌고 실제 컨텍스트(모듈 접근)는 **안 바뀐다**. 반드시 **좌표 실클릭**으로:
드롭다운 열기 → 옵션 클릭 → **변경적용** 클릭. 변경적용은 페이지를 reload 하며 해당
컨텍스트 모듈을 부여한다.

- nbkit 패턴: JS 는 **클릭 좌표(bbox 중심)만** 돌려주고, 실제 클릭은 `page.mouse.click`.
- 전환 후 **패널을 다시 열어 재확인**(더블체크). 최대 2회 재시도.

→ nbkit: `omnisol/auth.py`(`switch_user_type`), `browser/actions.py`(`mouse_click`),
`js_lib`(`UT_DROPDOWN_BOX_JS`/`UT_OPTION_BOX_JS`/`UT_APPLY_BOX_JS`/`UT_DISPLAY_JS`/`USER_TYPE_READ_JS`).

## 5. 캔버스 셀 편집 = `setCurrent`+`showEditor` → DOM 오버레이 픽셀 클릭

증빙유형 같은 codepicker 셀은 캔버스라 DOM 이 없다. `setCurrent({itemIndex, fieldName})` +
`showEditor()` 로 **DOM 에디터 오버레이(input + 돋보기)** 를 띄운 뒤, input bbox 오른쪽
(`input.right + 8px`)을 **픽셀 실클릭**해 돋보기 팝업을 연다. 좌표는 뷰포트(1600×1000) 의존.

→ nbkit(P3 프리미티브, `js_lib` §B): `OPEN_EVDN_EDITOR_JS`, `EVDN_EDITOR_MAGNIFIER_RECT_JS`.

## 6. 성공 판정은 URL 이 아니라 **요소/그리드 상태**로

- 로그인: 성공해도 URL 이 그대로일 수 있다 → **로그인 폼(`#userid`) 소멸** 또는 요소 수
  임계값(>200)으로 판정.
- 메뉴 진입: **`.dews-ui-grid` 개수**로 판정. "메뉴를 찾을 수 없/권한이 없" 팝업이면
  90초 헛돌지 말고 **즉시 실패**(MenuError).
- 옴니솔은 `networkidle` 을 자주 못 잡는다 → 대기는 **타임아웃을 삼키고** 후속 조건 폴링으로 판정.

→ nbkit: `browser/detection.py`(`is_authenticated`/`detect_dialog`), `browser/waits.py`,
`omnisol/navigator.py`(`navigate_menu`), `js_lib.MENU_CHECK_JS`.

## 7. 취약 셀렉터·좌표·JS 는 **단일 소스**

옴니솔 리스킨/버전업 시 클래스·id·좌표가 바뀐다. nbkit 은 이를 한 곳에 모아 그때 한
파일만 고치게 한다:
- CSS 셀렉터 → `omnisol/selectors.py` (뷰포트·로그인폼·그리드·툴바버튼·모달·코드피커).
- in-page JS → `omnisol/js_lib.py` (rowcount·getJsonRows·menu-check·profile·user-type
  bbox·plant·collect·[P3] kendo/evidence/project).
- 메뉴 매핑 → `omnisol/menu_schemas.py` (메뉴ID↔딥링크↔상세 service_url↔사용자유형).

## 8. ⚠ 절대 금지 (실데이터 생성)

결의서입력(FI/GLDDOC00300) 쓰기 플로우에서 **저장(F7, `.main-button.save`)** 과 모달
**확정 '적용'** 이후 단계는 **실전표를 생성**한다. 자동화는 **증빙유형 선택/모달 적용 직전까지**만.
`selectors.BTN_SAVE` 는 참조용 상수일 뿐 — 클릭 금지.

## 9. 메뉴 딥링크 (검증됨)

| 메뉴 | 딥링크 | 사용자유형 | 그리드 | 상세 service_url |
|------|--------|-----------|--------|------------------|
| 프로젝트BOM불출요청처리[나인벨] (`IMIIRM00700_X20616`) | `/IM/IMIIRM00700_X20616` | 인사 | 2 | `/api/IM/Imiirm00700_X20616_Service/imiirm00700_x20616_list_dtl` |
| 결의서입력 (`GLDDOC00300`) | `/FI/GLDDOC00300` | 회계 | 3 | — (쓰기 플로우) |

딥링크 우선. 폴백(사이드바 플라이아웃): 좌측 아이콘 사이드바를 path 순서로 클릭하되
**클릭마다 재스냅샷**(펼침/접힘으로 ref 무효화). 폴백은 라이브 전용이라 nbkit 은 딥링크+폴링만
구현하고 폴백 절차는 이 문서로 남긴다.

## 10. 값 선택은 **선택 → 확인 → 다음**(확인 커널)

옴니솔 자동화의 조용한 실패 대부분은 *클릭/세팅 호출이 성공했다* 를 *값이 반영됐다* 로
착각하는 데서 나온다: 피커 '적용'이 폼에 안 붙음, 드롭다운이 change 핸들러에 되돌려짐,
조회 버튼을 눌렀지만 그리드가 아직 이전 결과, 탭이 안 열렸는데 그 화면을 조작…
**값을 지정하는 스텝은 반영을 확인하고서야 성공을 돌려준다**(`nbkit/omnisol/verify.py`).

### 재시도 규율 (사용자 지시 2026-07-27)
**가능하면 딜레이 없이 확인**하고, 실패하면 **짧은 대기부터 점증하며 3회 재시도**한다.
정상 경로는 첫 read(대기 0ms)에서 끝나므로 **추가 지연이 0** 이다.

| timing | 대기(ms) 0→1→2→3회차 | 대상(반영 타이밍) |
|---|---|---|
| `INSTANT` | 0, 120, 360, 900 | native select 선택값, input readback (DOM 즉시) |
| `ASYNC` | 0, 300, 900, 2400 | 피커 적용 표시값, 팝업 개폐, dialog 렌더(위젯 왕복) |
| `HEAVY` | 0, 600, 1800, 4500 | 화면·탭 전환, 조회 결과 그리드(서버 왕복) |

⚠ 대기는 **실시간**(`asyncio.sleep`)이다. `page.wait_for_timeout` 은 워크플로우
`delay_scale`(예: 0.4)로 축소돼 느린 세션에서 확인이 조기 실패한다 — 공지 팝업 관찰창이
같은 이유로 붕괴했던 선례가 있다. 이 대기는 **실패했을 때만** 발생하므로 delay_scale 의
목적(정상 경로 단축)과 충돌하지 않는다.

### 종류별 확인 헬퍼 (전부 같은 커널)
| 종류 | 헬퍼 | 리더(js_lib §C) |
|---|---|---|
| 셀렉트 | `confirm_select(page, selector, text)` | `SELECTED_TEXT_JS` |
| 피커 표시값 | `confirm_display(page, label)` / `confirm_display_empty` | `FIELD_DISPLAY_JS` |
| 팝업 개폐 | `confirm_popup_count(page, more_than=/less_than=)` | `POPUP_COUNT_JS` |
| 그리드 | `confirm_grid_rows(page, index=, min_rows=)` | `ROWCOUNT_BY_INDEX_JS` |
| 화면·탭 도착 | `confirm_visible_label(page, label)` ← 권장 / `confirm_visible_element(page, selector)` | `FIELD_LABEL_VISIBLE_JS` / `VISIBLE_ELEMENT_JS` |
| 화면 텍스트 | `confirm_visible_text(page, text)` | `VISIBLE_TEXT_JS` |
| 기간 | `confirm(read=PERIOD_VALUE_JS…)` | `PERIOD_VALUE_JS` |

⚠ 다중 메뉴 탭에서는 다른 탭의 DOM 이 남아 있으므로 도착 확인은 **존재가 아니라 가시성**으로
한다 — 엉뚱한 탭 조작 사고 차단.

⚠⚠ **도착 앵커로 native select 를 쓰지 말 것**(2026-07-27 라이브 실패로 확정): kendo
DropDownList 는 원본 `<select>` 를 `display:none` 으로 숨기고 위젯을 대신 그린다 — 올바른
화면에 도착해도 select 는 영원히 '안 보임'이라 확인이 **항상 실패**한다. 반대로 값 세팅
(`KENDO_SET_DROPDOWN_BY_TEXT_JS`)·선택값 읽기(`SELECTED_TEXT_JS`)는 jQuery 위젯 API 라
숨은 select 에서도 정상 동작한다 — **가시성 앵커로만 부적합**하다.
도착 앵커는 `confirm_visible_label`(조회조건 라벨) 또는 실제 버튼 rect(예: 결재 버튼)처럼
**눈에 보이는 것**으로 잡는다. 화면 식별 예: 전표조회승인 '작성부서' / 결의서조회승인 '결의부서'.

### 연쇄(cascade) — 어떤 값은 다른 값에 영향을 준다
- `settle=` : 매 확인 **직전** 정착(예: `wait_loading_overlay_gone`). 로딩 중 스냅샷을 읽고
  "반영됐다"로 오판하거나 **직전 조회 결과(스테일)** 를 읽는 것을 막는다.
- `reapply=` : 재시도 때 액션 **재실행**(되돌려지는 드롭다운 등). 기다린다고 붙지 않는 값 전용.
- A 가 B 를 바꾸면 **A 확인 후 B 를 다시 확인**한다(호출부에서 confirm 을 이어 붙임).

### 실패 처리 정책 — 불일치(hard) vs 확인 불가(soft)
`Confirmed.mismatch`(확인은 됐는데 값이 다름) = **하드 실패**로 중단한다.
`Confirmed.unknown`(리더가 필드/위젯을 못 읽음, `unknown_when=`) = **경고 후 진행** —
리더 오탐이 플로우를 끊지 않게 한다(D7 체크행수 판정과 같은 규율).
어느 쪽을 하드로 둘지는 **그 값이 대상 집합을 정의하는가**로 가른다:
- 대상 정의(전표유형·전표상태·결의구분·화면 도착·조회 결과) → 하드.
- 범위 보조(부서 전체선택·작성자 비움·회계일 override) → soft(warn) 후 진행.

→ 커널 `omnisol/verify.py`, 리더 `omnisol/js_lib.py` §C, 계약 테스트 `tests/test_verify_kernel.py`.

### 적용 현황 / 확장 지침 (2026-07-27)
| 화면·스텝 | 상태 |
|---|---|
| 전표조회승인 조회조건 6필드(`voucher_receivable/steps.py`) | ✅ 확인 커널 적용 — **외상매출금·외상매입금·미지급금 법인카드 3개 에이전트가 공유 백본으로 자동 승계** |
| 결의서조회승인 Phase B(`voucher_card/steps.py`) | ✅ 탭 도착·결의부서·결의자·회계일·결의구분·조회 결과 |
| 결제창 참조문서 Phase C | ✅ dialog 도착·문서번호 readback / ⚠ '선택된 문서 목록' 이동만 **미확인**(하단 그리드 리더 프로브 필요 — 로그도 '완료'가 아니라 '미확인'으로 남긴다) |
| 결의서입력 증빙유형(`common/doc_steps.select_evdn_code`) | ✅ 이미 셀 반영 판정으로 확인 중(커널 이전 방식이나 동등 — 신규 확인은 커널 사용) |
| 사용자유형 전환(`omnisol/auth.switch_user_type`) | ✅ 패널 재오픈 재확인(전환 성격상 전용 로직 유지) |

새 스텝을 만들 때: **값을 지정했으면 그 값을 읽는 리더를 정하고 `confirm_*` 로 확인**한다.
리더가 없으면 `js_lib` §C 에 추가한다(에이전트 로컬 js.py 가 아니라 — 전 에이전트 공용).
확인할 리더를 아직 모르면 **성공을 단정하지 말고**(`verified=False`) 로그에 미확인임을 남기고,
프로브(`omnisol-flow-prober`)로 셀렉터를 확정한 뒤 확인을 붙인다.

## 10-1. 진입 구간 속도 — 공지 대기를 **차단형으로 두지 말 것**(2026-07-28 실측)

진입(login → user_type → menu_nav) 11.8s 중 **5s 이상이 '공지 팝업을 기다리는 시간'**이었다
(`e2e/login_timing_probe.py` 로 단계별 실측):

| 구간 | 전 | 후 |
| --- | --- | --- |
| 로그인(goto+폼+제출폴링) | 4.0s | 4.0s (서버 왕복 — 손댈 게 없음) |
| 공지 대기(로그인 직후) | 2.4~3.3s | 그대로(실제로 팝업을 잡는다) |
| 프로필 읽기 | 0.3s | 0.3s |
| 사용자유형 전환 | 0.2s | 0.2s |
| **메뉴 진입** | **4.8s** | **1.5s** |
| **합계** | **11.8s** | **8.6s** |

- 공지 팝업은 로그인 완료 **~1.6초 뒤** 뜨고, 화면 전환 뒤에는 (실측 계정·화면 기준) 다시 뜨지
  않는다. 그래서 메뉴 도착 후의 관찰창 2.5s 는 **매 실행 ~2.8s 를 통째로 헛대기**했다 →
  `watch_notice_popup`(배경 감시)로 바꿔 없앴다. 재출현하면 배경에서 그대로 닫힌다.
- ⚠ **로그인 직후 대기는 배경화하지 말 것**(시도했다가 되돌림): 그 시간을 없애면 팝업 등장이
  프로필 읽기(아바타 클릭)와 겹쳐 0.3s → 2.4s 로 늘어난다 — 총합은 그대로인데 변동성만 커진다.
  기다리든 가려지든 그 1.6초는 어차피 지불된다.
- 클릭 직전 JIT 확인(`appear_cap_ms=0`)은 **차단형 그대로** 두었다 — 레이스 방어는 불변.

## 11. 로그인 시 뜨는 **시스템 팝업(별도 창)** — 공지 팝업과 다른 축

계정에 따라 로그인 중 **회사 홈페이지가 별도 브라우저 창**으로 뜬다(실측 2026-07-27, 계정
'석대현': `http://www.ninebell.co.kr/default/00/01.php` / '주식회사 나인벨'). 이때 **메인 페이지의
인페이지 다이얼로그는 0개** — `dismiss_notice_popup`(고유 앵커 `#close-today-chk`)은 인페이지
레이어 전용이라 이 창을 **절대 잡지 못한다**. 처리 축이 다르다:

| | 공지 팝업 | 시스템 팝업 |
|---|---|---|
| 정체 | 같은 페이지의 `.k-window` 레이어 | `window.open` 으로 뜬 **별도 Page** |
| 처리 | `dismiss_notice_popup`(체크+닫기 실클릭) | ①`install_notice_autoclose`(상시 즉시 닫기) ②`PopupWatcher`(로그인 구간 폴백) |
| 단일소스 | `nbkit/omnisol/modals.py` | `nbkit/browser/popups.py` |

### 공지 시스템 팝업은 **도착 즉시 닫아 무시한다**(2026-07-28, 사용자 요청)
`install_notice_autoclose(context)` 가 컨텍스트에 **상시** `page` 리스너를 걸어, 도착한 창이
공지로 확정되면 곧바로 닫는다(`app/live/runner.py` 가 컨텍스트 생성 직후 1회 설치).

⚠ **폐기한 접근 — `window.open` 후킹은 동작하지 않는다.** 처음엔 공지 URL 이면 창을 열지 않게
`window.open` 을 가로챘으나 실화면에서 공지창이 그대로 떴다. 추적 결과(`e2e/notice_open_trace.py`):
- 공지창의 **opener 는 ERP 메인 페이지가 맞다**(그 페이지가 연 것),
- 그런데 **모든 프레임에서 `window.open` 호출이 0건**이다 → form target 등 다른 경로로 열린다.

즉 "어떻게 여는지"에 기대면 안 된다. 열린 창을 즉시 닫는 축이 메커니즘과 무관하게 동작한다
(헤드리스에선 사람 눈에 보이지 않으므로 이것이 곧 '무시'다).

- **닫는 기준은 공지 마커**: `art_seq_no=` / `callComp=UFAP…`. 상시 동작이라 호스트 기준을 쓰면
  안 된다(결제창이 같은 호스트).
- ⚠⚠ **결제창(EAP)은 절대 닫지 않는다** — `approkey` / `docID` / `callComp=UBAP…` /
  `MicroModuleCode=eap`. 판정 전에 `is_approval_window` 로 한 번 더 막는다.
- **fail-safe**: 공지로 확정되지 않으면 닫지 않는다. 못 닫은 공지는 무해하지만, 업무 창을 닫으면
  결재가 불가능해진다.
- 실화면 검증: `e2e/notice_block_verify.py` — 대조군(미설치)엔 공지창이 살아남고, 실험군엔
  남지 않음(2026-07-28 실측 ✅).

### 회계일 기간은 **항상 명시 세팅**한다(2026-07-28)
두 화면(전표조회승인 `#s_period` · 결의서조회승인 `#PERIOD_DT_C`)의 **화면 기본값은 1일~오늘**
이지 1일~말일이 아니다(실측). 그래서 '당월이면 안 건드린다'는 단락을 두면 —
- 전표조회승인은 `setMonth()` 로 1일~말일이 되고,
- 결의서조회승인은 손대지 않아 1일~오늘로 남아

**두 화면의 조회기간이 어긋난다**(미지급금 법인카드는 두 화면을 함께 쓴다). 기간이 주어지면
당월이든 아니든 항상 세팅한다. 임의 기간 세팅이 두 화면 모두 반영되고 이후 조회조건 세팅에도
유지됨은 `e2e/voucher_period_probe.py` 로 확인했다(view/model 분리 측정).

### 규율(폴백 `PopupWatcher`)
- **감시는 로그인 구간에서만.** 결제(결재)창(EAP)도 다른 호스트의 시스템 팝업이라, 상시 자동
  닫기를 걸면 정상 업무 창을 죽인다 — `PopupWatcher.start()/stop()` 로 구간을 명시한다
  (`ensure_logged_in` 이 `finally` 에서 반드시 `stop()`).
- **닫는 기준은 호스트.** ERP(`erp.ninebell.co.kr`)와 다른 호스트만 닫고, 같은 호스트 창은
  업무 창일 수 있으므로 보존한다. 갓 열린 창은 `about:blank` 라 목적지 URL 이 정해질 때까지
  짧게 기다린 뒤 판정한다.
- **도착 즉시 닫는다(이벤트 기반).** 이 팝업은 로그인 시퀀스 중 **뜨는 시점이 일정하지 않다**
  (실측: 공지 정리 뒤 프로필 읽기 구간에 도착) — 한 지점에서 한 번만 훑으면 놓친다.
- **관찰 대기를 두지 말 것.** 즉시 닫기가 커버하므로 sweep 은 `appear_cap_ms=0` 으로 '지금까지
  닫힌 것 회수' 용도만 — 대기를 두면 팝업이 없는 계정·에이전트 전부가 그 시간을 물어 로그인이
  느려진다(실측: 2s 관찰 = 전 에이전트 로그인 +2s).

→ 프로브 `e2e/login_popup_probe.py`(계정별 팝업 정체·출현 시각 측정), 계약 테스트
`tests/test_login_popup_close.py`.

### 계정별 로그인 속도(실측 2026-07-27, 참고)
`omnisol_login` 자체가 계정에 따라 크게 다르다 — 이트라이브2 4.6s vs 석대현 **25.3s**
(팝업 닫기와 무관: 팝업은 로그인 완료 **후** 도착). 원인은 ERP 측(계정 초기화면·권한 로딩)으로
보이며 자동화가 줄일 수 있는 구간이 아니다. 타임아웃을 잡을 때 이 편차를 고려할 것.
