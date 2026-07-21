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
# '결의서입력' 문서군: 카드(실동작) + 출장(국내/자차·해외/정산서)·경조금·학자금(전부 실동작·노출).
# 학자금은 라이브 스모크 10/10 통과 후 노출(2026-07-15, 경조금 관례).
AGENT_GROUP_FIXTURES: list[dict] = [
    {
        "id": "resolution",
        "name": "결의서입력",
        "description": "지출 결의서를 종류별로 대신 작성해 저장합니다.",
        "sort_order": 0,
    },
    {
        "id": "voucher",
        "name": "회계전표",
        "description": "외상매입·매출, 미지급금 등 회계전표를 종류별로 대신 입력합니다.",
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
    # 라이브 검증 완료(2026-07-09: 결의구분 54·금액 예산현황·저장 실증, 상대계정은 정산서 유형에
    # 항목이 없어 자동 스킵) → 노출(사용자 요청).
    "hidden": False,
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
        {"key": "fill_rows", "label": "건별 입력", "skill": "grid-input", "status": "pending", "phase": "건별 입력", "detail": "행별 증빙(10)·계산서일·거래처(본인)·예산단위(해외출장)·프로젝트·공급가액(타이핑+예산현황 확인)·적요·상대계정(부가선택 위젯)+빈행정리를 반복 입력(HITL 없음)"},
        {"key": "save_doc", "label": "저장(F7)", "skill": "save", "status": "pending", "phase": "저장", "detail": "반영된 행을 마지막에 한 번만 저장"},
    ],
    "logs": [],
}


# ── 경조금신청서 결의 플로우 그래프 (gyeongjo-grant 그래프의 사람용 요약) ──────
# 단건(1행) — 국내/해외출장의 '다음 행?' 반복 루프가 없다(경조사 1건 = 결의서 1장).
GYEONGJO_GRANT_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "결의서 입력 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "kind", "kind": "step", "status": "done", "title": "결의구분 = 경조금신청서", "sub": "추가(F3)", **_col(1)},
        {"id": "date", "kind": "step", "status": "done", "title": "회계일자 세팅", "sub": "증빙일자", **_col(2)},
        {"id": "evd", "kind": "step", "status": "active", "title": "증빙유형 선택", "sub": "10 규정에의한 비용정산", **_col(3)},
        {"id": "partner", "kind": "step", "status": "pending", "title": "거래처 입력", "sub": "작성자 본인", **_col(4)},
        {"id": "budget", "kind": "step", "status": "pending", "title": "예산단위", "sub": "복리후생비-경조(부서×판/제)", **_col(5)},
        {"id": "project", "kind": "step", "status": "pending", "title": "프로젝트", "sub": "기본 제조 500 / 판관 800", **_col(6)},
        {"id": "amount", "kind": "step", "status": "pending", "title": "공급가액", "sub": "정액(근속 1년 미만 시 50%)", **_col(7)},
        {"id": "memo", "kind": "step", "status": "pending", "title": "적요 작성", "sub": "경조금-{본인이름}", **_col(8)},
        {"id": "bfc", "kind": "step", "status": "pending", "title": "상대계정거래처", "sub": "작성자 본인(부가선택 위젯)", **_col(9)},
        {"id": "save", "kind": "step", "status": "pending", "title": "저장(F7)", "sub": "저장 후 지속 확인", **_col(10)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "전자결재 상신", "sub": "사용자가 직접", **_col(11)},
    ],
    "edges": [
        {"id": "e-access-kind", "source": "access", "target": "kind"},
        {"id": "e-kind-date", "source": "kind", "target": "date"},
        {"id": "e-date-evd", "source": "date", "target": "evd"},
        {"id": "e-evd-partner", "source": "evd", "target": "partner"},
        {"id": "e-partner-budget", "source": "partner", "target": "budget"},
        {"id": "e-budget-project", "source": "budget", "target": "project"},
        {"id": "e-project-amount", "source": "project", "target": "amount"},
        {"id": "e-amount-memo", "source": "amount", "target": "memo"},
        {"id": "e-memo-bfc", "source": "memo", "target": "bfc"},
        {"id": "e-bfc-save", "source": "bfc", "target": "save"},
        {"id": "e-save-submit", "source": "save", "target": "submit", "label": "저장 후", "kind": "branch"},
    ],
}


