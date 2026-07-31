"""결의서입력 하단 '항목(관리항목)' 패널 조작 — 업무용차량 선택(실측 2026-07-29).

실측(e2e/mgmt_item_panel_probe.py + artifacts/mgmt_item_panel_result.json):
  - 패널은 RealGrid 캔버스가 **아니라** 순수 DOM ``<table id="tb1">``(항목|내역코드|내역명
    3열). 행 input id 가 전부 'undefined_text' 로 충돌해 **라벨 텍스트로만** 행을 찾는다.
  - 관리항목 구성은 예산계정 의존 — 차량유지비 계열 계정을 고르면 '업무용차량' 행이 생긴다.
  - 패널은 **현재 선택된 상세행** 기준으로 갱신된다(행 전환 시 값도 따라 바뀜, 복원 확인).
  - 차량 팝업(제목 '업무용 차량', 버튼 적용/닫기)은 표준 코드피커 그리드 —
    BIZ_CAR_CD(차량코드)/CAR_NM(차량명)/CAR_NO(차량번호)/RENT_NM(임차여부).

저장(F7)·상신은 여기서 하지 않는다 — 필드 세팅과 readback 까지만.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from nbkit.browser.actions import mouse_click
from nbkit.omnisol import js_lib, latency
from nbkit.omnisol.codepicker import _picker_search

VEHICLE_LABEL = "업무용차량"

# ── 항목 패널(tb1) — 라벨 텍스트 기반 행 접근(프로브 검증 JS 이식) ─────────────────
_ROW_SCROLL_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const td = [...document.querySelectorAll('td')].find(e => e.offsetParent!==null && c(e.innerText)===label);
  if (!td) return false;
  td.scrollIntoView({ block: 'center' });  // 패널 내부 스크롤 — 없으면 버튼 좌표 0/클리핑(프로브 실측).
  return true;
}"""

_ROW_BUTTON_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const td = [...document.querySelectorAll('td')].find(e => e.offsetParent!==null && c(e.innerText)===label);
  if (!td) return null;
  const tr = td.closest('tr');
  const btn = tr && tr.querySelector('.dews-codepicker-button');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return null;
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

_ROW_VALUES_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const td = [...document.querySelectorAll('td')].find(e => e.offsetParent!==null && c(e.innerText)===label);
  if (!td) return { found:false };
  const tr = td.closest('tr');
  const tds = [...tr.querySelectorAll('td')];
  const codeInput = tds[1] ? [...tds[1].querySelectorAll('input')].find(i => i.id === 'undefined_text') : null;
  const nameInput = tds[2] ? tds[2].querySelector('input') : null;
  return { found: true, code: codeInput ? c(codeInput.value) : null, name: nameInput ? c(nameInput.value) : null };
}"""

# 차량 팝업 전 행 덤프(프로브는 10행 캡이었음 — 여기선 전량).
_VEHICLE_POPUP_DUMP_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).slice(-1)[0];
  if (!p) return { ok:false, reason:'no-popup' };
  const title = c((p.querySelector('.k-window-title') || {}).innerText);
  try {
    const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    return { ok:true, title, n,
      rows: rows.map(r => ({ code: c(r.BIZ_CAR_CD), name: c(r.CAR_NM), carNo: c(r.CAR_NO), rent: c(r.RENT_NM) })) };
  } catch (e) { return { ok:false, title, err: String(e).slice(0, 150) }; }
}"""

# 상세(디테일) 그리드 행 덤프 — 예산계정으로 차량유지비 행을 찾는다.
_DETAIL_ROWS_DUMP_JS = r"""() => { try {
  const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const n = g.getDataSource().getRowCount();
  const rows = n > 0 ? g.getDataSource().getJsonRows(0, n - 1) : [];
  return { ok:true, n, rows: rows.map(r => ({ BGACCT_NM: r.BGACCT_NM, BG_NM: r.BG_NM, NOTE_DC: r.NOTE_DC })) };
} catch (e) { return { ok:false, err: String(e).slice(0, 100) }; } }"""

