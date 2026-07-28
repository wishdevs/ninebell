"""결의구분 세팅 + **반영 확인** 노드(공유 set_gubun 노드 래핑).

공유 노드(`common.nodes.make_set_gubun_node`)는 kendo 세터의 {ok:true}(= "옵션을 찾아 value 를
넣었다")와 **고정 1.5s 대기**만으로 성공을 돌려준다. 결의구분은 change 핸들러가 문서 스키마와
관리항목을 재구성하는 연쇄 필드라, 위젯이 값을 되돌리거나 서버 리로드로 초기화되면 세터는
성공인데 화면은 **다른 문서 종류**로 남는다. 그 상태로 진행하면 경조금이 아닌 결의서를 채워
F7 저장까지 가서야 드러난다(가장 비싼 조용한 실패 — 되돌리려면 사람이 전표를 지워야 한다).

그래서 세팅 직후 드롭다운의 **현재 선택 텍스트**를 읽어 확정한다(js_lib.SELECTED_TEXT_JS).
결의구분은 작성 대상(문서 종류)을 정의하므로 **불일치 = 하드 실패**, 리더가 select 자체를 못
찾으면(세션·버전차) 경고 후 진행한다.
"""

from __future__ import annotations

from typing import Any

from nbkit.omnisol import selectors, verify

from app.agents.common.nodes import make_set_gubun_node
from app.live.events import emit_log, emit_step


def _unreadable_select(v: Any) -> bool:
    """SELECTED_TEXT_JS 가 ok:false = select 미발견(값이 틀린 게 아니라 확인 불가)."""
    return not (isinstance(v, dict) and v.get("ok"))


def make_confirmed_set_gubun_node(gubun_text: str):
    """공유 set_gubun 노드 실행 → 드롭다운 선택 텍스트 재확인. 노드 키는 그대로 'set_gubun'."""
    base_node = make_set_gubun_node(gubun_text)

    async def set_gubun(state: dict) -> dict:
        if state.get("error"):
            return {}
        out = await base_node(state)
        if out.get("error"):  # 세팅 자체가 실패 — 공유 노드가 이미 step/log 를 남겼다.
            return out
        events = state["events"]
        res = await verify.confirm_select(
            state["page"],
            selectors.GUBUN_SELECT,
            gubun_text,
            unknown_when=_unreadable_select,
        )
        if res:
            return out
        if res.unknown:
            # 확인 불가 — 진행하되 '확정됨'이라고 단정하지 않는다(로그에 미확인으로 남긴다).
            await emit_log(events, f"결의구분 {res.reason} — 미확인 상태로 진행합니다.", "warn")
            return out
        await emit_step(events, "set_gubun", "failed")
        return {**out, "error": f"결의구분 반영 실패: {res.reason}"}

    return set_gubun