# ── 경조금신청서 — 실동작 승격(gyeongjo-grant 워크플로우) ──────────────────────
# family-event 더미를 제자리 승격한다(agent id "family-event" 유지 — 프론트/시드 연속성). 국내/해외
# 출장과 detail 스키마·프리미티브 동일(단건). steps 의 key 는 그래프 노드 emit_step 키와 1:1.
# 노출(hidden=False, 2026-07-13) — 단계 3/7 라이브 실저장 10/10 PASS·잔존 0·50%(ROUND_HALF_UP) 저장값
# 일치 검증 완료. D12 상대계정거래처는 경조금 불필요로 확정돼 fill 에서 제거. 프론트 pre-run 폼
# (gyeongjo-pre-run-form) 등록됨.
_GYEONGJO_GRANT_FIXTURE: dict = {
    "id": "family-event",
    "workflow_id": "gyeongjo-grant",
    "group_id": "resolution",
    "hidden": False,
    "name": "경조금",
    "description": "경조사 1건의 경조금을 입력하면 결의서로 만들어 저장합니다. 근속 1년 미만이면 공급가액을 자동으로 50% 처리합니다.",
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
    "flow_graph": GYEONGJO_GRANT_FLOW,
    "steps": [
        {"key": "validate_params", "label": "입력 검증", "skill": "field-input", "status": "pending", "phase": "접속", "detail": "실행 전 폼 입력(증빙일·정액·근속토글·프로젝트)을 검증하고 공급가액(근속<1년 50%)을 계산"},
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
        {"key": "menu_nav", "label": "결의서입력 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "전사공통(회계) 결의서 입력 화면 진입"},
        {"key": "set_gubun", "label": "결의구분: 경조금신청서", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "결의구분 드롭다운을 경조금신청서로 설정"},
        {"key": "add_row", "label": "상세행 추가(F3)", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "F3로 결의 상세행 생성(단건)"},
        {"key": "set_acct_date", "label": "회계일 설정", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "증빙일자로 결의서 회계일 설정"},
        {"key": "fill_rows", "label": "건별 입력", "skill": "grid-input", "status": "pending", "phase": "건별 입력", "detail": "증빙(10)·계산서일·거래처(본인)·예산단위(복리후생비-경조)·프로젝트·공급가액(타이핑+예산현황 확인)·적요(경조금-{본인})·상대계정(부가선택 위젯)+빈행정리를 입력(HITL 없음)"},
        {"key": "save_doc", "label": "저장(F7)", "skill": "save", "status": "pending", "phase": "저장", "detail": "반영된 행을 마지막에 한 번만 저장"},
    ],
    "logs": [],
}


# ── 학자금신청서 결의 플로우 그래프 (hakjagum-grant 그래프의 사람용 요약) ──────
# 경조금 형제 클론 — 단건(1행), '다음 행?' 반복 루프 없음(학자금 1건 = 결의서 1장). 경조금 대비
# 델타: 결의구분 학자금신청서·예산단위 복리후생비-기타·공급가액 사용자 입력 그대로(50% 규칙 없음)·
# 적요 학자금-{본인이름}. 상대계정거래처(bfc) 노드 없음(미사용 확정 — 라이브 11/11, 경조금 동형) → memo→save 직결.
HAKJAGUM_GRANT_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "결의서 입력 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "kind", "kind": "step", "status": "done", "title": "결의구분 = 학자금신청서", "sub": "추가(F3)", **_col(1)},
        {"id": "date", "kind": "step", "status": "done", "title": "회계일자 세팅", "sub": "증빙일자", **_col(2)},
        {"id": "evd", "kind": "step", "status": "active", "title": "증빙유형 선택", "sub": "10 규정에의한 비용정산", **_col(3)},
        {"id": "partner", "kind": "step", "status": "pending", "title": "거래처 입력", "sub": "작성자 본인", **_col(4)},
        {"id": "budget", "kind": "step", "status": "pending", "title": "예산단위", "sub": "복리후생비-기타(부서×판/제)", **_col(5)},
        {"id": "project", "kind": "step", "status": "pending", "title": "프로젝트", "sub": "기본 제조 500 / 판관 800", **_col(6)},
        {"id": "amount", "kind": "step", "status": "pending", "title": "공급가액", "sub": "사용자 입력 금액", **_col(7)},
        {"id": "memo", "kind": "step", "status": "pending", "title": "적요 작성", "sub": "학자금-{본인이름}", **_col(8)},
        {"id": "save", "kind": "step", "status": "pending", "title": "저장(F7)", "sub": "저장 후 지속 확인", **_col(9)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "전자결재 상신", "sub": "사용자가 직접", **_col(10)},
    ],
    "edges": [
        {"id": "e-access-kind", "source": "access", "target": "kind"},
        {"id": "e-kind-date", "source": "kind", "target": "date"},
        {"id": "e-date-evd", "source": "date", "target": "evd"},
        {"id": "e-evd-partner", "source": "evd", "target": "partner"},
        {"id": "e-partner-budget", "source": "partner", "target": "budget"},
        {"id": "e-budget-project", "source": "budget", "target": "project"},
        {"id": "e-project-amount", "source": "project", "target": "amount"},
        {"id": "e-amount-memo", "source": "amount", "target": "memo"},
        {"id": "e-memo-save", "source": "memo", "target": "save"},
        {"id": "e-save-submit", "source": "save", "target": "submit", "label": "저장 후", "kind": "branch"},
    ],
}