# 상세행 클릭 좌표 — **스크롤 오프셋(getTopItem) 반영**(프로브 확정 2026-07-29: 고정 공식은
# 그리드가 스크롤되면 idx0 클릭이 idx4 를 짚는 등 **엉뚱한 행을 조용히 선택**한다).
# getTopItem 반환 형태가 미실측(숫자/객체)이라 방어적으로 파싱하고, 파싱 실패 시 0 으로
# 폴백 — 어긋난 클릭은 호출부의 getCurrent 재검증 + 쓰기 전 패널 기대값 가드가 잡는다.
_DETAIL_ROW_CLICK_JS = r"""(idx) => {
  try {
    const el = document.querySelectorAll('.dews-ui-grid')[1];
    if (!el) return null;
    let top = 0;
    try {
      const g = window.jQuery(el).data('dewsControl')._grid;
      const t = g.getTopItem ? g.getTopItem() : 0;
      top = (typeof t === 'number') ? t
        : (t && (t.itemIndex != null ? t.itemIndex
                 : (t.dataRow != null ? t.dataRow : 0))) || 0;
    } catch (e) { top = 0; }
    const off = idx - top;
    if (off < 0) return null;
    const r = el.getBoundingClientRect();
    const y = r.y + 34 + off * 32 + 16;
    if (y > r.y + r.height - 8) return null;
    return { x: Math.round(r.x + 100), y: Math.round(y) };
  } catch (e) { return null; }
}"""

# 상세행 API 선택(setCurrent) + 현재행 확인 — 좌표 클릭이 불가한(스크롤 밖) 행용.
_DETAIL_SET_CURRENT_JS = r"""(idx) => { try {
  const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  g.setCurrent({ itemIndex: idx });
  return { ok: true };
} catch (e) { return { ok:false, err:String(e).slice(0,100) }; } }"""

_DETAIL_CURRENT_JS = r"""() => { try {
  const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const cur = g.getCurrent ? g.getCurrent() : null;
  if (!cur) return -1;
  return cur.itemIndex != null ? cur.itemIndex : (cur.dataRow != null ? cur.dataRow : -1);
} catch (e) { return -2; } }"""

# 차량 팝업 목록 행 좌표(더블클릭용 — 프로브 검증: 더블클릭 1회 = 선택+적용+닫힘).
# 행이 그리드 가시영역 밖이면 null — 호출부가 선택→'적용' 폴백을 탄다.
_POPUP_ROW_RECT_JS = r"""(rowIndex) => {
  const p = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).slice(-1)[0];
  if (!p) return null;
  const gridEl = p.querySelector('.dews-ui-grid');
  if (!gridEl) return null;
  const gr = gridEl.getBoundingClientRect();
  const y = gr.y + 30 + rowIndex * 32 + 16;
  if (y > gr.y + gr.height - 8) return null;
  return { x: Math.round(gr.x + 150), y: Math.round(y) };
}"""


async def _read_vehicle_field(page: Any) -> dict:
    """현재 선택 상세행의 업무용차량 값 read — {found, code, name}."""
    await page.evaluate(_ROW_SCROLL_JS, VEHICLE_LABEL)
    await asyncio.sleep(0.3)
    return await page.evaluate(_ROW_VALUES_JS, VEHICLE_LABEL)


async def _select_detail_row(page: Any, idx: int) -> bool:
    """상세행 선택 + **현재행 검증**.

    프로브 확정(2026-07-29 2차): setCurrent 는 스크롤 상태와 무관하게 항상 정확하고,
    좌표 클릭은 스크롤 오프셋이 어긋나면 엉뚱한 행을 조용히 선택한다. 그래서 순서는
    ① setCurrent(스크롤·선택 확정) → ② top-aware 좌표로 그 행을 클릭(패널 리바인딩은
    클릭에서만 실측 확인) → ③ 클릭이 다른 행을 짚었으면 setCurrent 재고정 →
    ④ getCurrent==idx 최종 검증(실패면 False — 엉뚱한 행 조작 금지)."""
    r = await page.evaluate(_DETAIL_SET_CURRENT_JS, idx)
    if not r.get("ok"):
        return False
    await asyncio.sleep(0.5)  # 스크롤 정착 대기.
    box = await page.evaluate(_DETAIL_ROW_CLICK_JS, idx)
    if box:
        await mouse_click(page, box["x"], box["y"])
        await asyncio.sleep(0.8)  # 패널 갱신 대기(프로브 실측 타이밍).
        if await page.evaluate(_DETAIL_CURRENT_JS) != idx:
            # 클릭이 다른 행을 짚음(오프셋 계산 어긋남) — 재고정 후 패널 가드에 위임.
            r = await page.evaluate(_DETAIL_SET_CURRENT_JS, idx)
            if not r.get("ok"):
                return False
            await asyncio.sleep(0.8)
    else:
        await asyncio.sleep(0.8)
    cur = await page.evaluate(_DETAIL_CURRENT_JS)
    return cur == idx


