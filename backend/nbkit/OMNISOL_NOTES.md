# OMNISOL_NOTES — 더존 OmniEsol 브라우저 자동화 노하우

nbkit 이 인코딩한 옴니솔(더존 ERP) 화면 조작 노하우 요약. 원천은 ninebell-bak 의 실측
경험 문서(`docs/collection-strategies.md`, `experience-grid-data-extraction.md`,
`flow-ninebell-*.md`)와 검증된 그래프 노드다. **여기 적힌 함정을 어기면 조용히 실패한다.**

> 원칙: (1) 모든 더존 상호작용은 헤드리스 브라우저(Playwright)로만 — 내부 API 직접호출 금지.
> (2) 자격증명 비저장 — 매 작업마다 1회 로그인 → 작업 → 즉시 폐기.

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