# ── 학자금신청서 — 실동작 승격(hakjagum-grant 워크플로우) ──────────────────────
# scholarship 더미를 제자리 승격한다(agent id "scholarship" 유지 — 프론트/시드 연속성). 경조금의
# 형제 클론(단건·공급가액=사용자 입력 그대로, 50% 규칙 없음). steps 의 key 는 그래프 노드
# emit_step 키와 1:1. 노출(hidden=False, 2026-07-15) — 단계 3/7 라이브 실저장 10/10 PASS·잔존 0·
# 저장 금액(SPPRC_AMT2) 일치 검증 완료. D12 상대계정거래처는 학자금 미사용 확정(11/11 사이클 상대계정
# 스텝 없이 저장 성공·스트레이 빈 행 0)이라 fill 에 없음. 프론트 pre-run 폼(hakjagum-grant) 등록됨.
_HAKJAGUM_GRANT_FIXTURE: dict = {
    "id": "scholarship",
    "workflow_id": "hakjagum-grant",
    "group_id": "resolution",
    "hidden": False,
    "name": "학자금",
    "description": "학자금 1건을 입력하면 결의서로 만들어 저장합니다.",
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
    "flow_graph": HAKJAGUM_GRANT_FLOW,
    "steps": [
        {"key": "validate_params", "label": "입력 검증", "skill": "field-input", "status": "pending", "phase": "접속", "detail": "실행 전 폼 입력(증빙일·금액·프로젝트)을 검증"},
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
        {"key": "menu_nav", "label": "결의서입력 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "전사공통(회계) 결의서 입력 화면 진입"},
        {"key": "set_gubun", "label": "결의구분: 학자금신청서", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "결의구분 드롭다운을 학자금신청서로 설정"},
        {"key": "add_row", "label": "상세행 추가(F3)", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "F3로 결의 상세행 생성(단건)"},
        {"key": "set_acct_date", "label": "회계일 설정", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "증빙일자로 결의서 회계일 설정"},
        {"key": "fill_rows", "label": "건별 입력", "skill": "grid-input", "status": "pending", "phase": "건별 입력", "detail": "증빙(10)·계산서일·거래처(본인)·예산단위(복리후생비-기타)·프로젝트·공급가액(타이핑+예산현황 확인)·적요(학자금-{본인})를 입력(HITL 없음)"},
        {"key": "save_doc", "label": "저장(F7)", "skill": "save", "status": "pending", "phase": "저장", "detail": "반영된 행을 마지막에 한 번만 저장"},
    ],
    "logs": [],
}


# ── 전표조회승인 결재 플로우 그래프 (voucher-receivable 그래프의 사람용 요약) ──────
# 결의서입력(문서 생성) 계열과 다른 '조회+결재' 아키타입 — 결제창을 열어 가상 상신 로그만
# 남기고 닫는다(실제 상신 없음). 단일행 기본(max_rows=1) — 다음 건 반복은 배치 게이트 안에서만.
VOUCHER_RECEIVABLE_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "전표조회승인 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "setq", "kind": "step", "status": "done", "title": "조회 조건 세팅", "sub": "미결·전자결재저장·국내/해외매출", **_col(1)},
        {"id": "query", "kind": "step", "status": "active", "title": "조회(F2)", "sub": "대상 전표 목록", **_col(2)},
        {"id": "pick", "kind": "step", "status": "pending", "title": "행 선택(checkRow)", "sub": "결재 대상 지정", **_col(3)},
        {"id": "pay", "kind": "step", "status": "pending", "title": "결제창 열기", "sub": "별도 전자결재 창(EAP)", **_col(4)},
        {"id": "virtual", "kind": "step", "status": "pending", "title": "가상 상신", "sub": "상신·보관 미클릭 — 로그만", **_col(5)},
        {"id": "close", "kind": "step", "status": "pending", "title": "결제창 닫기", "sub": "비영속(다음 건)", **_col(6)},
        {"id": "more", "kind": "decision", "status": "pending", "title": "다음 건?", "sub": "max_rows 내 반복(기본 1건)", **_col(7)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "실제 상신", "sub": "사용자가 직접(EAP)", **_col(8)},
    ],
    "edges": [
        {"id": "e-access-setq", "source": "access", "target": "setq"},
        {"id": "e-setq-query", "source": "setq", "target": "query"},
        {"id": "e-query-pick", "source": "query", "target": "pick"},
        {"id": "e-pick-pay", "source": "pick", "target": "pay"},
        {"id": "e-pay-virtual", "source": "pay", "target": "virtual"},
        {"id": "e-virtual-close", "source": "virtual", "target": "close"},
        {"id": "e-close-more", "source": "close", "target": "more"},
        {"id": "e-more-pick", "source": "more", "target": "pick", "label": "다음 건 ↩", "kind": "loop"},
        {"id": "e-more-submit", "source": "more", "target": "submit", "label": "마지막 건", "kind": "branch"},
    ],
}