async def _open_vehicle_popup(page: Any) -> dict:
    """업무용차량 돋보기 클릭 → 팝업 전 행 덤프. 반환 {ok, n, rows} | {ok:False, reason}."""
    await page.evaluate(_ROW_SCROLL_JS, VEHICLE_LABEL)
    await asyncio.sleep(0.3)
    box = await page.evaluate(_ROW_BUTTON_JS, VEHICLE_LABEL)
    if not box:
        return {"ok": False, "reason": "업무용차량 돋보기를 찾지 못했습니다(관리항목 패널에 해당 행 없음)"}
    await mouse_click(page, box["x"], box["y"])
    # 무엇을 기다리나: 차량 팝업 **오픈 + 목록 행 도착**(종전 고정 1.2s 후 1회 덤프). 덤프
    # ok(팝업+그리드 부착)이고 행이 있으면 즉시 진행. 필터로 정말 0건인 팝업은 상한(1.5s ×
    # latency 배율, 실시간 monotonic) 소진 후 마지막 덤프로 진행 — 기존 재검색 폴백 수순 유지.
    dump: dict = {}
    t0 = time.monotonic()
    cap_s = latency.budget_ms(1_500) / 1_000
    while True:
        dump = await page.evaluate(_VEHICLE_POPUP_DUMP_JS) or {}
        if dump.get("ok") and (dump.get("rows") or []):
            break
        if time.monotonic() - t0 >= cap_s:
            break
        await asyncio.sleep(0.3)
    if not dump.get("ok"):
        return {"ok": False, "reason": f"차량 팝업 덤프 실패: {dump.get('reason') or dump.get('err')}"}
    return dump


async def _poll_vehicle_reflected(page: Any, code: str, *, cap_ms: int = 2_400) -> dict:
    """팝업 적용(더블클릭/'적용') 후 패널 readback 이 ``code`` 로 반영될 때까지 실시간 폴링.

    종전 고정 1.2s 후 1회 readback 대체 — 무엇을 기다리나: 팝업 닫힘 + 관리항목 패널
    리바인딩으로 업무용차량 값이 배정 코드로 붙는 것(성공 판정과 동일 신호라 조기 진행
    위험 없음). 반영 즉시 마지막 readback 을 반환하고, 미반영이면 상한(latency 배율 확대,
    monotonic) 소진 후 마지막 readback 반환 — 호출부의 코드 일치 판정(실패 보고)은 기존
    그대로. _read_vehicle_field 자체가 스크롤 정착 0.3s 를 포함해 폴 간격을 겸한다.
    """
    t0 = time.monotonic()
    cap_s = latency.budget_ms(cap_ms) / 1_000
    rb: dict = {}
    while True:
        rb = await _read_vehicle_field(page) or {}
        if rb.get("found") and (rb.get("code") or "") == code:
            return rb
        if time.monotonic() - t0 >= cap_s:
            return rb


async def _close_popup(page: Any) -> None:
    try:
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        await asyncio.sleep(0.5)
    except Exception:  # noqa: BLE001 — 닫기 실패는 다음 오픈 시도에서 드러난다.
        pass


