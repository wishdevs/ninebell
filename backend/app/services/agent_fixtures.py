"""에이전트 시드 픽스처 — 프론트 `src/lib/data/agents.ts`·`flows.ts` 이식.

사용자 요청으로 **corporate-card(결의서 입력 - 카드, workflow=card-collect)**
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
# '결의서입력' 문서군: 법인카드(실동작) + 출장(국내/자차·해외/정산서)·경조금·학자금(전부 실동작·노출).
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
    # 구매팀(사용자 지정 2026-08-12) — 자리만 잡은 그룹. 업무 정의 전이라 설명은 비워 둔다.
    {
        "id": "purchase",
        "name": "구매팀",
        "description": None,
        "sort_order": 2,
    },
]


# ── 1개 에이전트 (corporate-card 만 유지) ─────────────────────────────────────────
AGENT_FIXTURES: list[dict] = [
    {
        "id": "corporate-card",
        "workflow_id": "card-collect",  # 실행 레지스트리 워크플로우 id(유일 실동작).
        "group_id": "resolution",  # '결의서입력' 그룹 소속.
        # 형제 스타일(출장(국내/자차)·경조금·학자금 = 문서종류명)에 맞춰 '카드' → '법인카드'.
        "name": "법인카드",
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


# ── 전표조회승인 배치 결재 플로우 그래프 (매출 2026-07-27 → 매입 확대 2026-08-07) ──
# 결의서입력(문서 생성) 계열과 다른 '조회+결재' 아키타입 — 결제창을 열어 **상신까지 실행**한다
# (정책 전환 2026-08-07, 취소는 전자결재 결재취소로 가역). (건별 순회 원형 플로우
# VOUCHER_RECEIVABLE_FLOW 는 매입금의 배치 확대(2026-08-07)로 제거 — 필요 시 git 이력 참조.)
# 건별 순회 대신 **하위(계정정보) 건수 기준 배치**: 단독 200 이상은 먼저 단독으로, 나머지는
# 합계가 200 미만이 되도록 묶어 한 번에 결재창을 연다. 매입금은 기존 건별 플로우를 유지한다.
VOUCHER_RECEIVABLE_BATCH_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "전표조회승인 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "setq", "kind": "step", "status": "done", "title": "조회 조건 세팅", "sub": "미결·전자결재저장·선택한 전표유형", **_col(1)},
        {"id": "query", "kind": "step", "status": "active", "title": "조회(F2)", "sub": "대상 전표 목록", **_col(2)},
        {"id": "count", "kind": "step", "status": "pending", "title": "하위 건수 파악", "sub": "메뉴 필터 적용·전표별 계정정보 행수", **_col(3)},
        {"id": "plan", "kind": "decision", "status": "pending", "title": "배치 계획", "sub": "단독 200↑ 먼저 · 나머지 합계 200 미만", **_col(4)},
        {"id": "pick", "kind": "step", "status": "pending", "title": "묶음 선택(checkRow)", "sub": "그룹 행 일괄 체크", **_col(5)},
        {"id": "pay", "kind": "step", "status": "pending", "title": "결제창 열기", "sub": "묶음 1회 = 자식창 1개", **_col(6)},
        {"id": "virtual", "kind": "step", "status": "pending", "title": "상신", "sub": "묶음 1회 클릭 = N건 상신 · 보관 미클릭", **_col(7)},
        {"id": "more", "kind": "decision", "status": "pending", "title": "다음 묶음?", "sub": "재조회(F2) 후 잔여 그룹 — 상신분은 리스트에서 소멸", **_col(8)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "상신 완료", "sub": "취소는 전자결재 결재취소로 가능", **_col(9)},
    ],
    "edges": [
        {"id": "e-access-setq", "source": "access", "target": "setq"},
        {"id": "e-setq-query", "source": "setq", "target": "query"},
        {"id": "e-query-count", "source": "query", "target": "count"},
        {"id": "e-count-plan", "source": "count", "target": "plan"},
        {"id": "e-plan-pick", "source": "plan", "target": "pick"},
        {"id": "e-pick-pay", "source": "pick", "target": "pay"},
        {"id": "e-pay-virtual", "source": "pay", "target": "virtual"},
        {"id": "e-virtual-more", "source": "virtual", "target": "more"},
        {"id": "e-more-pick", "source": "more", "target": "pick", "label": "다음 묶음 ↩", "kind": "loop"},
        {"id": "e-more-submit", "source": "more", "target": "submit", "label": "마지막 묶음", "kind": "branch"},
    ],
}

# ── 유형별 전표조회 승인 — 외상매출금/외상매입금 병합(voucher-by-type, 2026-08-20) ──
# 두 에이전트(voucher-trade-receivable/voucher-trade-payable)를 하나로 병합했다 — 전표유형이
# 실행 전 폼의 다중 선택(국내매출/해외매출/내수구매)이 됐고, 메뉴(MENU_NM) 필터가 추가됐다
# (마스터 목록은 관리자 설정 menu_items — agent_settings.DEFAULT_MENU_ITEMS).
# DB 이관은 alembic 0036(조직 접근·즐겨찾기·런 이력 이관 후 구 행 삭제).
#   steps 의 key 는 그래프 노드(emit_step 키)와 1:1(진행 하이라이트 정합).
_VOUCHER_BY_TYPE_FIXTURE: dict = {
    "id": "voucher-by-type",
    "workflow_id": "voucher-by-type",
    "group_id": "voucher",
    "hidden": False,
    "name": "유형별 전표조회 승인",
    "description": "실행 시 선택한 전표유형(국내매출/해외매출/내수구매)의 미결·전자결재저장 전표를 조회해, 메뉴 필터로 대상을 추린 뒤 전표별 하위(계정정보) 건수를 파악해 묶음 단위로 결제창을 열어 전자결재로 상신합니다.",
    "handoff_note": "이 에이전트는 조회된 전표를 전자결재로 **실제 상신**합니다(2026-08-07 정책 전환). 상신 실패 건이 있으면 런이 중단되고 사유가 보고됩니다. 잘못 상신된 건은 전자결재 > 상신/보관함 > 상신문서에서 결재취소 → 미결문서 상신취소 → 임시보관문서 삭제로 회수할 수 있습니다. ⚠ 보관 버튼은 클릭하지 않습니다.",
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
    "flow_graph": VOUCHER_RECEIVABLE_BATCH_FLOW,
    "steps": [
        {"key": "validate_params", "label": "실행 파라미터 확인", "skill": "field-input", "status": "pending", "phase": "접속", "detail": "회계일 기간·전표유형 선택·메뉴 필터·처리 건수를 확인"},
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
        {"key": "menu_nav", "label": "전표조회승인 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "총계정원장 > 전표관리 > 전표조회승인(GLDDOC00700) 진입"},
        {"key": "set_query", "label": "조회 조건 세팅", "skill": "field-input", "status": "pending", "phase": "조회", "detail": "작성부서 전체·회계일 지정기간(기본 당월)·전표상태 미결·전자결재상태 저장·실행 시 선택한 전표유형(국내매출/해외매출/내수구매)"},
        {"key": "run_query", "label": "조회(F2)", "skill": "grid-read", "status": "pending", "phase": "조회", "detail": "조건으로 대상 전표를 조회하고 건수를 보고"},
        {"key": "count_details", "label": "하위 건수 파악·배치 계획", "skill": "grid-read", "status": "pending", "phase": "조회", "detail": "메뉴 필터로 대상을 추린 뒤 전표별 하위(계정정보) 행수를 읽어, 단독 200건 이상은 단독으로 · 나머지는 합계 200 미만이 되도록 결재 묶음을 계획"},
        {"key": "loop_approvals", "label": "묶음 결재 상신", "skill": "eap-submit", "status": "pending", "phase": "결재", "detail": "계획된 묶음마다 대상 행을 함께 체크해 결제창을 열고 상신 버튼을 클릭(묶음 1회=N건 상신, 보관 미클릭). 상신 실패 시 즉시 중단"},
    ],
    "logs": [],
}


# ── 미지급금 법인카드 결재 플로우 그래프 (voucher-card 그래프의 사람용 요약) ──────
# 공유 조회+결재에 카드 3대 확장: (B) 결의서조회승인 다중탭 결재번호 수집, (C) 결제창 안
# 참조문서 선택+확인 클릭+첨부 검증. 검증 통과 후 상신까지 실행(정책 전환 2026-08-07).
VOUCHER_CARD_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "전표조회승인 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "setq", "kind": "step", "status": "done", "title": "조회 조건 세팅", "sub": "미결·전자결재저장·전표유형 일반", **_col(1)},
        {"id": "query", "kind": "step", "status": "done", "title": "조회(F2)", "sub": "대상=결의구분 카드·결의서번호 있는 행", **_col(2)},
        {"id": "collect", "kind": "step", "status": "active", "title": "결재번호 수집", "sub": "결의서조회승인(다중탭)·결의구분 카드 일괄", **_col(3)},
        {"id": "pick", "kind": "step", "status": "pending", "title": "행 선택(checkRow)", "sub": "결재 대상 지정", **_col(4)},
        {"id": "pay", "kind": "step", "status": "pending", "title": "결제창 열기", "sub": "별도 전자결재 창(EAP)", **_col(5)},
        {"id": "refdoc", "kind": "step", "status": "pending", "title": "참조문서 선택·확인", "sub": "문서번호=결재번호 검색→선택→확인→첨부 검증", **_col(6)},
        {"id": "virtual", "kind": "step", "status": "pending", "title": "상신", "sub": "첨부 검증 통과 후 상신 클릭 · 보관 미클릭", **_col(7)},
        {"id": "close", "kind": "step", "status": "pending", "title": "창 닫힘 확인", "sub": "상신 적용 판정(다음 건)", **_col(8)},
        {"id": "more", "kind": "decision", "status": "pending", "title": "다음 건?", "sub": "재조회(F2) 후 다음 건 — 상신분은 리스트에서 소멸", **_col(9)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "상신 완료", "sub": "취소는 전자결재 결재취소로 가능", **_col(10)},
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
# steps 의 key 는 그래프 노드(emit_step 키)와 1:1(진행 하이라이트 정합). 참조문서 확인·상신
# 게이트 개방(2026-08-07). 참조문서 검색 0건(테스트 계정 승인 이슈)은 우아하게 로그 후 진행.
_VOUCHER_CARD_FIXTURE: dict = {
    "id": "voucher-card-payable",
    "workflow_id": "voucher-card",
    "group_id": "voucher",
    "hidden": False,
    "name": "미지급금 법인카드",
    "description": "미결·전자결재저장 상태의 법인카드(결의구분 카드) 전표를 조회해, 건별로 결제창을 열고 참조문서(결재번호)를 선택·확인한 뒤 전자결재로 상신합니다.",
    "handoff_note": "이 에이전트는 참조문서 확인과 **실제 상신**까지 수행합니다(2026-08-07 정책 전환) — 참조문서 첨부 검증을 통과한 건만 상신하며, 첨부·상신 실패 시 런이 중단되고 사유가 보고됩니다. 잘못 상신된 건은 전자결재 > 상신문서 결재취소 → 미결문서 상신취소 → 임시보관문서 삭제로 회수할 수 있습니다. ⚠ 보관 버튼은 클릭하지 않습니다. ⚠ 현재 테스트 계정은 시스템 승인 이슈로 참조문서가 0건 조회될 수 있습니다(추후 손봄).",
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
        {"key": "validate_params", "label": "실행 파라미터 확인", "skill": "field-input", "status": "pending", "phase": "접속", "detail": "처리 건수(기본 전체)·회계일 조회기간(기본 당월 1일~말일)을 확인"},
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
        {"key": "menu_nav", "label": "전표조회승인 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "총계정원장 > 전표관리 > 전표조회승인(GLDDOC00700) 진입"},
        {"key": "set_query", "label": "조회 조건 세팅", "skill": "field-input", "status": "pending", "phase": "조회", "detail": "작성부서 전체·회계일 지정기간(기본 당월)·전표상태 미결·전자결재상태 저장·전표유형 일반"},
        {"key": "run_query", "label": "조회(F2)", "skill": "grid-read", "status": "pending", "phase": "조회", "detail": "조건으로 대상 전표를 조회하고 건수를 보고(대상=결의구분 카드·결의서번호 있는 행)"},
        {"key": "collect_payments", "label": "결재번호 수집", "skill": "grid-read", "status": "pending", "phase": "수집", "detail": "결의서조회승인(다중탭)에서 결의구분=카드 일괄 조회 → ABDOCU_NO→GWDOCU_NO(결재번호) 맵 수집 → 전표조회승인 탭 복귀"},
        {"key": "loop_approvals", "label": "결재창 순회(참조문서·상신)", "skill": "eap-submit", "status": "pending", "phase": "결재", "detail": "대상 전표를 건별로 결제창까지 열어 참조문서(문서번호=결재번호)를 선택·확인하고 첨부 검증 통과 후 상신 클릭(보관 미클릭). 첨부·상신 실패 시 즉시 중단"},
    ],
    "logs": [],
}


# ── 세금계산서 결의 플로우 그래프 (tax-invoice 그래프의 사람용 요약) ────────────
# 발행 전/후·분할 여부로 갈리는 3경로를 한 그래프에 요약한다: 발행 후만 계산서 리스트(HITL)를
# 지나고, 분할일 때만 분할처리 팝업을 지난다. 저장 후 상신은 사용자가 ERP 에서 직접.
TAX_INVOICE_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "결의서 입력 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "kind", "kind": "step", "status": "done", "title": "결의구분 = 세금계산서", "sub": "추가(F3)", **_col(1)},
        {"id": "evd", "kind": "step", "status": "active", "title": "증빙유형 확정", "sub": "발행·과세·분할 → 10종 코드(서버 도출)", **_col(2)},
        {"id": "list", "kind": "decision", "status": "pending", "title": "계산서 선택·입력", "sub": "발행 후만 · 행 선택 + 행별 입력(개입)", **_col(3)},
        {"id": "fill", "kind": "step", "status": "pending", "title": "본문 입력", "sub": "발행 전 폼 / 발행 후 개입값을 행별 반영", **_col(4)},
        {"id": "split", "kind": "decision", "status": "pending", "title": "비용분할", "sub": "분할처리 팝업 다행 분개", **_col(5)},
        {"id": "save", "kind": "step", "status": "pending", "title": "저장(F7)", "sub": "저장 후 재조회 지속 확인", **_col(6)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "전자결재 상신", "sub": "사용자가 ERP 에서 직접", **_col(7)},
    ],
    "edges": [
        {"id": "e-access-kind", "source": "access", "target": "kind"},
        {"id": "e-kind-evd", "source": "kind", "target": "evd"},
        {"id": "e-evd-list", "source": "evd", "target": "list", "label": "발행 후", "kind": "branch"},
        {"id": "e-evd-fill", "source": "evd", "target": "fill", "label": "발행 전·분할", "kind": "branch"},
        {"id": "e-list-fill", "source": "list", "target": "fill"},
        {"id": "e-fill-split", "source": "fill", "target": "split", "label": "분할일 때", "kind": "branch"},
        {"id": "e-fill-save", "source": "fill", "target": "save", "label": "분할 없음", "kind": "branch"},
        {"id": "e-split-save", "source": "split", "target": "save"},
        {"id": "e-save-submit", "source": "save", "target": "submit", "label": "저장 후", "kind": "branch"},
    ],
}


# ── 세금계산서 — 실동작 승격(tax-invoice 워크플로우, 2026-08-19) ────────────────
# 화면 시뮬레이션 더미를 제자리 승격한다(agent id "tax-invoice" 유지 — 프론트/시드 연속성).
# 증빙유형 10종은 서버 도출(app.agents.tax_invoice.params.evidence_for — 프론트 evidenceFor 와
# 패리티 테스트로 lockstep). steps 의 key 는 그래프 노드(emit_step 키)와 1:1.
# 검증 상태(2026-08-19): 발행 전(22)은 쓰기 프로브 완전 사이클 PASS(RN202608190004 저장→독립
# 검증→F6 삭제). 분할(11)은 headed 동반 세션에서 레시피가 확정됐고(RN202608190005 저장 성공 —
# 자금과목 채움이 F7 반려 해소의 핵심) 10사이클 스모크는 미완이다.
_TAX_INVOICE_FIXTURE: dict = {
    "id": "tax-invoice",
    "workflow_id": "tax-invoice",
    "group_id": "resolution",
    "hidden": False,
    "name": "세금계산서",
    "description": "발행 전/후·과세성격·비용분할에 맞는 증빙유형으로 세금계산서 결의서를 작성해 저장(F7)까지 자동 진행합니다. 발행 후에는 전자발행 계산서 목록에서 반영할 행을 직접 선택합니다.",
    "handoff_note": "저장된 결의서는 아직 상신 전입니다 — 상신은 ERP 에서 직접 진행해 주세요. ⚠ 비용분할(11·13)은 마지막 배부행 적요가 문서 적요로 저장될 수 있습니다(금액 배분은 정상) — 저장 후 적요만 확인해 주세요.",
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
    "flow_graph": TAX_INVOICE_FLOW,
    "steps": [
        {"key": "validate_params", "label": "입력 검증", "skill": "field-input", "status": "pending", "phase": "접속", "detail": "실행 전 폼 입력을 검증하고 증빙유형 코드(10종)를 서버에서 확정"},
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "회계 사용자 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 '회계'로 전환"},
        {"key": "menu_nav", "label": "결의서입력 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "전사공통(회계) 결의서 입력 화면 진입"},
        {"key": "set_gubun", "label": "결의구분: 세금계산서", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "결의구분 드롭다운을 세금계산서(51)로 설정"},
        {"key": "add_row", "label": "상세행 추가(F3)", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "F3로 결의 상세행 생성"},
        {"key": "select_evdn", "label": "증빙유형 적용", "skill": "field-input", "status": "pending", "phase": "결의서 준비", "detail": "확정 코드 적용 + '전자발행된 증빙' 다이얼로그 응답(발행 전·분할=아니요, 발행 후=예)"},
        {"key": "pick_invoices", "label": "계산서 선택·입력", "skill": "grid-read", "status": "pending", "phase": "계산서 선택", "detail": "발행 후만 — 조회(F2)→전자세금계산서 팝업 기간 조회→계산서 그리드 개입(행 선택 + 행별 예산단위·프로젝트·적요, 분할이면 분할 계획)"},
        {"key": "apply_invoices", "label": "계산서 반영", "skill": "grid-input", "status": "pending", "phase": "건별 입력", "detail": "발행 후만 — 선택한 계산서를 문서에 적용하고 생성된 상세 행마다 예산단위·프로젝트·적요·자금과목을 입력"},
        {"key": "fill_rows", "label": "본문 입력", "skill": "grid-input", "status": "pending", "phase": "건별 입력", "detail": "발행 전만 — 거래처(정확명)·적요·예산단위·공급가액(타이핑, 세액 자동)·프로젝트(WBS)·[비과세 사유구분]·[회계일]·자금과목(일반경비)을 입력"},
        {"key": "split_costs", "label": "비용분할", "skill": "grid-input", "status": "pending", "phase": "건별 입력", "detail": "분할일 때만 — 분할처리 팝업 행 구성+차액반영+잉여 행 정리+전 행 비용센터/프로젝트→적용"},
        {"key": "save_doc", "label": "저장(F7)", "skill": "save", "status": "pending", "phase": "저장", "detail": "저장 확인 '예' 후 재조회로 문서 지속을 검증(상신은 하지 않음)"},
    ],
    "logs": [],
}


# ── 테스트 문서 정리(디버그 전용, 2026-08-10 → 결의서 전체 확대) — hidden 워크플로우 ──
# 스모크 삭제 가드레일(본인 작성·결의구분 일치·미결) + HITL 선택 삭제의 공용 cleanup 그래프.
# hidden=True: 목록/상세는 전원 비노출(404), 실행은 관리자만(ensure_can_run 비대칭) —
# 프론트는 에이전트 상세의 디버그 모드 버튼으로만 트리거한다.
def _cleanup_fixture(cleanup_id: str, doc_name: str, gubun_label: str) -> dict:
    return {
        "id": cleanup_id,
        "workflow_id": cleanup_id,
        "group_id": None,
        "hidden": True,
        "name": f"{doc_name} 테스트 문서 정리",
        "description": (
            f"디버깅 중 만든 {gubun_label} 결의서를 결의서입력 화면에서 조회해, "
            "본인 작성·미결 문서 전량 가드 통과 후 사용자가 선택한 문서만 삭제(F6)합니다."
        ),
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
        "flow_graph": None,
        "steps": [],
        "logs": [],
    }


# ── 전자결재 상신 취소(디버그 전용, 2026-08-12) — hidden 워크플로우 ──────────────
# voucher 3종이 실제 상신한 문서를 회수하는 경로(결재취소 → 상신취소 → 삭제). 취소 3단계는
# 비가역이라 HITL(multiselect)로 상신문서함의 '진행' 문서를 제시하고 체크한 건만 처리한다.
# hidden=True: 목록/상세 비노출(404), 실행은 관리자 + 프론트 디버그 모드 버튼뿐.
_EAP_CANCEL_FIXTURE: dict = {
    "id": "eap-approval-cancel",
    "workflow_id": "eap-approval-cancel",
    "group_id": None,
    "hidden": True,
    "name": "전자결재 상신 취소",
    "description": (
        "전자결재 상신문서함에서 '진행' 상태 문서를 조회해 목록으로 보여주고, "
        "사용자가 체크한 문서만 결재취소 → 상신취소 → 삭제까지 처리합니다(비가역)."
    ),
    "drive": "browser",
    "interaction": "autonomous",
    "target_system": "더존 옴니솔",
    "target_url": "erp.ninebell.co.kr",
    "status": "idle",
    "progress": 0,
    "timeout_seconds": 600,
    "elapsed_seconds": 0,
    "current_action": "대기 중 — 실행을 누르면 시작합니다",
    "run_count": 0,
    "success_rate": 0.0,
    "avg_seconds": 0,
    "last_run_at": None,
    "flow_graph": None,
    "steps": [],
    "logs": [],
}


# ── 구매발주 계획 플로우 그래프 (purchase-order 그래프의 사람용 요약, Phase A) ──────
# 읽기 + 계획서 HITL 까지 — 저장(F7)·결재 없음. 발주단위 반복 실행(쓰기)은 Phase B 에서
# 그래프·플로우를 함께 확장한다(PROCESS.md 남은 작업).
PURCHASE_ORDER_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "구매요청 화면 접속", "sub": "SCM-구매 · PUOPRQ00200", **_col(0)},
        {"id": "project", "kind": "step", "status": "active", "title": "프로젝트 적용", "sub": "실행 전 선택분 · 도움창 검색·적용", **_col(1)},
        {"id": "query", "kind": "step", "status": "pending", "title": "BOM 조회(F2)", "sub": "이동요청 해제 · 구매요청만", **_col(2)},
        {"id": "read", "kind": "step", "status": "pending", "title": "BOM 트리 읽기", "sub": "장비·모듈(SET)·부품 조립", **_col(3)},
        {"id": "plan", "kind": "step", "status": "pending", "title": "발주 계획서 작성", "sub": "발주단위·사유·납기·거래처(사용자 개입)", **_col(4)},
        {"id": "confirm", "kind": "decision", "status": "pending", "title": "계획 검증", "sub": "사유·납기·의사 거래처 확정 확인", **_col(5)},
        {"id": "save_move", "kind": "step", "status": "pending", "title": "이동요청 저장", "sub": "전체 선택 · 공용자재→프로젝트 · 저장(IRQ)", **_col(6)},
        {"id": "save_units", "kind": "step", "status": "pending", "title": "구매요청 저장 반복", "sub": "발주단위별 SET 선택·납기·사유 · 저장(PRQ)", **_col(7)},
        {"id": "approve", "kind": "step", "status": "pending", "title": "셀프결재 상신", "sub": "구매요청처리 · EAP 상신(사용자 확인)", **_col(8)},
        {"id": "orders", "kind": "step", "status": "pending", "title": "구매발주 저장", "sub": "일괄입력 · 거래처 변경·납기·비고 · 저장(사용자 확인)", **_col(9)},
        {"id": "report", "kind": "end", "status": "pending", "title": "결과 반환", "sub": "IRQ/PRQ/상신/발주번호", **_col(10)},
    ],
    "edges": [
        {"id": "e-access-project", "source": "access", "target": "project"},
        {"id": "e-project-query", "source": "project", "target": "query"},
        {"id": "e-query-read", "source": "query", "target": "read"},
        {"id": "e-read-plan", "source": "read", "target": "plan"},
        {"id": "e-plan-confirm", "source": "plan", "target": "confirm"},
        {"id": "e-confirm-plan", "source": "confirm", "target": "plan", "label": "보완 ↩", "kind": "loop"},
        {"id": "e-confirm-save", "source": "confirm", "target": "save_move", "label": "저장 승인", "kind": "branch"},
        {"id": "e-save-units", "source": "save_move", "target": "save_units"},
        {"id": "e-units-approve", "source": "save_units", "target": "approve"},
        {"id": "e-approve-orders", "source": "approve", "target": "orders"},
        {"id": "e-orders-report", "source": "orders", "target": "report"},
    ],
}


# ── 구매발주 — 실동작 승격(purchase-order 워크플로우, Phase A 2026-08-13) ─────────
# placeholder 를 제자리 승격한다(agent id "purchase-order" 유지 — 프론트/시드 연속성).
# steps 의 key 는 build_purchase_order_graph 노드 등록 순서와 1:1(진행 하이라이트 정합).
# HITL 은 plan 한 스텝만(kind 'planner', full) — pick_project 의 검색 개입 폴백은
# 2026-08-14 제거(실행 전 폼이 프로젝트 필수, 적용 실패 = 하드 실패). hidden=False 유지.
_PURCHASE_ORDER_FIXTURE: dict = {
    "id": "purchase-order",
    "workflow_id": "purchase-order",
    "group_id": "purchase",
    "hidden": False,
    "name": "구매발주",
    "description": (
        "프로젝트를 검색해 BOM 을 불러오고, 모듈(SET)을 발주단위로 묶어 구매사유·납기예정일과 "
        "거래처를 계획서로 확정합니다. 확인 후 이동요청 저장 → 발주단위별 구매요청 저장 → "
        "구매요청처리에서 셀프결재 상신까지 진행합니다."
    ),
    "handoff_note": (
        "이 실행은 구매요청 저장과 셀프결재 상신까지입니다. 구매발주일괄입력(화면 ③)의 거래처 "
        "적용·납기 확정·저장은 아직 자동화되지 않았으니 결과의 구매요청번호(PRQ)로 옴니솔에서 직접 "
        "진행해 주세요."
    ),
    "drive": "browser",
    "interaction": "autonomous",
    "target_system": "더존 옴니솔",
    "target_url": "erp.ninebell.co.kr",
    "status": "idle",
    "progress": 0,
    # 계획서 개입(plan)은 최대 30분 대기(PLAN_TIMEOUT_S) — HITL 대기는 런 예산에서 제외되지만
    # 표시용 상한은 넉넉히 잡는다.
    "timeout_seconds": 600,
    "elapsed_seconds": 0,
    "current_action": "대기 중 — 실행을 누르면 시작합니다",
    "run_count": 0,
    "success_rate": 0.0,
    "avg_seconds": 0,
    "last_run_at": None,
    "flow_graph": PURCHASE_ORDER_FLOW,
    "steps": [
        {"key": "login", "label": "로그인", "skill": "login", "status": "pending", "phase": "접속", "detail": "더존 옴니솔 인증 후 세션 확보"},
        {"key": "user_type", "label": "SCM-구매 전환", "skill": "user-type", "status": "pending", "phase": "접속", "detail": "사용자 유형을 'SCM-구매'로 전환"},
        {"key": "menu_nav", "label": "프로젝트BOM구매요청 화면", "skill": "menu-nav", "status": "pending", "phase": "접속", "detail": "구매(PU) > 프로젝트BOM구매요청[나인벨](PUOPRQ00200) 진입"},
        {
            "key": "pick_project", "label": "프로젝트 적용", "skill": "codepicker", "status": "pending",
            "phase": "프로젝트",
            "detail": "실행 전 입력에서 고른 프로젝트를 도움창 검색·선택으로 적용 → 반영 확인·조회(F2)",
        },
        {"key": "read_bom", "label": "BOM 읽기", "skill": "grid-read", "status": "pending", "phase": "BOM", "detail": "이동요청 해제(구매요청만) → 조회(F2) → 트리그리드 전량 읽기 → 계획서 BOM 조립"},
        {
            "key": "plan", "label": "발주 계획서 작성", "skill": "grid-input", "status": "pending",
            "intervention": True,
            "phase": "계획",
            "detail": "발주단위 묶음 + 구매사유·납기예정일 + 거래처 확정을 계획서로 제출(사용자 개입, 최대 30분)",
        },
        {"key": "save_move", "label": "이동요청 저장", "skill": "save", "status": "pending", "phase": "저장", "detail": "이동요청만 조회 → 전체 선택 → 이동출고=공용자재·이동입고=프로젝트 적용 → 저장(이동요청번호 IRQ)"},
        {"key": "save_units", "label": "구매요청 저장(발주단위별)", "skill": "save", "status": "pending", "phase": "저장", "detail": "구매요청만 조회 → SET 선택(자손 정확 일치 검증) → 납기예정일 적용 → 구매사유 → 저장(PRQ) 반복"},
        {
            "key": "self_approve", "label": "셀프결재 상신", "skill": "eap-submit", "status": "pending",
            "phase": "결재",
            "detail": "구매요청처리(PUOPRQ00300) 진입 → PRQ 조회·가드(결재상태 저장) → 결재창(EAP) 상신(보관 미클릭) — 자동 진행",
        },
        {
            "key": "place_orders", "label": "구매발주 저장(거래처별)", "skill": "save", "status": "pending",
            "phase": "발주",
            "detail": "구매발주일괄입력(PUOORD02000) — 발주단위별 구매요청 팝업 → 가공품/판금품 거래처 변경 → 적용 → 거래처별 납기·비고 → 저장(발주번호) — 자동 진행",
        },
        {"key": "report", "label": "결과 반환", "skill": "grid-read", "status": "pending", "phase": "완료", "detail": "계획 + 이동요청/구매요청/상신/발주번호 결과 반환"},
    ],
    "logs": [],
}


# ── 구매팀 — 자리만 잡은 빈 에이전트(사용자 지정 2026-08-12) ─────────────────────
# 업무 정의 전이라 설명·현재동작·단계·플로우를 **비워 둔다**. workflow_id=None 이라 실행
# 컨트롤은 비활성이고(프론트 canRun=false), steps/flow_graph 가 비어 워크플로우 탭에
# 없는 계획을 그리지 않는다(세금계산서 관례 — 그래프 없이 계획을 그리면 거짓이 된다).
# 그래프를 붙일 때 workflow_id·steps·flow_graph·description 을 채워 실동작으로 승격한다.
def _placeholder_fixture(agent_id: str, name: str, group_id: str) -> dict:
    return {
        "id": agent_id,
        "workflow_id": None,
        "group_id": group_id,
        "hidden": False,
        "name": name,
        "description": "",
        "drive": "browser",
        "interaction": "autonomous",
        "target_system": "더존 옴니솔",
        "target_url": "erp.ninebell.co.kr",
        "status": "idle",
        "progress": 0,
        "timeout_seconds": 240,
        "elapsed_seconds": 0,
        "current_action": "",
        "run_count": 0,
        "success_rate": 0.0,
        "avg_seconds": 0,
        "last_run_at": None,
        "flow_graph": None,
        "steps": [],
        "logs": [],
    }


AGENT_FIXTURES.extend(
    [
        _placeholder_fixture("item-bulk-register", "품목일괄등록", "purchase"),
        # 구매발주 = Phase A 실동작 승격(2026-08-13 — 읽기 그래프 + 계획서 HITL, 저장 없음).
        # 구매발주 데모(purchase-order-demo)는 2026-08-21 제거 — seed 가 DB 행도 prune 한다.
        _PURCHASE_ORDER_FIXTURE,
        _EAP_CANCEL_FIXTURE,
        _cleanup_fixture("trip-domestic-cleanup", "출장(국내/자차)", "출장(국내·자차)"),
        _cleanup_fixture("trip-overseas-cleanup", "출장(해외/정산서)", "출장(해외·정산서)"),
        _cleanup_fixture("card-collect-cleanup", "법인카드", "카드"),
        _cleanup_fixture("gyeongjo-grant-cleanup", "경조금", "경조금신청서"),
        _cleanup_fixture("hakjagum-grant-cleanup", "학자금", "학자금신청서"),
        _cleanup_fixture("tax-invoice-cleanup", "세금계산서", "세금계산서"),
    ]
)

AGENT_FIXTURES.extend(
    [
        _TRIP_DOMESTIC_FIXTURE,
        _TRIP_OVERSEAS_FIXTURE,
        _GYEONGJO_GRANT_FIXTURE,  # family-event 더미 → 실동작 승격(gyeongjo-grant).
        _HAKJAGUM_GRANT_FIXTURE,  # scholarship 더미 → 실동작 승격(hakjagum-grant, 노출).
        _TAX_INVOICE_FIXTURE,  # 결의서입력 — 프론트 화면 시뮬레이션(실행 비활성).
        # 회계전표 그룹 — 유형별 전표조회 승인(매출/매입 병합, 2026-08-20) → 미지급금 법인카드.
        _VOUCHER_BY_TYPE_FIXTURE,  # voucher-by-type(국내매출/해외매출/내수구매 실행 시 선택)
        _VOUCHER_CARD_FIXTURE,  # voucher-card-payable → voucher-card(미지급금 법인카드)
    ]
)