# ── 외상매출금 전표결재 — 실동작 승격(voucher-receivable 워크플로우) ──────────────
# voucher-trade-receivable 더미를 제자리 승격한다(agent id 유지 — 프론트/시드 연속성).
# 완전 공개(hidden=False, 사용자 결정 2026-07-21) — 목록 노출 + 실행 허용. 라이브 스모크·EAP
#   담당자 확인 전이지만 사용자 요청으로 노출한다. ⚠ 결제창을 여는 것만으로 EAP 임시문서가
#   생길 수 있음(handoff_note·PROCESS.md 안전섹션 참조). 배치(allow_batch)는 여전히 코드 게이트.
#   steps 의 key 는 그래프 노드(emit_step 키)와 1:1(진행 하이라이트 정합).
_VOUCHER_RECEIVABLE_FIXTURE: dict = {
    "id": "voucher-trade-receivable",
    "workflow_id": "voucher-receivable",
    "group_id": "voucher",
    "hidden": False,
    "name": "외상매출금",
    "description": "미결·전자결재저장 상태의 매출전표(국내/해외)를 조회해, 건별로 결제창을 열어 상신 대기 상태를 확인합니다(실제 상신은 하지 않습니다).",
    "handoff_note": "이 에이전트는 실제 상신을 하지 않습니다 — 결제창을 열어 '가상 상신'만 확인하고 닫습니다. 옴니솔 전표조회승인에서 대상 전표를 확인하고 전자결재(EAP)에서 직접 상신하세요. ⚠ 결제창을 여는 것만으로 EAP 임시문서가 생길 수 있으니, 여러 건 배치는 담당자 확인 후에만 사용하세요.",
    "drive": "browser",
    "interaction": "autonomous",
    "target_system": "더존 옴니솔",
    "target_url": "erp.ninebell.co.kr",
    "status": "idle",
    "progress": 0,
    "timeout_seconds": 240,
    "elapsed_seconds": 0,
    "current_action": "대기 중 — 실행을 누르면 시작합니다",
    "run_count": 0,
    "success_rate": 0.0,
    "avg_seconds": 0,
    "last_run_at": None,
    "flow_graph": VOUCHER_RECEIVABLE_FLOW,
    "steps": [
        {"key": "validate_params", "label": "실행 파라미터 확인", "skill": "field-input", "status": "pending", "phase": "접속", "detail": "처리 건수(기본 1건)를 확인하고 배치 안전 게이트를 적용"},
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
        {"key": "menu_nav", "label": "전표조회승인 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "총계정원장 > 전표관리 > 전표조회승인(GLDDOC00700) 진입"},
        {"key": "set_query", "label": "조회 조건 세팅", "skill": "field-input", "status": "pending", "phase": "조회", "detail": "작성부서 전체·회계일 당월·전표상태 미결·전자결재상태 저장·전표유형 국내/해외매출"},
        {"key": "run_query", "label": "조회(F2)", "skill": "grid-read", "status": "pending", "phase": "조회", "detail": "조건으로 대상 전표를 조회하고 건수를 보고"},
        {"key": "loop_approvals", "label": "결재창 순회(가상 상신)", "skill": "grid-input", "status": "pending", "phase": "결재", "detail": "대상 전표를 건별로 결제창까지 열어 '가상 상신' 로그만 남기고 닫음(상신·보관 미클릭, 실제 상신 없음)"},
    ],
    "logs": [],
}


# 외상매입금 — 외상매출금과 전부 공유, 전표유형만 내수구매(build_voucher_payable_graph).
# 픽스처도 receivable 를 스프레드로 재사용하고 id/workflow_id/name/설명·set_query detail 만 덮는다.
_VOUCHER_PAYABLE_FIXTURE: dict = {
    **_VOUCHER_RECEIVABLE_FIXTURE,
    "id": "voucher-trade-payable",
    "workflow_id": "voucher-payable",
    "name": "외상매입금",
    "description": "미결·전자결재저장 상태의 매입전표(내수구매)를 조회해, 건별로 결제창을 열어 상신 대기 상태를 확인합니다(실제 상신은 하지 않습니다).",
    "steps": [
        {**s, "detail": "작성부서 전체·회계일 당월·전표상태 미결·전자결재상태 저장·전표유형 내수구매"}
        if s["key"] == "set_query"
        else s
        for s in _VOUCHER_RECEIVABLE_FIXTURE["steps"]
    ],
}


# ── 미지급금 법인카드 결재 플로우 그래프 (voucher-card 그래프의 사람용 요약) ──────
# 공유 조회+결재에 카드 3대 확장: (B) 결의서조회승인 다중탭 결재번호 수집, (C) 결제창 안
# 참조문서 선택. 실제 상신·참조문서 확인 없음(가상 상신 로그만).
VOUCHER_CARD_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "전표조회승인 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "setq", "kind": "step", "status": "done", "title": "조회 조건 세팅", "sub": "미결·전자결재저장·전표유형 일반", **_col(1)},
        {"id": "query", "kind": "step", "status": "done", "title": "조회(F2)", "sub": "대상=결의구분 카드·결의서번호 있는 행", **_col(2)},
        {"id": "collect", "kind": "step", "status": "active", "title": "결재번호 수집", "sub": "결의서조회승인(다중탭)·결의구분 카드 일괄", **_col(3)},
        {"id": "pick", "kind": "step", "status": "pending", "title": "행 선택(checkRow)", "sub": "결재 대상 지정", **_col(4)},
        {"id": "pay", "kind": "step", "status": "pending", "title": "결제창 열기", "sub": "별도 전자결재 창(EAP)", **_col(5)},
        {"id": "refdoc", "kind": "step", "status": "pending", "title": "참조문서 선택", "sub": "문서번호=결재번호 검색→선택→아래버튼", **_col(6)},
        {"id": "virtual", "kind": "step", "status": "pending", "title": "가상 상신", "sub": "확인·상신 미클릭 — 로그만", **_col(7)},
        {"id": "close", "kind": "step", "status": "pending", "title": "결제창 닫기", "sub": "비영속(다음 건)", **_col(8)},
        {"id": "more", "kind": "decision", "status": "pending", "title": "다음 건?", "sub": "대상 전 건 반복(기본 전체)", **_col(9)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "실제 상신", "sub": "사용자가 직접(EAP)", **_col(10)},
    ],
    "edges": [
        {"id": "e-access-setq", "source": "access", "target": "setq"},
        {"id": "e-setq-query", "source": "setq", "target": "query"},
        {"id": "e-query-collect", "source": "query", "target": "collect"},
        {"id": "e-collect-pick", "source": "collect", "target": "pick"},
        {"id": "e-pick-pay", "source": "pick", "target": "pay"},
        {"id": "e-pay-refdoc", "source": "pay", "target": "refdoc"},
        {"id": "e-refdoc-virtual", "source": "refdoc", "target": "virtual"},
        {"id": "e-virtual-close", "source": "virtual", "target": "close"},
        {"id": "e-close-more", "source": "close", "target": "more"},
        {"id": "e-more-pick", "source": "more", "target": "pick", "label": "다음 건 ↩", "kind": "loop"},
        {"id": "e-more-submit", "source": "more", "target": "submit", "label": "마지막 건", "kind": "branch"},
    ],
}