async def survey_vehicle_targets(page: Any) -> dict:
    """차량유지비 상세행들의 업무용차량 상태 + 차량 목록 확보.

    반환 {ok, targets:[{idx, acct, code, name}], vehicles:[{code,name,carNo,rent}]} |
    {ok:False, reason}. targets 는 예산계정에 '차량'이 포함된 상세행 전부(입력 여부 포함),
    vehicles 는 첫 미입력 행의 돋보기로 연 팝업 목록(덤프 후 닫음).
    """
    d = await page.evaluate(_DETAIL_ROWS_DUMP_JS)
    if not d.get("ok"):
        return {"ok": False, "reason": f"상세 그리드 read 실패: {d.get('err')}"}
    car_idxs = [
        i for i, r in enumerate(d.get("rows") or [])
        if "차량" in str(r.get("BGACCT_NM") or "")
    ]
    if not car_idxs:
        return {"ok": False, "reason": "차량유지비 계열 상세행이 없습니다"}
    targets: list[dict] = []
    for i in car_idxs:
        if not await _select_detail_row(page, i):
            return {"ok": False, "reason": f"상세행 {i + 1} 선택 실패"}
        v = await _read_vehicle_field(page)
        if not v.get("found"):
            return {"ok": False, "reason": f"상세행 {i + 1}의 관리항목 패널에 업무용차량 행이 없습니다"}
        targets.append({
            "idx": i,
            "acct": str((d["rows"][i] or {}).get("BGACCT_NM") or ""),
            "note": str((d["rows"][i] or {}).get("NOTE_DC") or ""),
            "code": v.get("code") or "",
            "name": v.get("name") or "",
        })
    first = next((t for t in targets if not t["code"]), targets[0])
    if not await _select_detail_row(page, first["idx"]):
        return {"ok": False, "reason": f"상세행 {first['idx'] + 1} 재선택 실패"}
    popup = await _open_vehicle_popup(page)
    if not popup.get("ok"):
        return {"ok": False, "reason": popup.get("reason")}
    vehicles = popup.get("rows") or []
    await _close_popup(page)
    if not vehicles:
        return {"ok": False, "reason": "차량 목록이 비어 있습니다"}
    return {"ok": True, "targets": targets, "vehicles": vehicles}


async def fill_vehicle(
    page: Any, assignments: list[tuple[int, dict]], expected: dict[int, str] | None = None
) -> dict:
    """(상세행 인덱스, 차량) 배정 목록을 순회 반영 + 행별 readback 검증.

    전체 동일 차량이면 호출부가 [(idx, v), …]로 같은 v 를 배정한다(내역별 상이 배정
    '1-1, 2-3' 지원 — 사용자 요청 2026-07-29). 반영 경로: 행 선택(현재행 검증) →
    (기대 기존값 대조 — 패널이 엉뚱한 행을 표시하면 쓰기 전에 중단) → 돋보기 → 목록에
    없으면 차량번호 재검색(값이 이미 있는 행의 팝업은 현재 값으로 **필터**돼 열릴 수 있다,
    실사용 2026-07-29) → 행 더블클릭(실측 경로, 가시영역 밖이면 선택→'적용' 폴백) →
    패널 readback 의 코드가 차량코드와 일치해야 성공(불일치는 실패로 보고, 성공 단정 금지).
    expected: {상세행 idx: 반영 전 기대 코드(''=빈)} — survey 시점 값. 쓰기 전 가드.
    반환 {ok, done:[행번호], failed:[{row, reason}]}.
    """
    done: list[int] = []
    failed: list[dict] = []
    for i, vehicle in assignments:
        row_no = i + 1
        if not await _select_detail_row(page, i):
            failed.append({"row": row_no, "reason": "상세행 선택 확인 실패(스크롤 밖 행 선택 불가)"})
            continue
        if expected is not None and i in expected:
            pre = await _read_vehicle_field(page)
            if pre.get("found") and (pre.get("code") or "") != expected[i]:
                # 패널이 의도한 행을 표시하지 않는다(직전 행 잔상 등) — 쓰면 엉뚱한 행이
                # 바뀐다. 쓰기 전에 중단하고 사실대로 보고.
                failed.append({
                    "row": row_no,
                    "reason": f"패널 값 불일치(기대 {expected[i]!r}/실제 {pre.get('code')!r}) — 행 전환 미반영 의심, 반영 중단",
                })
                continue
        popup = await _open_vehicle_popup(page)
        if not popup.get("ok"):
            failed.append({"row": row_no, "reason": popup.get("reason")})
            continue
        rows = popup.get("rows") or []
        pick_i = next((k for k, r in enumerate(rows) if r.get("code") == vehicle.get("code")), None)
        if pick_i is None:
            # 값이 있는 행의 팝업은 현재 값으로 필터돼 열릴 수 있다 — 차량번호로 재검색.
            try:
                await _picker_search(page, str(vehicle.get("carNo") or vehicle.get("code") or ""))
                popup = await page.evaluate(_VEHICLE_POPUP_DUMP_JS)
                rows = popup.get("rows") or [] if popup.get("ok") else []
            except Exception:  # noqa: BLE001 — 재검색 실패는 아래 '없음' 실패로 수렴.
                rows = []
            pick_i = next((k for k, r in enumerate(rows) if r.get("code") == vehicle.get("code")), None)
        if pick_i is None:
            await _close_popup(page)
            failed.append({"row": row_no, "reason": f"팝업 목록에 차량코드 {vehicle.get('code')} 없음(재검색 포함)"})
            continue
        # 1차: 행 더블클릭(프로브 실측 경로 — 선택+적용+닫힘 일괄). 가시영역 밖 행(rect
        # null)만 2차: setCurrent 선택 → '적용' 버튼(표준 코드피커 패턴, 이 팝업 미실측 —
        # 아래 readback 검증이 성공 단정을 막는다).
        rect = await page.evaluate(_POPUP_ROW_RECT_JS, pick_i)
        if rect:
            await page.mouse.dblclick(rect["x"], rect["y"])
        else:
            sel = await page.evaluate(js_lib.PICKER_SELECT_JS, pick_i)
            if not sel.get("ok"):
                await _close_popup(page)
                failed.append({"row": row_no, "reason": f"행 선택 실패: {sel.get('err') or sel.get('reason')}"})
                continue
            btn = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
            if not btn:
                await _close_popup(page)
                failed.append({"row": row_no, "reason": "'적용' 버튼 없음"})
                continue
            await mouse_click(page, btn["x"], btn["y"])
        # 반영 폴링(종전 고정 1.2s 후 1회 readback) — 패널 readback 코드 일치가 신호.
        rb = await _poll_vehicle_reflected(page, str(vehicle.get("code") or ""))
        if rb.get("found") and (rb.get("code") or "") == (vehicle.get("code") or ""):
            done.append(row_no)
        else:
            failed.append({
                "row": row_no,
                "reason": f"반영 확인 실패(기대 {vehicle.get('code')} / 실제 {rb.get('code')!r})",
            })
    return {"ok": bool(done) and not failed, "done": done, "failed": failed}


