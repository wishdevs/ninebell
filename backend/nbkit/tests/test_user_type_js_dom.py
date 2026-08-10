"""사용자유형 리더 JS 의 **실행 동작** 검증 — 최소 DOM 스텁 위에서 node 로 직접 돌린다.

파이썬 FakePage 는 JS 를 실행하지 않으므로 리더의 '의미'만 흉내낼 수 있다. 그런데 이번 장애
(H1)의 원인은 정확히 **JS 안의 탐색 조건**이었다 — 그래서 그 부분만은 문자열 검사가 아니라
실행으로 고정한다. node 가 없으면 skip(문자열 구조 검사는 test_user_type_resolution.py 가 담당).

검증 대상(2026-08-01 라이브 실측 반영):
  * 현재 선택이 `SCM-구매`(‘사용자’ 없음)여도 드롭다운 위젯을 찾는다(H1 회귀).
  * select 탐색 1순위 `#ch_group`, 2순위 사용자 패널 스코프(라벨에 '사용자'가 하나도 없어도).
  * ⑦ kendo API 부재(window.jQuery 없음) 시 인접 `.k-dropdown` → 조상 스캔 → native select
    폴백으로 좌표·표시 텍스트를 계속 얻는다.
  * li 매칭 — 인덱스 접미사(`'SCM-구매 3'`) 흡수, 정규식 메타문자 문자 그대로, 모호하면 null.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap

import pytest

from nbkit.omnisol import js_lib

_NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(_NODE is None, reason="node 미설치 — JS 실행 검증 skip")

# 최소 DOM 스텁 — querySelector/getElementById/getBoundingClientRect 만 지원한다.
# 실제 브라우저가 아니므로 '셀렉터'는 스텁이 이해하는 소수 패턴으로 한정(리더가 쓰는 것 전부).
_DOM_STUB = r"""
function el(spec) {
  const e = Object.assign(
    { id: '', tagName: 'DIV', className: '', innerText: '', children: [], parentElement: null,
      nextElementSibling: null, options: null, selectedIndex: -1, offsetParent: {},
      rect: { x: 0, y: 0, width: 100, height: 25 } },
    spec
  );
  e.classList = { contains: c => String(e.className).split(/\s+/).includes(c) };
  e.getBoundingClientRect = () => e.rect;
  e.querySelector = sel => descend(e).find(n => matches(n, sel)) || null;
  e.querySelectorAll = sel => descend(e).filter(n => matches(n, sel));
  e.closest = () => null;
  for (const c of e.children) c.parentElement = e;
  return e;
}
function descend(node) {
  const out = [];
  for (const c of node.children) { out.push(c); out.push(...descend(c)); }
  return out;
}
// 지원 범위: 콤마 분리 + (자손 결합자는 마지막 토큰만) + tag / .class / #id / tag.class.
// 리더가 실제로 쓰는 셀렉터(li.k-item, .k-list li, .user-info-box, #ch_group …)를 덮는다.
function matches(node, sel) {
  return sel.split(',').map(s => s.trim()).filter(Boolean).some(one => {
    const last = one.split(/\s+/).pop().replace(/\[[^\]]*\]/g, '');
    const tag = (last.match(/^[a-zA-Z]+/) || [''])[0];
    if (tag && String(node.tagName).toLowerCase() !== tag.toLowerCase()) return false;
    const id = (last.match(/#([\w-]+)/) || [])[1];
    if (id && node.id !== id) return false;
    const cls = last.match(/\.([\w-]+)/g) || [];
    return cls.every(c => node.classList.contains(c.slice(1)));
  });
}
function mount(root) {
  global.document = {
    getElementById: id => descend(root).find(n => n.id === id) || null,
    querySelector: sel => root.querySelector(sel),
    querySelectorAll: sel => root.querySelectorAll(sel),
    body: root,
  };
}
function selectEl(spec, optionTexts, selectedIndex) {
  const e = el(Object.assign({ tagName: 'SELECT' }, spec));
  e.options = optionTexts.map(t => ({ text: t }));
  e.selectedIndex = selectedIndex;
  return e;
}
"""


def _run_js(script: str) -> object:
    """DOM 스텁 + 시나리오 JS 를 node 로 실행하고 마지막 console.log(JSON) 를 파싱."""
    src = _DOM_STUB + textwrap.dedent(script)
    proc = subprocess.run(
        [str(_NODE), "-e", src], capture_output=True, text=True, timeout=20, check=False
    )
    assert proc.returncode == 0, f"node 실행 실패: {proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _js(name: str) -> str:
    return f"({getattr(js_lib, name)})"


def test_dropdown_box_found_when_selection_has_no_user_suffix():
    """H1 회귀 — 현재 선택이 'SCM-구매' 라도 kendo wrapper 를 역참조해 좌표를 얻는다."""
    out = _run_js(
        f"""
        const wrapper = el({{ className: 'k-dropdown', innerText: 'SCM-구매',
                              rect: {{ x: 200, y: 50, width: 160, height: 30 }} }});
        const sel = selectEl({{ id: 'ch_group' }},
                             ['회계사용자(예외)', '인사사용자(예외)', 'SCM-구매'], 2);
        mount(el({{ children: [sel, wrapper] }}));
        global.window = {{ jQuery: () => ({{ data: () => ({{ wrapper: [wrapper] }}) }}) }};
        console.log(JSON.stringify({{
          box: {_js('UT_DROPDOWN_BOX_JS')}(),
          display: {_js('UT_DISPLAY_JS')}(),
          current: {_js('USER_TYPE_READ_JS')}(),
          options: {_js('USER_TYPE_OPTIONS_JS')}(),
        }}));
        """
    )
    assert out["box"] == {"x": 280, "y": 65}
    assert out["display"] == "SCM-구매"
    assert out["current"] == "SCM-구매"
    assert out["options"]["selectId"] == "ch_group"
    assert out["options"]["options"] == ["회계사용자(예외)", "인사사용자(예외)", "SCM-구매"]
    assert out["options"]["selectedIndex"] == 2


def test_readers_fall_back_when_kendo_api_absent():
    """⑦ window.jQuery 부재 — 인접 형제 `.k-dropdown` 으로 좌표를, 위젯도 없으면 native
    select 의 선택 옵션 텍스트로 표시를 얻는다(둘 다 텍스트 조건에 의존하지 않는다)."""
    with_sibling = _run_js(
        f"""
        const sel = selectEl({{ id: 'ch_group' }}, ['회계사용자(예외)', 'SCM-구매'], 1);
        const wrapper = el({{ className: 'k-dropdown', innerText: 'SCM-구매',
                              rect: {{ x: 0, y: 0, width: 200, height: 40 }} }});
        sel.nextElementSibling = wrapper;
        mount(el({{ children: [sel, wrapper] }}));
        global.window = {{}};  // kendo/jQuery 없음.
        console.log(JSON.stringify({{
          box: {_js('UT_DROPDOWN_BOX_JS')}(),
          display: {_js('UT_DISPLAY_JS')}(),
        }}));
        """
    )
    assert with_sibling["box"] == {"x": 100, "y": 20}
    assert with_sibling["display"] == "SCM-구매"

    no_wrapper = _run_js(
        f"""
        const sel = selectEl({{ id: 'ch_group' }}, ['회계사용자(예외)', 'SCM-구매'], 1);
        mount(el({{ children: [sel] }}));
        global.window = {{}};
        console.log(JSON.stringify({{
          box: {_js('UT_DROPDOWN_BOX_JS')}(),
          display: {_js('UT_DISPLAY_JS')}(),
        }}));
        """
    )
    assert no_wrapper["box"] is None  # 좌표는 못 얻는다(호출부가 재시도/실패 처리).
    assert no_wrapper["display"] == "SCM-구매"  # 표시 반영 신호는 select 로 계속 읽힌다.


def test_select_finder_falls_back_to_user_panel_scope():
    """id 도 '사용자' 라벨도 없는 미래 스킨 — 사용자 패널 스코프 내 select 로 찾는다."""
    out = _run_js(
        f"""
        const sel = selectEl({{ id: 'other_id' }}, ['SCM-구매', '자재-검수'], 0);
        const panel = el({{ className: 'user-info-box', children: [sel] }});
        mount(el({{ children: [panel] }}));
        global.window = {{}};
        console.log(JSON.stringify({{ options: {_js('USER_TYPE_OPTIONS_JS')}() }}));
        """
    )
    assert out["options"]["options"] == ["SCM-구매", "자재-검수"]


def _option_box_case(li_texts: list[str], label: str):
    lis = ", ".join(
        f"el({{ tagName: 'LI', className: 'k-item', innerText: {json.dumps(t)},"
        f" rect: {{ x: 0, y: {100 + i * 25}, width: 200, height: 25 }} }})"
        for i, t in enumerate(li_texts)
    )
    return _run_js(
        f"""
        mount(el({{ children: [{lis}] }}));
        console.log(JSON.stringify({{ box: {_js('UT_OPTION_BOX_JS')}({json.dumps(label)}) }}));
        """
    )["box"]


def test_option_box_absorbs_index_suffix_and_literal_metacharacters():
    live = ["회계사용자(예외) 1", "인사사용자(예외) 2", "SCM-구매 3"]
    # 실측된 인덱스 접미사(' 3')를 흡수하고 정확히 그 항목을 짚는다.
    assert _option_box_case(live, "SCM-구매") == {"x": 100, "y": 163}
    assert _option_box_case(live, "회계사용자(예외)") == {"x": 100, "y": 113}
    # 정규식이었다면 '회계AXBB사용자' 를 잘못 짚었을 라벨 — 문자 그대로 처리한다.
    meta = ["회계(A).B+사용자 1", "회계AXBB사용자 2"]
    assert _option_box_case(meta, "회계(A).B+") == {"x": 100, "y": 113}
    # 모호(같은 라벨 2개)면 임의 선택하지 않고 null.
    assert _option_box_case(["알파 1", "알파 2"], "알파") is None
    # 미발견도 null.
    assert _option_box_case(live, "총무") is None