# ── 미지급금 법인카드 — 실동작 승격(voucher-card 워크플로우) ────────────────────
# voucher-card-payable 더미를 제자리 승격한다(agent id 유지 — 프론트/시드 연속성). 공유 백본
# (전표조회승인 조회+결재)에 카드 3대 확장(collect_payments 결재번호 수집 · 참조문서 선택 훅).
# steps 의 key 는 그래프 노드(emit_step 키)와 1:1(진행 하이라이트 정합). ⚠ 실제 상신·참조문서
# 확인 없음(가상). 참조문서 검색 0건(현재 테스트 계정 시스템 승인 이슈)은 우아하게 로그 후 진행.
_VOUCHER_CARD_FIXTURE: dict = {
    "id": "voucher-card-payable",
    "workflow_id": "voucher-card",
    "group_id": "voucher",
    "hidden": False,
    "name": "미지급금 법인카드",
    "description": "미결·전자결재저장 상태의 법인카드(결의구분 카드) 전표를 조회해, 건별로 결제창을 열고 참조문서(결재번호)를 선택한 뒤 상신 대기 상태를 확인합니다(실제 상신·참조문서 확인은 하지 않습니다).",
    "handoff_note": "이 에이전트는 실제 상신·참조문서 확인을 하지 않습니다 — 결제창을 열어 참조문서를 선택(선택+아래버튼)하고 '가상 상신'만 확인한 뒤 닫습니다. 옴니솔 전표조회승인에서 대상 전표를 확인하고 전자결재(EAP)에서 직접 참조문서 확인·상신을 진행하세요. ⚠ 결제창을 여는 것만으로 EAP 임시문서가 생길 수 있습니다. ⚠ 현재 테스트 계정은 시스템 승인 이슈로 참조문서가 0건 조회될 수 있습니다(추후 손봄).",
    "drive": "browser",
    "interaction": "autonomous",
    "target_system": "더존 옴니솔",
    "target_url": "erp.ninebell.co.kr",
    "status": "idle",
    "progress": 0,
    "timeout_seconds": 240,
    "elapsed_seconds": 0,
    "current_action": "대기 중 — 실행을 누르면 시작합니다",
    "run_count": 0,
    "success_rate": 0.0,
    "avg_seconds": 0,
    "last_run_at": None,
    "flow_graph": VOUCHER_CARD_FLOW,
    "steps": [
        {"key": "validate_params", "label": "실행 파라미터 확인", "skill": "field-input", "status": "pending", "phase": "접속", "detail": "처리 건수(기본 전체)·회계일(기본 당월)을 확인"},
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
        {"key": "menu_nav", "label": "전표조회승인 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "총계정원장 > 전표관리 > 전표조회승인(GLDDOC00700) 진입"},
        {"key": "set_query", "label": "조회 조건 세팅", "skill": "field-input", "status": "pending", "phase": "조회", "detail": "작성부서 전체·회계일 당월·전표상태 미결·전자결재상태 저장·전표유형 일반"},
        {"key": "run_query", "label": "조회(F2)", "skill": "grid-read", "status": "pending", "phase": "조회", "detail": "조건으로 대상 전표를 조회하고 건수를 보고(대상=결의구분 카드·결의서번호 있는 행)"},
        {"key": "collect_payments", "label": "결재번호 수집", "skill": "grid-read", "status": "pending", "phase": "수집", "detail": "결의서조회승인(다중탭)에서 결의구분=카드 일괄 조회 → ABDOCU_NO→GWDOCU_NO(결재번호) 맵 수집 → 전표조회승인 탭 복귀"},
        {"key": "loop_approvals", "label": "결재창 순회(참조문서·가상 상신)", "skill": "grid-input", "status": "pending", "phase": "결재", "detail": "대상 전표를 건별로 결제창까지 열어 참조문서(문서번호=결재번호)를 선택(선택+아래버튼)하고 '가상 상신' 로그만 남기고 닫음(참조문서 확인·상신 미클릭, 실제 상신 없음)"},
    ],
    "logs": [],
}


AGENT_FIXTURES.extend(
    [
        _TRIP_DOMESTIC_FIXTURE,
        _TRIP_OVERSEAS_FIXTURE,
        _GYEONGJO_GRANT_FIXTURE,  # family-event 더미 → 실동작 승격(gyeongjo-grant).
        _HAKJAGUM_GRANT_FIXTURE,  # scholarship 더미 → 실동작 승격(hakjagum-grant, 노출).
        # 회계전표 그룹 — 표시 순서: 외상매입금 → 외상매출금 → 미지급금 법인카드(사용자 지정 2026-07-21).
        _VOUCHER_PAYABLE_FIXTURE,  # voucher-trade-payable → voucher-payable(내수구매)
        _VOUCHER_RECEIVABLE_FIXTURE,  # voucher-trade-receivable → voucher-receivable
        _VOUCHER_CARD_FIXTURE,  # voucher-card-payable → voucher-card(미지급금 법인카드)
    ]
)
