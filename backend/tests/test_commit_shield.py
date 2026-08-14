"""shielded_commit — 저장 확정 구간 취소 보호 헬퍼 테스트.

시나리오: ① 취소 없음(완전 투명) ② 확정 중 취소 1회/반복 주입(내부 완료까지 보호·안내
1회·완료 후 CancelledError 재발생) ③ cap 초과(내부 cancel+경고 후 재발생) ④ 내부 자체
예외(취소 없으면 그대로 전파) ⑤ 저장 노드 통합(가짜 저장 코루틴으로 취소 시
'완료 후 중단' 로그 확인 — trip_domestic·card_collect).
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.agents.common.commit_shield import shielded_commit

_SETTLE_S = 0.01  # 취소 주입이 이벤트 루프를 한 바퀴 돌아 전달되기에 충분한 짧은 대기.


def _q() -> asyncio.Queue:
    return asyncio.Queue()


def _log_msgs(q: asyncio.Queue) -> list[str]:
    """큐에 쌓인 프레임 중 log 프레임의 메시지만 추출."""
    out: list[str] = []
    while not q.empty():
        ev = q.get_nowait()
        if "log" in ev:
            out.append(str(ev["log"]))
    return out


# ── ① 취소 없음 — 완전 투명 ──────────────────────────────────────────────────
async def test_no_cancel_returns_result_transparently():
    q = _q()

    async def _save():
        return {"ok": True, "via": "F7"}

    out = await shielded_commit(_save, events=q, label="저장(F7)")
    assert out == {"ok": True, "via": "F7"}
    assert _log_msgs(q) == []  # 정상 경로에선 로그도 안내도 없다(오버헤드 0).


async def test_no_cancel_accepts_bare_coroutine():
    async def _save():
        return {"ok": False, "reason": "거부"}

    # 팩토리가 아닌 생(生) 코루틴도 받는다 — 거부 dict 도 예외 없이 그대로 반환.
    out = await shielded_commit(_save(), events=_q(), label="저장(F7)")
    assert out == {"ok": False, "reason": "거부"}


# ── ④ 내부 자체 예외 — 취소 없으면 그대로 전파 ───────────────────────────────
async def test_inner_exception_propagates_without_cancel():
    async def _boom():
        raise RuntimeError("ERP down")

    with pytest.raises(RuntimeError, match="ERP down"):
        await shielded_commit(_boom, events=_q(), label="저장(F7)")


# ── ② 확정 중 취소 — 내부 완료까지 보호 ─────────────────────────────────────
async def test_cancel_during_commit_protects_until_done():
    q = _q()
    started = asyncio.Event()
    release = asyncio.Event()
    done_flag: dict = {}

    async def _save():
        started.set()
        await release.wait()
        done_flag["done"] = True
        return {"ok": True}

    task = asyncio.create_task(shielded_commit(_save, events=q, label="저장(F7)"))
    await started.wait()
    task.cancel()
    await asyncio.sleep(_SETTLE_S)  # 취소가 shield await 에 전달 → 억류 진입.
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done_flag.get("done") is True  # 취소에도 내부 저장은 끝까지 갔다.
    logs = _log_msgs(q)
    assert sum("확정 중 — 완료 후 중단됩니다" in m for m in logs) == 1
    assert any("완료 후 중단(저장됨)" in m for m in logs)


async def test_repeated_cancel_injection_absorbed(caplog):
    """반복 주입되는 CancelledError 를 루프로 흡수 — 한 번만 catch 하면 뚫리는 케이스."""
    caplog.set_level(logging.INFO, logger="app.agents.common.commit_shield")
    q = _q()
    started = asyncio.Event()
    release = asyncio.Event()
    done_flag: dict = {}

    async def _save():
        started.set()
        await release.wait()
        done_flag["done"] = True
        return {"ok": True}

    task = asyncio.create_task(shielded_commit(_save, events=q, label="저장(F7)"))
    await started.wait()
    task.cancel()  # 1차(예: 워치독)
    await asyncio.sleep(_SETTLE_S)
    task.cancel()  # 2차(예: 러너 finally) — 억류 대기 중 재주입
    await asyncio.sleep(_SETTLE_S)
    task.cancel()  # 3차 — 그래도 뚫리지 않아야 한다
    await asyncio.sleep(_SETTLE_S)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done_flag.get("done") is True
    logs = _log_msgs(q)
    assert sum("확정 중 — 완료 후 중단됩니다" in m for m in logs) == 1  # 안내는 1회만.
    assert any("완료 후 중단(저장됨)" in m for m in logs)
    # 재주입이 실제로 흡수됐는지(2차 이후) 서버 로그로 확인.
    assert any("취소 재주입 흡수" in r.message for r in caplog.records)


async def test_cancel_with_rejection_result_logs_not_saved():
    """내부가 거부 dict({"ok": False})로 끝나면 '저장 안 됨'으로 확정 로그."""
    q = _q()
    started = asyncio.Event()
    release = asyncio.Event()

    async def _save():
        started.set()
        await release.wait()
        return {"ok": False, "reason": "회계일 마감"}

    task = asyncio.create_task(shielded_commit(_save, events=q, label="저장(F7)"))
    await started.wait()
    task.cancel()
    await asyncio.sleep(_SETTLE_S)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    logs = _log_msgs(q)
    assert any("거부 후 중단(저장 안 됨)" in m and "회계일 마감" in m for m in logs)


async def test_cancel_with_inner_exception_logs_reason_and_reraises_cancel():
    """취소 억류 중 내부가 자체 예외로 끝나면 실패 사유를 로그로 확정하고 취소 흐름 복귀."""
    q = _q()
    started = asyncio.Event()
    release = asyncio.Event()

    async def _save():
        started.set()
        await release.wait()
        raise RuntimeError("계정 불일치")

    task = asyncio.create_task(shielded_commit(_save, events=q, label="저장(F7)"))
    await started.wait()
    task.cancel()
    await asyncio.sleep(_SETTLE_S)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    logs = _log_msgs(q)
    assert any("실패 후 중단" in m and "계정 불일치" in m for m in logs)


# ── ③ cap 초과 — 내부 cancel + 경고 후 재발생 ────────────────────────────────
async def test_cap_exceeded_cancels_inner_and_reraises():
    q = _q()
    started = asyncio.Event()
    inner_cancelled: dict = {}

    async def _save():
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            inner_cancelled["yes"] = True
            raise
        return {"ok": True}

    task = asyncio.create_task(
        shielded_commit(_save, events=q, label="저장(F7)", cap_s=0.2)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inner_cancelled.get("yes") is True  # cap 초과 시 내부 task 를 취소했다.
    logs = _log_msgs(q)
    assert any("확정 미완" in m and "ERP 상태 확인 필요" in m for m in logs)


# ── ⑤ 저장 노드 통합 — 가짜 저장 코루틴으로 취소 시 '완료 후 중단' 로그 ──────
class _TripSavePage:
    """trip save_doc 의 F7 사전 팝업 검증만 통과시키는 최소 가짜 page."""

    async def evaluate(self, js_src, arg=None):
        from nbkit.omnisol import js_lib

        if js_src is js_lib.POPUP_COUNT_JS:
            return 0
        return True

    async def wait_for_timeout(self, ms):
        return None


async def test_trip_save_node_cancel_during_f7_keeps_commit(monkeypatch):
    from app.agents.trip_domestic.nodes import save as trip_save
    from app.agents.trip_domestic.nodes.save import make_save_doc_node

    q = _q()
    started = asyncio.Event()
    release = asyncio.Event()
    done_flag: dict = {}

    async def _slow_save(page, confirm):
        started.set()
        await release.wait()
        done_flag["done"] = True
        return {"ok": True, "modals_seen": []}

    monkeypatch.setattr(trip_save.card_steps, "save_document", _slow_save)
    node = make_save_doc_node()
    task = asyncio.create_task(node({"events": q, "page": _TripSavePage(), "filled": 1}))
    await started.wait()
    task.cancel()
    await asyncio.sleep(_SETTLE_S)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done_flag.get("done") is True  # F7 확정 구간은 취소에도 끝까지 갔다.
    logs = _log_msgs(q)
    assert any("확정 중 — 완료 후 중단됩니다" in m for m in logs)
    assert any("완료 후 중단(저장됨)" in m for m in logs)


async def test_card_save_node_cancel_during_f7_keeps_commit(monkeypatch):
    from app.agents.card_collect.nodes import save as card_save
    from app.agents.card_collect.nodes.save import make_save_final_node

    q = _q()
    started = asyncio.Event()
    release = asyncio.Event()
    done_flag: dict = {}

    async def _slow_save(page, confirm):
        started.set()
        await release.wait()
        done_flag["done"] = True
        return {"ok": True, "via": "F7", "modals_seen": []}

    monkeypatch.setattr(card_save.steps, "save_document", _slow_save)
    node = make_save_final_node()
    task = asyncio.create_task(
        node({"events": q, "page": object(), "filled": 1, "pass2_filled": 0})
    )
    await started.wait()
    task.cancel()
    await asyncio.sleep(_SETTLE_S)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done_flag.get("done") is True
    logs = _log_msgs(q)
    assert any("확정 중 — 완료 후 중단됩니다" in m for m in logs)
    assert any("완료 후 중단(저장됨)" in m for m in logs)
