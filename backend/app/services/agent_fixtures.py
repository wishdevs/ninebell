"""에이전트 시드 픽스처 — 프론트 `src/lib/data/agents.ts`·`flows.ts` 이식.

사용자 요청으로 **card-chat(결의서 입력 - 카드, workflow=card-collect)**
1개만 남긴다(나머지 4개 outbound-test·card-expense·card-md·bom-lookup 제거).

타임스탬프는 프론트와 동일 앵커(NOW_ANCHOR = 2026-06-30T14:00:00+09:00 = 05:00Z)에서
상대 오프셋으로 계산해 화면 연속성을 유지한다(프론트 relativeFromNow 와 동일 의미).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_ANCHOR = datetime(2026, 6, 30, 5, 0, 0, tzinfo=UTC)  # = 2026-06-30T14:00:00+09:00


def rel(*, minutes: int = 0, hours: int = 0, days: int = 0) -> datetime:
    return _ANCHOR - timedelta(minutes=minutes, hours=hours, days=days)


def _iso(*, minutes: int = 0, hours: int = 0, days: int = 0) -> str:
    return rel(minutes=minutes, hours=hours, days=days).isoformat()


# ── 법인카드 지출결의 플로우 그래프 (flows.ts CORPORATE_CARD_FLOW 이식) ──────
_STEP_X = 212
_BASE_Y = 160


def _col(i: int) -> dict:
    return {"x": i * _STEP_X, "y": _BASE_Y}


CORPORATE_CARD_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "결의서 입력 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "kind", "kind": "step", "status": "done", "title": "결의구분 = 카드", "sub": "추가(F3)", **_col(1)},
        {"id": "date", "kind": "step", "status": "done", "title": "회계일자 세팅", "sub": "카드 사용 월", **_col(2)},
        {"id": "ev", "kind": "step", "status": "done", "title": "증빙유형 선택", "sub": "01 매입 / 02 불공", **_col(3)},
        {"id": "card", "kind": "step", "status": "done", "title": "카드내역 조회·적용", "sub": "승인일→조회→적용", **_col(4)},
        {"id": "vat", "kind": "decision", "status": "done", "title": "부가세 구분", "sub": "간이·빈칸이면 02", **_col(5)},
        {"id": "both", "kind": "decision", "status": "done", "title": "매입·불공 동시?", "sub": "둘 다면 행 분리 등록", **_col(6)},
        {"id": "rowMae", "kind": "step", "status": "done", "title": "매입 행 입력", "sub": "증빙유형 01 매입", **_col(7)},
        {"id": "rowAdd", "kind": "step", "status": "done", "title": "F3 줄 추가", "sub": "불공용 행 추가", **_col(8)},
        {"id": "rowBul", "kind": "step", "status": "done", "title": "불공 행 입력", "sub": "증빙유형 02 불공", **_col(9)},
        {"id": "budget", "kind": "step", "status": "done", "title": "예산계정 매핑", "sub": "항목별 계정 선택", **_col(10)},
        {"id": "project", "kind": "step", "status": "done", "title": "프로젝트·일괄적용", "sub": "취소 내역 포함", **_col(11)},
        {"id": "memo", "kind": "step", "status": "active", "title": "적요 작성", "sub": "자금예정일 매핑", **_col(12)},
        {"id": "save", "kind": "step", "status": "pending", "title": "저장(F7)", "sub": "결의번호 생성", **_col(13)},
        {"id": "warn", "kind": "decision", "status": "pending", "title": "저장 시 경고?", "sub": "회계일자 확인", **_col(14)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "전자결재 상신", "sub": "회계팀 + 증빙", **_col(15)},
    ],
    "edges": [
        {"id": "e-access-kind", "source": "access", "target": "kind"},
        {"id": "e-kind-date", "source": "kind", "target": "date"},
        {"id": "e-date-ev", "source": "date", "target": "ev"},
        {"id": "e-ev-card", "source": "ev", "target": "card"},
        {"id": "e-card-vat", "source": "card", "target": "vat"},
        {"id": "e-vat-both", "source": "vat", "target": "both", "label": "아니오 · 과세", "kind": "branch"},
        {"id": "e-vat-ev", "source": "vat", "target": "ev", "label": "예 ↩ 02", "kind": "loop"},
        {"id": "e-both-mae", "source": "both", "target": "rowMae", "label": "예 · 둘 다", "kind": "branch"},
        {"id": "e-mae-add", "source": "rowMae", "target": "rowAdd"},
        {"id": "e-add-bul", "source": "rowAdd", "target": "rowBul"},
        {"id": "e-bul-budget", "source": "rowBul", "target": "budget"},
        {"id": "e-both-budget", "source": "both", "target": "budget", "label": "아니오 · 한 종류", "kind": "skip"},
        {"id": "e-budget-project", "source": "budget", "target": "project"},
        {"id": "e-project-memo", "source": "project", "target": "memo"},
        {"id": "e-memo-save", "source": "memo", "target": "save"},
        {"id": "e-save-warn", "source": "save", "target": "warn"},
        {"id": "e-warn-submit", "source": "warn", "target": "submit", "label": "확인 후", "kind": "branch"},
    ],
}


# ── 출장(국내/자차) 결의 플로우 그래프 (trip-domestic 그래프의 사람용 요약) ──────
TRIP_DOMESTIC_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "결의서 입력 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "kind", "kind": "step", "status": "done", "title": "결의구분 = 출장(국내·자차)", "sub": "추가(F3)", **_col(1)},
        {"id": "date", "kind": "step", "status": "done", "title": "회계일자 세팅", "sub": "마지막 자차 사용일", **_col(2)},
        {"id": "row", "kind": "step", "status": "active", "title": "상세행 추가(F3)", "sub": "행별 반복", **_col(3)},
        {"id": "evd", "kind": "step", "status": "pending", "title": "증빙유형 선택", "sub": "10 규정에의한 비용정산", **_col(4)},
        {"id": "partner", "kind": "step", "status": "pending", "title": "거래처 입력", "sub": "통행료=공공기관 / 유류비=본인", **_col(5)},
        {"id": "budget", "kind": "step", "status": "pending", "title": "예산단위", "sub": "여비교통비-국내출장(부서×판/제)", **_col(6)},
        {"id": "project", "kind": "step", "status": "pending", "title": "프로젝트", "sub": "행별 프로젝트 선택", **_col(7)},
        {"id": "amount", "kind": "step", "status": "pending", "title": "금액·적요", "sub": "공급가(거래금액)+공급가액+합계 · 적요", **_col(8)},
        {"id": "bfc", "kind": "step", "status": "pending", "title": "상대계정거래처", "sub": "작성자 본인(부가선택 위젯)", **_col(9)},
        {"id": "more", "kind": "decision", "status": "pending", "title": "다음 행?", "sub": "남은 행이 있으면 F3 반복", **_col(10)},
        {"id": "save", "kind": "step", "status": "pending", "title": "저장(F7)", "sub": "저장 후 지속 확인", **_col(11)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "전자결재 상신", "sub": "사용자가 직접", **_col(12)},
    ],
    "edges": [
        {"id": "e-access-kind", "source": "access", "target": "kind"},
        {"id": "e-kind-date", "source": "kind", "target": "date"},
        {"id": "e-date-row", "source": "date", "target": "row"},
        {"id": "e-row-evd", "source": "row", "target": "evd"},
        {"id": "e-evd-partner", "source": "evd", "target": "partner"},
        {"id": "e-partner-budget", "source": "partner", "target": "budget"},
        {"id": "e-budget-project", "source": "budget", "target": "project"},
        {"id": "e-project-amount", "source": "project", "target": "amount"},
        {"id": "e-amount-bfc", "source": "amount", "target": "bfc"},
        {"id": "e-bfc-more", "source": "bfc", "target": "more"},
        {"id": "e-more-row", "source": "more", "target": "row", "label": "다음 행 ↩ F3", "kind": "loop"},
        {"id": "e-more-save", "source": "more", "target": "save", "label": "마지막 행", "kind": "branch"},
        {"id": "e-save-submit", "source": "save", "target": "submit", "label": "저장 후", "kind": "branch"},
    ],
}


# ── 에이전트 그룹 (2뎁스 분류 — 실행 불가, 목록 섹션·브레드크럼 전용) ────────
# '결의서입력' 문서군: 카드(실동작) + 출장(국내/자차·해외/정산서)·경조금·학자금(더미 —
# 아래 _RESOLUTION_DUMMY 참조, 구현되면 workflow_id·steps 를 채워 실동작으로 승격).
AGENT_GROUP_FIXTURES: list[dict] = [
    {
        "id": "resolution",
        "name": "결의서입력",
        "description": "지출 결의서를 종류별로 대신 작성해 저장합니다.",
        "sort_order": 0,
    },
    {
        "id": "materials",
        "name": "자재팀",
        "description": "자재 입고·분류를 대신 처리합니다.",
        "sort_order": 1,
    },
]


# ── 1개 에이전트 (card-chat 만 유지) ─────────────────────────────────────────
AGENT_FIXTURES: list[dict] = [
    {
        "id": "card-chat",
        "workflow_id": "card-collect",  # 실행 레지스트리 워크플로우 id(유일 실동작).
        "group_id": "resolution",  # '결의서입력' 그룹 소속.
        "name": "카드",
        "description": "법인카드로 쓴 내역을 불러와, 건별로 예산·프로젝트만 골라 주면 결의서로 만들어 저장까지 해 줍니다.",
        # 완료 후 사람 몫: 저장까지가 에이전트 몫이고, 저장된 결의서의 결제(승인) 상신은 사람이 한다.
        "handoff_note": "저장된 결의서는 아직 상신 전입니다. 옴니솔 결의서 화면에서 저장된 건을 확인하고, 직접 결제(승인) 상신을 진행해 주세요.",
        "drive": "browser",
        "interaction": "conversational",
        "target_system": "더존 옴니솔",
        "target_url": "erp.ninebell.co.kr",
        "status": "idle",
        "progress": 0,
        "timeout_seconds": 240,
        "elapsed_seconds": 0,
        "current_action": "대기 중 — 실행을 누르면 시작합니다",
        "run_count": 23,
        "success_rate": 89.1,
        "avg_seconds": 124,
        "last_run_at": rel(minutes=6),
        "flow_graph": CORPORATE_CARD_FLOW,
        # 실제 실행 그래프(app/agents/card_collect/graph.py = card-collect)의 16개 노드와 1:1.
        # skill 은 app/services/skills.py 카탈로그의 KEY — 직렬화 시 라벨로 풀어 UI 에 노출한다.
        # phase 는 UI Phase 아코디언(큰 단계)의 그룹 라벨 — 순서대로 연속 구간을 이룬다.
        "steps": [
            {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
            {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
            {"key": "menu_nav", "label": "결의서입력 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "전사공통(회계) 결의서 입력 화면 진입"},
            {"key": "set_gubun", "label": "결의구분: 카드", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "결의구분 드롭다운을 카드로 설정"},
            {"key": "add_row", "label": "상세행 추가(F3)", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "F3로 카드 결의 상세행 생성"},
            {"key": "set_acct_date", "label": "회계일 설정", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "수집 기간 월의 말일로 결의서 회계일 설정(전월 수집=전월 말일 / 당월=당월 말일)"},
            {"key": "open_evdn", "label": "증빙유형 선택", "skill": "codepicker", "status": "pending", "phase": "결의서 준비", "detail": "증빙유형 코드피커 열기"},
            {"key": "select_evdn", "label": "법인카드 선택", "skill": "codepicker", "status": "pending", "phase": "결의서 준비", "detail": "증빙유형 01 법인카드 선택 → 승인내역 팝업"},
            {"key": "select_all_cards", "label": "카드 전체선택", "skill": "codepicker", "status": "pending", "phase": "승인내역 조회", "detail": "카드번호 돋보기 → 전체선택 → 적용"},
            {"key": "set_period", "label": "승인일 기간", "skill": "field-input", "status": "pending", "phase": "승인내역 조회", "detail": "회계시점 결정일(설정)까지=전월 / 이후=당월 기간 설정"},
            {"key": "query", "label": "조회", "skill": "grid-read", "status": "pending", "phase": "승인내역 조회", "detail": "승인내역 조회 → 리스트 보고"},
            # collect_rows 노드 내부(intra-node) 스텝 — 그리드가 뜨기 전 AI 추천 콜이 수십 초
            # 걸려 멈춰 보이는 문제를 별도 스텝으로 가시화(ETA 타임라인의 자동 세그먼트).
            {"key": "prefill", "label": "AI 추천 준비", "skill": "ai-recommend", "status": "pending", "phase": "건별 입력", "detail": "행별 예산단위·프로젝트·적요 추천을 계산합니다 — 건수에 따라 수십 초 걸릴 수 있어요"},
            {
                "key": "collect_rows", "label": "건별 입력(그리드)", "skill": "grid-input", "status": "pending",
                "intervention": True,
                "phase": "건별 입력",
                "detail": "전 행 예산단위·프로젝트·적요를 입력하고 '입력 완료'로 제출(사용자 개입).",
            },
            # collect_rows 노드 내부(intra-node) 스텝 — 제출 후 그리드 실입력(기계 작업 ~수십 초)을
            # 개입과 분리 가시화. 제출 순간 개입이 끝났음을 레일·ETA 가 정직하게 반영한다.
            {"key": "fill_rows", "label": "입력값 반영", "skill": "grid-input", "status": "pending", "phase": "건별 입력", "detail": "제출된 예산단위·프로젝트·적요를 그리드 행별로 실제 입력"},
            {"key": "apply_doc", "label": "과세분 적용", "skill": "doc-apply", "status": "pending", "phase": "문서 반영", "detail": "과세 행 체크 → 적용 → 결의서 반영(저장 전)"},
            {"key": "switch_evdn", "label": "불공 전환", "skill": "codepicker", "status": "pending", "phase": "문서 반영", "detail": "행 추가(F3) → 증빙유형 법인카드(불공) 선택 → 재조회·행 매칭"},
            {"key": "apply_pass2", "label": "불공분 반영·적용", "skill": "grid-input", "status": "pending", "phase": "문서 반영", "detail": "입력해둔 값을 불공 행에 자동 반영 후 결의서 적용"},
            {"key": "save_final", "label": "저장(F7)", "skill": "save", "status": "pending", "phase": "저장", "detail": "과세·불공 반영분을 마지막에 한 번만 저장"},
        ],
        "logs": [
            {"key": "l1", "at": _iso(minutes=4), "level": "success", "step": "조회", "message": "조회 완료 — 승인내역 4건"},
            {"key": "l2", "at": _iso(minutes=4), "level": "info", "step": "건별 입력", "message": "AI 추천을 계산하는 중입니다…"},
            {"key": "l3", "at": _iso(minutes=3), "level": "action", "step": "건별 입력", "message": "부가세구분 분류: 과세 3건 · 불공 1건"},
            {"key": "l4", "at": _iso(minutes=3), "level": "info", "step": "건별 입력", "message": "그리드 입력 대기 — 예산단위·프로젝트·적요 입력 후 '입력 완료'"},
        ],
        "intervention": {
            "kind": "chat",
            "title": "상세 필드 — 대화형 입력",
            "prompt": "남은 상세 필드를 한 문장으로 입력하면 에이전트가 알아서 채웁니다. 부족하면 되묻습니다.",
            "options": None,
            "placeholder": "예) 적요는 6월 팀 회식, 사용부서는 마케팅, 금액 184,000원",
            "messages": [
                {"id": "m1", "role": "agent", "at": _iso(minutes=4), "text": "상세 필드를 채울게요. 적요·사용부서·금액을 한 문장으로 알려주세요."},
                {"id": "m2", "role": "user", "at": _iso(minutes=3), "text": "적요는 6월 거래처 미팅 식대로 해줘"},
                {"id": "m3", "role": "agent", "at": _iso(minutes=3), "text": "적요=‘6월 거래처 미팅 식대’로 입력했어요. 사용부서와 금액도 알려주시겠어요?"},
            ],
        },
    },
]


def _dummy_agent(
    agent_id: str,
    name: str,
    *,
    group_id: str,
    hidden: bool = False,
    target_system: str = "더존 옴니솔",
) -> dict:
    """미구현 더미 에이전트 — 자리만 잡는다(억지 장식 없음).

    workflow_id 없음 = 실행 컨트롤 비활성화(프론트 게이트), steps/logs 비움 = 계획·이력 미표시.
    구현 시 workflow_id·steps·handoff_note 를 채워 실동작으로 승격한다.
    hidden=True 면 목록/상세에서 완전히 숨긴다.
    """
    return {
        "id": agent_id,
        "workflow_id": None,
        "group_id": group_id,
        "hidden": hidden,
        "name": name,
        "description": "준비 중 — 아직 실행할 수 없습니다.",
        "drive": "browser",
        "interaction": "conversational",
        "target_system": target_system,
        "target_url": "erp.ninebell.co.kr",
        "status": "idle",
        "progress": 0,
        "timeout_seconds": 240,
        "elapsed_seconds": 0,
        "current_action": "준비 중 — 아직 실행할 수 없습니다",
        "run_count": 0,
        "success_rate": 0.0,
        "avg_seconds": 0,
        "last_run_at": None,
        "flow_graph": None,
        "steps": [],
        "logs": [],
    }


def _resolution_dummy(agent_id: str, name: str) -> dict:
    """'결의서입력' 그룹 더미 — 미검증이라 숨김(카드·국내출장만 노출, 사용자 요청 2026-07-08)."""
    return _dummy_agent(agent_id, name, group_id="resolution", hidden=True)


# ── 출장(국내/자차) — 실동작 승격(trip-domestic 워크플로우) ────────────────────
# steps 의 key 는 그래프 노드가 emit_step 하는 키와 1:1(진행 하이라이트). 증빙 선택은
# fill_rows 내부에서 행별로 처리하므로(P9 carry-over 없음) 별도 스텝을 두지 않는다.
_TRIP_DOMESTIC_FIXTURE: dict = {
    "id": "trip-domestic",
    "workflow_id": "trip-domestic",
    "group_id": "resolution",
    "name": "출장(국내/자차)",
    "description": "국내 출장에서 자차로 쓴 통행료·유류비를 입력하면 결의서로 만들어 저장합니다. 유류비는 주행거리만 넣으면 자동으로 계산됩니다.",
    "handoff_note": "저장된 결의서는 아직 상신 전입니다. 옴니솔 결의서 화면에서 저장된 건을 확인하고, 직접 결제(승인) 상신을 진행해 주세요.",
    "drive": "browser",
    "interaction": "autonomous",
    "target_system": "더존 옴니솔",
    "target_url": "erp.ninebell.co.kr",
    "status": "idle",
    "progress": 0,
    "timeout_seconds": 240,
    "elapsed_seconds": 0,
    "current_action": "대기 중 — 입력을 완료하고 실행하면 시작합니다",
    "run_count": 0,
    "success_rate": 0.0,
    "avg_seconds": 0,
    "last_run_at": None,
    "flow_graph": TRIP_DOMESTIC_FLOW,
    "steps": [
        {"key": "validate_params", "label": "입력 검증", "skill": "field-input", "status": "pending", "phase": "접속", "detail": "실행 전 폼 입력(회계일자·행)을 검증하고 유류비 금액을 계산"},
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
        {"key": "menu_nav", "label": "결의서입력 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "전사공통(회계) 결의서 입력 화면 진입"},
        {"key": "set_gubun", "label": "결의구분: 출장(국내·자차)", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "결의구분 드롭다운을 출장(국내·자차)으로 설정"},
        {"key": "add_row", "label": "상세행 추가(F3)", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "F3로 첫 결의 상세행 생성"},
        {"key": "set_acct_date", "label": "회계일 설정", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "마지막 자차 사용일로 결의서 회계일 설정"},
        {"key": "fill_rows", "label": "건별 입력", "skill": "grid-input", "status": "pending", "phase": "건별 입력", "detail": "행별 증빙(10)·거래처·예산단위·프로젝트·금액(타이핑+예산현황 확인)·적요·상대계정(부가선택 위젯)+빈행정리를 반복 입력(HITL 없음)"},
        {"key": "save_doc", "label": "저장(F7)", "skill": "save", "status": "pending", "phase": "저장", "detail": "반영된 행을 마지막에 한 번만 저장"},
    ],
    "logs": [],
}


# ── 출장(해외/정산서) 결의 플로우 그래프 (trip-overseas 그래프의 사람용 요약) ──────
TRIP_OVERSEAS_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "결의서 입력 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "kind", "kind": "step", "status": "done", "title": "결의구분 = 출장(해외·정산서)", "sub": "추가(F3)", **_col(1)},
        {"id": "date", "kind": "step", "status": "done", "title": "회계일자 세팅", "sub": "마지막 출장일(계산서일)", **_col(2)},
        {"id": "row", "kind": "step", "status": "active", "title": "상세행 추가(F3)", "sub": "행별 반복", **_col(3)},
        {"id": "evd", "kind": "step", "status": "pending", "title": "증빙유형 선택", "sub": "10 규정에의한 비용정산", **_col(4)},
        {"id": "partner", "kind": "step", "status": "pending", "title": "거래처 입력", "sub": "작성자 본인", **_col(5)},
        {"id": "budget", "kind": "step", "status": "pending", "title": "예산단위", "sub": "여비교통비-해외출장(부서×판/제)", **_col(6)},
        {"id": "project", "kind": "step", "status": "pending", "title": "프로젝트", "sub": "행별 프로젝트 선택", **_col(7)},
        {"id": "amount", "kind": "step", "status": "pending", "title": "공급가액·적요", "sub": "총 금액 + 적요(자유)", **_col(8)},
        {"id": "bfc", "kind": "step", "status": "pending", "title": "상대계정거래처", "sub": "작성자 본인(부가선택 위젯)", **_col(9)},
        {"id": "more", "kind": "decision", "status": "pending", "title": "다음 행?", "sub": "남은 행이 있으면 F3 반복", **_col(10)},
        {"id": "save", "kind": "step", "status": "pending", "title": "저장(F7)", "sub": "저장 후 지속 확인", **_col(11)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "전자결재 상신", "sub": "사용자가 직접(월별 분리 상신 주의)", **_col(12)},
    ],
    "edges": [
        {"id": "e-access-kind", "source": "access", "target": "kind"},
        {"id": "e-kind-date", "source": "kind", "target": "date"},
        {"id": "e-date-row", "source": "date", "target": "row"},
        {"id": "e-row-evd", "source": "row", "target": "evd"},
        {"id": "e-evd-partner", "source": "evd", "target": "partner"},
        {"id": "e-partner-budget", "source": "partner", "target": "budget"},
        {"id": "e-budget-project", "source": "budget", "target": "project"},
        {"id": "e-project-amount", "source": "project", "target": "amount"},
        {"id": "e-amount-bfc", "source": "amount", "target": "bfc"},
        {"id": "e-bfc-more", "source": "bfc", "target": "more"},
        {"id": "e-more-row", "source": "more", "target": "row", "label": "다음 행 ↩ F3", "kind": "loop"},
        {"id": "e-more-save", "source": "more", "target": "save", "label": "마지막 행", "kind": "branch"},
        {"id": "e-save-submit", "source": "save", "target": "submit", "label": "저장 후", "kind": "branch"},
    ],
}


# ── 출장(해외/정산서) — 실동작 승격(trip-overseas 워크플로우) ──────────────────
# 국내/자차와 기본틀 동일. 유형 구분 없음(모든 행 동일), 거래처=작성자 본인, 예산단위=여비교통비-
# 해외출장, 공급가액=입력 총액. steps 의 key 는 그래프 노드 emit_step 키와 1:1(국내와 동일 체인).
_TRIP_OVERSEAS_FIXTURE: dict = {
    "id": "trip-overseas",
    "workflow_id": "trip-overseas",
    "group_id": "resolution",
    # 라이브 프로브(ERP 필드 확정) 전까지 목록/상세에서 숨김 — 카드·국내출장만 노출(사용자 요청
    # 2026-07-08). 코드·등록은 유지되며, 검증 완료 시 이 플래그만 제거하면 노출된다.
    "hidden": True,
    "name": "출장(해외/정산서)",
    "description": "해외 출장 정산 내역(날짜·금액·프로젝트·내용)을 입력하면 결의서로 만들어 저장합니다.",
    "handoff_note": "저장된 결의서는 아직 상신 전입니다. 옴니솔 결의서 화면에서 저장된 건을 확인하고 직접 상신하세요. ⚠ 해외출장 일비가 두 달에 걸치면(예: 3/30~4/6) 회계일자별로 나눠 상신하세요 — 3/31자(3/30~3/31분)와 4/6 이후자(4/1~4/6분)를 각각 별도 결의서로 실행/상신해야 합니다.",
    "drive": "browser",
    "interaction": "autonomous",
    "target_system": "더존 옴니솔",
    "target_url": "erp.ninebell.co.kr",
    "status": "idle",
    "progress": 0,
    "timeout_seconds": 240,
    "elapsed_seconds": 0,
    "current_action": "대기 중 — 입력을 완료하고 실행하면 시작합니다",
    "run_count": 0,
    "success_rate": 0.0,
    "avg_seconds": 0,
    "last_run_at": None,
    "flow_graph": TRIP_OVERSEAS_FLOW,
    "steps": [
        {"key": "validate_params", "label": "입력 검증", "skill": "field-input", "status": "pending", "phase": "접속", "detail": "실행 전 폼 입력(계산서일·공급가액·행)을 검증하고 회계일자를 파생"},
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
        {"key": "menu_nav", "label": "결의서입력 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "전사공통(회계) 결의서 입력 화면 진입"},
        {"key": "set_gubun", "label": "결의구분: 출장(해외·정산서)", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "결의구분 드롭다운을 출장(해외·정산서)으로 설정"},
        {"key": "add_row", "label": "상세행 추가(F3)", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "F3로 첫 결의 상세행 생성"},
        {"key": "set_acct_date", "label": "회계일 설정", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "마지막 계산서일(출장일)로 결의서 회계일 설정"},
        {"key": "fill_rows", "label": "건별 입력", "skill": "grid-input", "status": "pending", "phase": "건별 입력", "detail": "행별 증빙(10)·계산서일·거래처(본인)·예산단위(해외출장)·프로젝트·공급가액·적요·상대계정(본인)을 반복 입력(HITL 없음)"},
        {"key": "save_doc", "label": "저장(F7)", "skill": "save", "status": "pending", "phase": "저장", "detail": "반영된 행을 마지막에 한 번만 저장"},
    ],
    "logs": [],
}


AGENT_FIXTURES.extend(
    [
        _TRIP_DOMESTIC_FIXTURE,
        _TRIP_OVERSEAS_FIXTURE,
        _resolution_dummy("family-event", "경조금"),
        _resolution_dummy("scholarship", "학자금"),
        # 자재팀 그룹 — 내용 없는 더미(준비 중, 노출). 구현 시 workflow_id·steps 를 채워 승격한다.
        _dummy_agent("materials-inbound", "자동 입고 처리", group_id="materials"),
        _dummy_agent("materials-classify", "프로젝트별 자재 자동 분류", group_id="materials"),
    ]
)
