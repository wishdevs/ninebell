"""차단 모달(Kendo .k-window) 일괄 해제 — 확인/예 계열 클릭 폴링.

card_collect 에서 승격(2026-07-05) — 모든 옴니솔 에이전트 공용. 로직은 card_collect
실전 검증본 그대로(동작 불변)이며, in-page JS 는 :mod:`nbkit.omnisol.js_lib` 단일 소스
(MODALS_SNAPSHOT_JS/MODAL_BTN_BOX_JS)를 쓴다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from nbkit.omnisol import js_lib, verify

__all__ = ["dismiss_blocking_modals", "dismiss_notice_popup", "watch_notice_popup"]

logger = logging.getLogger(__name__)


async def dismiss_blocking_modals(page: Any, *, rounds: int = 6) -> list[dict]:
    """화면을 막는 잔여 확인 모달('예산현황' 등)을 '확인'/'예'로 닫는다.

    실전 실측(2026-07-02 2차 런): 카드팝업 '적용' 후 팝업 닫힘보다 **늦게** '예산현황'
    모달이 떠서, 다음 단계(F3·증빙 코드피커)가 막혀 TypeError 로 실패했다. 확인 계열만
    클릭(취소/아니오 금지). 닫은 모달 스냅샷 목록 반환.

    속도: 첫 체크는 대기 없이 즉시, 이후 400ms 폴링. **2초 연속 조용**하면 종료(지연 모달
    관찰 창 유지, 기존 최소 3s → 2s). 상한 = rounds×1.5s(기존 시그니처 호환).
    """
    seen: list[dict] = []
    cap_ms = rounds * 1_500
    interval = 400
    quiet_needed = 2_000  # 이 시간 동안 모달이 안 뜨면 종료(지연 출현 관찰 창)
    waited = 0
    quiet = 0
    while True:
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)  # 첫 체크 즉시(고정 1.5s 선대기 제거)
        if modals:
            quiet = 0
            seen.extend(modals)
            for label in ("확인", "예"):
                btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
                if btn:
                    await page.mouse.click(btn["x"], btn["y"])
                    break
        elif quiet >= quiet_needed:
            break
        if waited >= cap_ms:
            break
        # ⚠ 시간축 규율(2026-08-07): '2초 연속 조용' 관찰창은 실시간이어야 한다 —
        #   page.wait_for_timeout 은 delay_scale 로 축소돼(card 0.15 = 실 300ms) 지연 출현
        #   모달을 놓친다. 실패-경로 관찰 대기이므로 실시간 sleep 을 쓴다.
        await verify.DEFAULT_SLEEP(interval / 1000)
        waited += interval
        if not modals:
            quiet += interval
    return seen


async def dismiss_notice_popup(
    page: Any, *, appear_cap_ms: int = 2_000, interval: int = 300, close_cap_ms: int = 4_000
) -> bool:
    """로그인 직후 뜨는 '공지' 레이어 팝업을 '하루동안 보지 않기' 체크 후 '닫기'로 닫는다.

    전 에이전트 공통(2026-07-21 프로브 실측): 이 팝업은 로그인 직후 ~1.5s 뒤 렌더되며 Kendo
    백드롭(.k-overlay)으로 **화면 전체를 차단**한다 → 로그인 성공 직후·다른 어떤 조작(아바타
    클릭·메뉴 진입)보다 **먼저** 닫아야 한다. 영속은 브라우저 localStorage 단독이라 새 브라우저
    로 시작하는 헤드리스 세션에선 **매번 재현**된다.

    고유 앵커 #close-today-chk 로만 판정(``dismiss_blocking_modals`` 는 '확인/예' 확정 전용이라
    '닫기' 버튼을 못 눌러 이 팝업을 못 닫는다). 팝업이 없으면(오늘 이미 닫힘/공지 없음) no-op.
    자체 방어(evaluate 실패 등은 삼켜 로그인 자체를 막지 않는다).

    **검증된 닫기(2026-07-23)**: 종전에는 체크·닫기 클릭을 쏘고 끝이라(발사 후 미검증) 진입
    애니메이션 중 좌표가 어긋나 닫기가 빗나가면 팝업이 남은 채 다음 단계로 넘어갔고 — 사용자
    관찰: "첫 화면에서 체크만 되고, 메뉴 이동 후에야 (JIT 방어가) 닫는" 이중 처리. 영속
    (localStorage)도 닫기까지 완료돼야 기록되므로 첫 처리 미완이면 재출현한다. 이제
    ① 체크는 클릭 후 checked 실측으로 확정(빗나감 재시도), ② 닫기는 클릭 직전 좌표 재평가 +
    팝업 소멸 폴 검증(미소멸 시 재클릭, 상한 close_cap_ms)으로 **첫 화면에서 확정 완료**한다.
    반환 True=닫힘 검증 완료 / False=팝업 없음 또는 닫기 실패(후속 JIT 방어가 재시도).
    """
    boxes = None
    # ⚠ 상한 판정은 time.monotonic 실시간이다 — page.wait_for_timeout 은 _ScaledPage 가
    # delay_scale 로 축소하므로, 명목 카운터(waited += interval)로 세면 card-collect(0.15)에서
    # 관찰창 2.5s 가 실 ~375ms 로 붕괴해 ~1.5s 뒤 비동기 렌더되는 공지를 놓친다(codepicker.py
    # _wait_picker_rows_stable 의 2026-07-04 회귀와 동일 함정). 폴 간격만 스케일되게 둔다.
    t0 = time.monotonic()
    # appear_cap_ms=0 이면 대기 없이 1회만 확인(just-in-time 재확인용 — 피커 클릭 직전 등).
    while True:
        try:
            boxes = await page.evaluate(js_lib.NOTICE_POPUP_BOXES_JS)
        except Exception:  # noqa: BLE001 — best-effort, 로그인 진행 우선.
            return False
        if boxes or (time.monotonic() - t0) * 1_000 >= appear_cap_ms:
            break
        await page.wait_for_timeout(interval)
    if not boxes:
        return False
    try:
        # ── 1) '하루동안 보지 않기' 체크 확정 — 클릭 후 재평가로 checked 실측(최대 3회) ──
        for _ in range(3):
            if boxes.get("checked"):
                break
            await page.mouse.click(boxes["checkbox"]["x"], boxes["checkbox"]["y"])
            await page.wait_for_timeout(200)
            boxes = await page.evaluate(js_lib.NOTICE_POPUP_BOXES_JS)
            if not boxes:
                return True  # 팝업이 사라짐(이미 닫힘) — 목적 달성.
        # ── 2) 닫기 — 클릭 직전 좌표(재평가분) 사용 + 소멸 폴 검증, 미소멸 시 재클릭 ──
        # 상한도 monotonic 실시간(닫힘 애니메이션은 서버/브라우저 실시간이라 스케일 무관).
        t_close = time.monotonic()
        while True:
            await page.mouse.click(boxes["close"]["x"], boxes["close"]["y"])
            await page.wait_for_timeout(400)
            boxes = await page.evaluate(js_lib.NOTICE_POPUP_BOXES_JS)
            if not boxes:
                return True  # 닫힘 검증 완료 — localStorage 영속까지 확정.
            if (time.monotonic() - t_close) * 1_000 >= close_cap_ms:
                return False  # 상한 — 후속 JIT 방어가 재시도한다(무한 대기 금지).
    except Exception:  # noqa: BLE001 — 닫기 실패해도 로그인 자체는 진행.
        return False


def watch_notice_popup(page: Any, *, appear_cap_ms: int = 4_000) -> Any:
    """공지 팝업을 **배경에서** 기다렸다 닫는다 — 진입 흐름을 멈추지 않는다.

    ``dismiss_notice_popup`` 과 같은 일을 하되 **await 하지 않는다**. 반환한 task 는 호출부가
    보관했다가(선택) 나중에 취소하거나 결과를 회수할 수 있다.

    ⚠ 왜 필요한가(2026-07-28 실측): 공지 팝업은 로그인 완료 **1.6초 뒤**에 뜨고, 화면 전환
    뒤에는 (적어도 이 계정·이 화면에선) 다시 뜨지 않는다. 그런데 진입 경로가 두 곳에서
    차단형으로 기다렸다 —
      · 로그인 직후 관찰창 4s → 실측 2.4~3.3s 소요(팝업을 실제로 잡음)
      · 메뉴 도착 후 관찰창 2.5s → 실측 2.8s 소요, 그런데 **팝업이 안 떠서 전부 헛대기**
    합쳐 진입 11.8s 중 5s 이상이 '팝업을 기다리는 시간'이었다. 배경으로 돌리면 팝업은 여전히
    뜨는 즉시 닫히고, 그 사이 프로필 읽기·사용자유형 전환·메뉴 진입이 진행된다.

    ⚠ 안전: 클릭을 가로채는 레이스 방어는 그대로다 — 실제 클릭 직전의 JIT 확인
    (``dismiss_notice_popup(page, appear_cap_ms=0)``, 피커/탭 열기 직전)은 **차단형으로 유지**
    한다. 이 배경 감시는 그 앞단의 '미리 치워두기'를 비동기화할 뿐이다.

    이벤트 루프가 없으면(동기 스텁 등) None 을 돌려주고 아무것도 하지 않는다.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return None

    async def _run() -> None:
        try:
            closed = await dismiss_notice_popup(page, appear_cap_ms=appear_cap_ms)
            if closed:
                logger.info("공지 팝업을 배경에서 닫았습니다.")
        except Exception:  # noqa: BLE001 — 배경 작업 실패가 본 흐름을 깨선 안 된다.
            logger.debug("공지 팝업 배경 감시 실패(무시)", exc_info=True)

    try:
        return asyncio.create_task(_run())
    except RuntimeError:
        return None
