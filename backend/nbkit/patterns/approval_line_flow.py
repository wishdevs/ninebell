"""결재라인 지정 플로우 — 결제창(EAP 팝업 Page) 안에서 결재선에 사용자를 추가한다.

실측 2026-08-21 (프로브 approval_line_probe_1/2/4a/4b + cleanup + 사용자 headed 시연,
이트라이브2 계정):
  · 모달 진입은 **결재란 사용자 셀 `td.lineUserInfo`**(사용자 시연 경로 — DOM 셀렉터,
    Playwright 자동 대기로 배치 본문 렌더 지연 흡수)가 1차, 전표 헤더의 '결재' 라벨
    (≈770,262 세로 셀 — 상단 네비바 아님, 프로브 검증 경로)이 폴백이다. 둘 다 같은
    Page 안에 "결재라인 지정" DOM 오버레이 모달을 띄운다.
  · 모달 우상단 인원표는 **canvas(RealGrid)** 라 DOM 셀렉터가 없다 — 체크박스는
    캔버스 rect 기준 픽셀 산식으로 클릭한다(헤더 27.5px, 행 29.2px, 체크박스 x+10).
  · 상단 툴바(병렬/결재/합의/수신참조/시행 — DOM)에서 '결재'를 누르면 체크한 인원이
    하단 결재선 그리드에 추가되고, 최하단 '저장'으로 모달이 닫힌다.
  · **지정은 비영속** — 상신 없이 결제창을 닫으면 소멸한다(새 세션 재오픈으로 확정).
    따라서 상신 직전에 결제창마다 매번 지정해야 한다.
  · 성공 검증: 저장 후 전표 헤더(DOM)에 대상 이름 리프 텍스트가 **정확일치로 새로**
    나타난다('이트라이브' vs '이트라이브2' 는 서로 다른 리프라 부분일치 오염 없음).
    캔버스 행 순서가 밀려 엉뚱한 사람을 체크해도 이 게이트가 상신 전에 잡는다.

⚠ 절대 안전: 이 모듈은 상신·보관을 클릭하지 않는다. 예상 밖 다이얼로그는 Escape 후
   실패로 반환한다(조용한 진행 금지).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

ERR_MAX = 200

# 결제창(EAP React) 리프 텍스트 전량 덤프 — 버튼 좌표·모달 상태·검증 신호의 단일 소스.
# ⚠ 읽기 전용. 캔버스 그리드 내용은 잡히지 않는다(DOM 텍스트만). w/h 는 '결재' 라벨(세로
# 셀 w40×h110 실측)을 형태로 판별하는 근거다 — 좌표 기준은 창 크기에 취약해 쓰지 않는다.
EAP_LEAF_DUMP_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 0) continue;
    const t = c(el.innerText || el.textContent || '');
    if (!t) continue;
    const r = el.getBoundingClientRect();
    if (el.offsetParent === null || r.width <= 0 || r.height <= 0) continue;
    out.push({ text: t.slice(0, 80), x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), w: Math.round(r.width), h: Math.round(r.height) });
  }
  return out;
}"""

# 가시 캔버스 rect 목록 — 결재라인 모달의 인원표(RealGrid) 위치 산출용. ⚠ 읽기 전용.
EAP_CANVAS_RECTS_JS = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('canvas')) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || el.offsetParent === null) continue;
    out.push({ x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) });
  }
  return out;
}"""

# 소형 확인 다이얼로그 감지(저장 클릭 후) — 위험 문구 필터의 근거. ⚠ 읽기 전용.
EAP_SMALL_DIALOG_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  for (const w of document.querySelectorAll('.k-window, .k-dialog, [role="dialog"], [class*="Modal"], [class*="Dialog"], [class*="confirm"], [class*="Confirm"]')) {
    if (w.offsetParent === null) continue;
    const r = w.getBoundingClientRect();
    if (r.width <= 0 || r.width > 600 || r.height <= 0 || r.height > 400) continue;
    const t = c(w.innerText);
    if (t) out.push({ text: t.slice(0, 300) });
  }
  return out;
}"""