def resolve_vehicle_assignments(
    text: str, vehicles: list[dict], n_targets: int
) -> tuple[list[tuple[int, dict]] | None, str]:
    """'1-1, 2-3, 3-1'(내역-차량) → [(내역번호 1-based, 차량), …] | (None, 안내).

    쌍 패턴이 하나도 없으면 (None, "") — 호출부가 단일 차량 해석으로 폴백한다.
    내역/차량 번호 범위 밖·내역 중복은 임의 해석하지 않고 안내문을 돌려준다.
    """
    pairs = re.findall(r"(\d+)\s*-\s*(\d+)", text or "")
    if not pairs:
        return None, ""
    out: list[tuple[int, dict]] = []
    seen: set[int] = set()
    for a, b in pairs:
        t_no, v_no = int(a), int(b)
        if not (1 <= t_no <= n_targets):
            return None, f"내역 {t_no}번은 대상 목록(1~{n_targets}번)에 없습니다."
        if not (1 <= v_no <= len(vehicles)):
            return None, f"차량 {v_no}번은 목록(1~{len(vehicles)}번)에 없습니다."
        if t_no in seen:
            return None, f"내역 {t_no}번이 두 번 지정됐습니다 — 한 번씩만 지정해 주세요."
        seen.add(t_no)
        out.append((t_no, vehicles[v_no - 1]))
    return out, ""


def resolve_vehicle_choice(text: str, vehicles: list[dict]) -> tuple[dict | None, str]:
    """사용자 답변('3번'/'175호3757'/'카니발' 등) → 차량 1대 확정. 반환 (vehicle|None, 안내문).

    번호(1-based) 우선, 다음 차량번호/차량명/코드 부분일치. 0건이면 없음, 2건 이상이면
    후보를 안내(임의 선택 금지).
    """
    t = (text or "").strip().replace(" ", "")
    if not t or not vehicles:
        return None, "차량 목록이 없습니다."
    m = re.fullmatch(r"(\d+)\s*번?", t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= len(vehicles):
            return vehicles[n - 1], ""
        return None, f"{n}번은 목록(1~{len(vehicles)}번)에 없습니다."
    hits = [
        v for v in vehicles
        if t in str(v.get("carNo") or "") or t in str(v.get("name") or "") or t == str(v.get("code") or "")
    ]
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, "목록에서 일치하는 차량을 찾지 못했습니다. 번호(예: '3번')나 차량번호로 알려주세요."
    desc = ", ".join(f"{vehicles.index(v) + 1}번 {v.get('carNo')}-{v.get('name')}" for v in hits[:5])
    return None, f"여러 대가 일치합니다({desc}). 번호로 골라주세요."