MODAL_TITLE = "결재라인 지정"
# 인원표 캔버스 픽셀 산식(실측 4a — 시각 검증 스크린샷으로 확정).
_MEMBER_HEADER_H = 27.5
_MEMBER_ROW_H = 29.2
_CHECKBOX_X_OFFSET = 10
# '결재' 라벨 = 전표 헤더의 세로 셀(실측 w40×h110) — 형태(h)로 판별한다. 모달 툴바/탭의
# '결재'(h≈20~30)와 확실히 갈리고, 창 폭이 달라져도 유효하다(종전 x<900 은 좌표 취약).
_LABEL_MIN_H = 60
# 배치(다건) EAP 문서는 본문 렌더가 느리다 — 네비바만 뜬 시점에 스캔하면 라벨이 아직 없다
# (라이브 45건 실패 2026-08-21). 라벨 출현까지 폴링한다.
_LABEL_CAP_S = 15.0
# 모달 제목 표출 후 RealGrid 캔버스 초기화까지의 지연(라이브 배치 실측) — 출현까지 폴링.
_CANVAS_CAP_S = 10.0
# 모달 헤더 행(툴바)·저장 버튼 렌더 대기 상한.
_TOOLBAR_CAP_S = 10.0
_POLL_INTERVAL_S = 0.5
# 저장 후 다이얼로그 문구 판정 — 위험 키워드가 있거나 무해 키워드가 전무하면 중단.
_DANGER_KEYWORDS = ("탈퇴", "초기화", "영구", "삭제")
_BENIGN_KEYWORDS = ("저장", "결재", "라인")


async def _leaves(child: Any) -> list[dict]:
    try:
        return await child.evaluate(EAP_LEAF_DUMP_JS) or []
    except Exception:  # noqa: BLE001 — 네비게이션 중 evaluate 실패 → 빈 목록으로 재시도 유도.
        return []


def _modal_open(leaves: list[dict]) -> bool:
    return any(leaf.get("text") == MODAL_TITLE for leaf in leaves)


def _count_exact(leaves: list[dict], text: str) -> int:
    return sum(1 for leaf in leaves if leaf.get("text") == text)


async def _wait_modal_open(child: Any, *, attempts: int = 10) -> bool:
    for _ in range(attempts):
        await asyncio.sleep(_POLL_INTERVAL_S)
        if _modal_open(await _leaves(child)):
            return True
    return False


async def designate_approval_line(
    child: Any,
    target_name: str,
    member_row_index: int,
    *,
    stage: str = "결재",
) -> dict:
    """결제창에서 결재라인 지정 모달을 열어 ``target_name`` 을 ``stage`` 라인에 추가한다.

    member_row_index: 인원표(캔버스) 0-based 행 인덱스 — 부서 인원 순서 실측값을 호출자가
    준다. 캔버스라 이름으로 행을 읽을 수 없으므로, 오지정은 마지막 검증(전표 헤더에
    target_name 리프가 **새로** 나타났는가)이 잡는다. 실패 시 호출자는 상신하지 말 것.

    반환 {ok, target, reason?, count_before?, count_after?}.
    """
    before = await _leaves(child)
    if not before:
        return {"ok": False, "target": target_name, "reason": "결제창 리프 덤프 실패(렌더 미완?)"}

    # 1) 모달 오픈 — 1차: 결재란 사용자 셀(td.lineUserInfo, 텍스트 있는 첫 셀) DOM 클릭
    # (사용자 시연 실측 2026-08-21 — Playwright 자동 대기가 배치 본문 렌더 지연을 흡수한다).
    # 폴백: 전표 헤더 '결재' 라벨(세로 셀 h≥60 형태 판별)을 출현까지 폴링해 클릭.
    if not _modal_open(before):
        opened = False
        try:
            cell = child.locator("td.lineUserInfo").filter(has_text=re.compile(r"\S")).first
            await cell.click(timeout=int(_LABEL_CAP_S * 1000))
            opened = await _wait_modal_open(child)
        except Exception:  # noqa: BLE001 — 셀 미발견/스텁 child → 폴백 경로.
            opened = False
        if not opened:
            label = None
            deadline = asyncio.get_event_loop().time() + _LABEL_CAP_S
            leaves_now = before
            while True:
                cands = [
                    leaf
                    for leaf in leaves_now
                    if leaf.get("text") == "결재" and leaf.get("h", 0) >= _LABEL_MIN_H
                ]
                if cands:
                    label = min(cands, key=lambda leaf: leaf.get("y", 0))
                    break
                if asyncio.get_event_loop().time() >= deadline:
                    seen = [
                        {k: leaf.get(k) for k in ("x", "y", "w", "h")}
                        for leaf in leaves_now
                        if leaf.get("text") == "결재"
                    ]
                    return {
                        "ok": False,
                        "target": target_name,
                        "reason": (
                            f"결재라인 모달 진입 실패 — lineUserInfo 셀도, '결재' 라벨"
                            f"(h≥{_LABEL_MIN_H})도 {_LABEL_CAP_S:.0f}s 내 찾지 못했습니다"
                            f" — 관측된 '결재' 리프: {seen or '없음'}"
                        ),
                    }
                await asyncio.sleep(_POLL_INTERVAL_S)
                leaves_now = await _leaves(child)
            try:
                await child.mouse.click(label["x"], label["y"])
            except Exception as exc:  # noqa: BLE001 — 클릭 실패는 실패 사유로 반환.
                return {"ok": False, "target": target_name, "reason": f"'결재' 라벨 클릭 실패: {str(exc)[:ERR_MAX]}"}
            if not await _wait_modal_open(child):
                return {"ok": False, "target": target_name, "reason": "결재라인 지정 모달이 열리지 않았습니다."}

    # 지정 전 기준선 — 모달이 뜬 시점의 덤프(본문 렌더 완료 보장). 인원표·결재선 그리드는
    # 캔버스라 DOM 리프에 이름이 없고, 대상 이름 리프는 저장 후 전표 헤더에만 새로 생긴다.
    count_before = _count_exact(await _leaves(child), target_name)

    # 2) 인원표 캔버스에서 대상 행 체크박스 클릭(픽셀 산식).
    # 모달 제목이 뜬 뒤에도 RealGrid 캔버스 초기화가 수 초 늦을 수 있어(라이브 배치 실측
    # 2026-08-21 — 단발 조회는 "캔버스 미발견" 실패) 출현까지 폴링한다. 모달 캔버스는 정확히
    # 2개(인원표 상단·결재선 하단, 둘 다 w>400 — 프로브 실측 y149/y423)라 **넓은 캔버스 중
    # 최상단(min y)** 이 인원표다(절대 y 기준은 창 크기에 취약해 쓰지 않는다).
    person = None
    deadline = asyncio.get_event_loop().time() + _CANVAS_CAP_S
    while True:
        try:
            canvases = await child.evaluate(EAP_CANVAS_RECTS_JS) or []
        except Exception:  # noqa: BLE001
            canvases = []
        wide = [c for c in canvases if c.get("w", 0) > 400]
        if wide:
            person = min(wide, key=lambda c: c.get("y", 0))
            break
        if asyncio.get_event_loop().time() >= deadline:
            return {
                "ok": False,
                "target": target_name,
                "reason": (
                    f"인원표 캔버스를 {_CANVAS_CAP_S:.0f}s 내 찾지 못했습니다 — "
                    f"관측된 캔버스: {canvases or '없음'}"
                ),
            }
        await asyncio.sleep(_POLL_INTERVAL_S)
    cb_x = person["x"] + _CHECKBOX_X_OFFSET
    cb_y = person["y"] + _MEMBER_HEADER_H + member_row_index * _MEMBER_ROW_H + _MEMBER_ROW_H / 2
    try:
        await child.mouse.click(cb_x, cb_y)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "target": target_name, "reason": f"인원 체크 클릭 실패: {str(exc)[:ERR_MAX]}"}
    await asyncio.sleep(0.5)

    # 3) 상단 툴바 '결재' 클릭 → 결재선에 추가.
    # 절대 y 기준은 창 크기에 취약하다(라이브 배치 실측 2026-08-21 — y<150 에 후보 0개).
    # 모달 제목 리프를 **앵커**로 삼아 그 바로 아래 헤더 행(title.y ~ +150) 안에서, 전표 헤더의
    # 세로 라벨(h≥60)을 제외하고 정확일치 1개를 찾는다. 하단 탭('결재'/'수신참조'/'시행')은
    # 모달 중단 이하라 이 창에 들어오지 않는다. 렌더 지연 대비 폴링.
    toolbar_btn = None
    deadline = asyncio.get_event_loop().time() + _TOOLBAR_CAP_S
    while True:
        now = await _leaves(child)
        title = next((leaf for leaf in now if leaf.get("text") == MODAL_TITLE), None)
        if title is None:
            return {"ok": False, "target": target_name, "reason": "모달이 예기치 않게 닫혔습니다(제목 미발견)."}
        cands = [
            leaf
            for leaf in now
            if leaf.get("text") == stage
            and leaf.get("h", 0) < _LABEL_MIN_H
            and title.get("y", 0) < leaf.get("y", 0) <= title.get("y", 0) + 150
        ]
        if len(cands) == 1:
            toolbar_btn = cands[0]
            break
        if asyncio.get_event_loop().time() >= deadline:
            seen = [
                {k: leaf.get(k) for k in ("x", "y", "w", "h")}
                for leaf in now
                if leaf.get("text") == stage
            ]
            return {
                "ok": False,
                "target": target_name,
                "reason": (
                    f"모달 툴바 '{stage}' 버튼이 유일하게 잡히지 않습니다"
                    f"(후보 {len(cands)}개, 제목 y={title.get('y')}, 관측 '{stage}' 리프: {seen or '없음'})."
                ),
            }
        await asyncio.sleep(_POLL_INTERVAL_S)
    try:
        await child.mouse.click(toolbar_btn["x"], toolbar_btn["y"])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "target": target_name, "reason": f"툴바 '{stage}' 클릭 실패: {str(exc)[:ERR_MAX]}"}
    await asyncio.sleep(0.8)

    # 4) '저장' 클릭 → (있으면) 소형 다이얼로그 처리 → 모달 닫힘 대기. 렌더 지연 대비 폴링.
    save = None
    deadline = asyncio.get_event_loop().time() + _TOOLBAR_CAP_S
    while save is None:
        now = await _leaves(child)
        save = next((leaf for leaf in now if leaf.get("text") == "저장"), None)
        if save is None:
            if asyncio.get_event_loop().time() >= deadline:
                return {"ok": False, "target": target_name, "reason": "모달 '저장' 버튼을 찾지 못했습니다."}
            await asyncio.sleep(_POLL_INTERVAL_S)
    try:
        await child.mouse.click(save["x"], save["y"])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "target": target_name, "reason": f"'저장' 클릭 실패: {str(exc)[:ERR_MAX]}"}

    for _ in range(10):
        try:
            dialogs = await child.evaluate(EAP_SMALL_DIALOG_JS) or []
        except Exception:  # noqa: BLE001
            dialogs = []
        if dialogs:
            texts = " ".join(d.get("text", "") for d in dialogs)
            if any(kw in texts for kw in _DANGER_KEYWORDS) or not any(
                kw in texts for kw in _BENIGN_KEYWORDS
            ):
                try:
                    await child.keyboard.press("Escape")
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "ok": False,
                    "target": target_name,
                    "reason": f"저장 후 예상 밖 다이얼로그 — 중단: {texts[:ERR_MAX]}",
                }
            leaves_dlg = await _leaves(child)
            confirm = next((leaf for leaf in leaves_dlg if leaf.get("text") in ("확인", "예")), None)
            if confirm is not None:
                try:
                    await child.mouse.click(confirm["x"], confirm["y"])
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(0.8)
        elif not _modal_open(await _leaves(child)):
            break
        await asyncio.sleep(0.4)
    else:
        return {"ok": False, "target": target_name, "reason": "저장 후 모달이 닫히지 않았습니다."}

    # 5) 검증 게이트 — 전표 헤더에 대상 이름 리프가 **새로** 나타났는가(정확일치 수 증가).
    # 모달이 닫힌 직후 헤더 재렌더가 수백 ms 늦을 수 있어(라이브 실측 2026-08-21 — 즉시 덤프는
    # 0건, 스크린샷 시점엔 반영) 단발 판정이 아니라 폴링한다.
    count_after = count_before
    for _ in range(10):
        count_after = _count_exact(await _leaves(child), target_name)
        if count_after > count_before:
            return {
                "ok": True,
                "target": target_name,
                "count_before": count_before,
                "count_after": count_after,
            }
        await asyncio.sleep(0.5)
    return {
        "ok": False,
        "target": target_name,
        "reason": (
            f"저장 후 전표 헤더에서 '{target_name}' 추가를 확인하지 못했습니다"
            f"(전 {count_before} → 후 {count_after}) — 오지정 가능, 상신 금지."
        ),
        "count_before": count_before,
        "count_after": count_after,
    }
