/**
 * 라이브 런(SSE) 도메인 타입 — 백엔드 이벤트 모델(app/live/events.py)과 1:1.
 *
 * SSE 프레임은 모두 "평탄한 dict"이며 한 프레임에 하나의 판별 키(step/log/screenshot/
 * hitl/chat/transactions/result/error)만 들어온다. 그래서 유니온을 태그드 유니온이 아니라
 * 모든 키가 옵셔널인 {@link LiveFrame} 로 모델링하고, 키 존재로 좁힌다(파싱이 단순해진다).
 *
 * 프레임 계약(고정 — 백엔드 app/live/events.py 와 1:1):
 *   {"step": str, "status": "running"|"done"|"failed", "ms"?: int}
 *   {"log": str, "level": "info"|"ok"|"error"|"warn"}
 *   {"screenshot": "data:image/jpeg;base64,...", "window"?: "parent"|"child"}  // 비버퍼(창별 최신 1장)
 *   {"window": "child", "closed": true}                    // 자식 창 닫힘 전이(버퍼/커서 대상 — 재생 가능)
 *   {"hitl": {"id","kind","title","prompt","options"?}}
 *   {"chat": {"id","role","content","streaming"?,"done"?,"note"?}}
 *   {"transactions": {"title","columns","rows"}}
 *   {"result": str}                                        // 종료(성공)
 *   {"error": str}                                         // 종료(실패)
 */

// ── 스칼라 ───────────────────────────────────────────────────────────

/** 단계 상태(백엔드 emit_step) — UI 스텝 상태(done/active/…)와는 별개. */
export type LiveStepStatus = 'running' | 'done' | 'failed';

/** 로그 레벨(백엔드 emit_log). ok=성공, warn/error/info. */
export type LiveLogLevel = 'info' | 'ok' | 'warn' | 'error';

/** 채팅 롤(백엔드 emit_chat). */
export type ChatRole = 'user' | 'assistant' | 'system';

/**
 * HITL 종류. demo-echo 는 `confirm`(옵션 yes/no), 실 에이전트는 `chat`(대화형) 등을 쓴다.
 * 알 수 없는 종류가 와도 무너지지 않도록 문자열 유니온으로 열어 둔다.
 */
export type LiveHitlKind =
  | 'confirm'
  | 'select'
  | 'multiselect'
  | 'input'
  | 'search'
  | 'chat'
  | 'grid'
  | 'invoice-grid'
  | 'planner'
  | (string & {});

// ── 서브 페이로드 ────────────────────────────────────────────────────

export interface LiveHitlOption {
  value: string;
  label: string;
  description?: string;
  recommended?: boolean;
}

/**
 * 그리드 개입(kind=grid) 한 행 — 카드 거래내역. 표시 컬럼은 읽기 전용이며,
 * 사용자는 행마다 예산단위·프로젝트·적요를 채운다. no 는 행 식별자(제출 시 키).
 * 백엔드 진화 중 컬럼이 빠질 수 있어 표시 필드는 모두 옵셔널로 둔다.
 */
export interface LiveGridRow {
  no: number;
  card?: string;
  merchant?: string;
  amount?: string;
  date?: string;
  time?: string;
  approved?: string;
  vatType?: string;
  /** 부가세구분 기본값(자동 분류) — '과세' 또는 '불공'. 사용자가 그리드에서 덮어쓸 수 있다. */
  vat?: string;
  /** 가맹점 기반 부가세 판정(AI) — '불공'이면 계정 무관 불공(통행료·우체국·유류). 계정 변경 시
   *  부가세구분을 원본 기준으로 복원할 때 쓴다(계정 불공만이 사유였는지 구분). */
  vatDeduction?: string;
  /** 적요 기본값(입력 프리필). */
  note?: string;
  /** 예산단위 프리셀렉트(AI 추천 또는 기본지정). 없으면 null/미포함. */
  budgetUnit?: BudgetUnitOption | null;
  /** 프로젝트 프리셀렉트(AI 추천 또는 기본지정). 없으면 null/미포함. */
  project?: ProjectOption | null;
  /** 예산단위 프리셀렉트 출처 — 'ai'=AI 추천, 'default'=기본지정 즐겨찾기. */
  budgetSource?: PrefillSource | null;
  /** 프로젝트 프리셀렉트 출처 — 'ai'=AI 추천, 'default'=기본지정 즐겨찾기. */
  projectSource?: PrefillSource | null;
  /** 적요 프리필 출처 — 'learned'=개입 학습, 'seed'=전사 기초자료. 키워드 휴리스틱은 null. */
  noteSource?: PrefillSource | null;
  /** 저장 실패 재시도 시 이 행의 조치 안내(예: 예산계정이 무엇과 같아야 하는지). 있으면 강조. */
  error?: string;
}

/**
 * 계산서 개입(kind='invoice-grid') 한 행 — 발행 후 '전자세금계산서/전자계산서' 팝업 그리드의
 * 계산서 1건. 표시 전용이며, 사용자는 **처리할 행을 고르고**(기본 미선택) 고른 행에만
 * 예산단위·프로젝트·적요를 채운다. no 는 행 식별자(제출 시 키).
 *
 * 카드 그리드(kind='grid', {@link LiveGridRow})와 표시 컬럼이 전혀 달라 별도 타입이며,
 * 프레임에서도 별도 키(invoiceRows)로 온다 — planner 의 plannerBom 과 같은 관례.
 * 백엔드 진화 중 컬럼이 빠질 수 있어 no 외 표시 필드는 모두 옵셔널이다.
 */
export interface InvoiceGridRow {
  no: number;
  /** 계산서일(START_DT) — 표시 그대로. 선택 행의 마지막 값이 회계일이 된다. */
  invoiceDate?: string;
  partnerName?: string;
  partnerCode?: string;
  /** 원 단위 정수. 취소분은 음수. */
  supplyAmount?: number;
  taxAmount?: number;
  sumAmount?: number;
  /** 국세청 승인번호(NTS_APRVL_NO). */
  ntsAprvlNo?: string;
  itemName?: string;
  /** 전자세금계산서종류(DATA_FG_NM) — '취소'가 들어가면 취소분으로 표시한다. */
  dataKind?: string;
}

/** 그리드 프리셀렉트 출처. ai=AI 추천(높은 확신), default=기본지정 즐겨찾기 폴백,
 * learned=개입 학습, seed=전사 기초자료, lookup=예산계정 변경에 맞춰 실시간 재추천된 적요. */
export type PrefillSource = 'ai' | 'default' | 'learned' | 'seed' | 'lookup' | 'mirror';

/** 예산단위 보기 한 항목(자주쓰는/전체 공용). deptNm 은 부서명(있을 때). */
/** 예산단위 보기 — 선택 단위는 (예산단위명 × 사업계획명 × 예산계정명) 조합 행.
 * code 는 BG|BIZPLAN|BGACCT 복합키. */
export interface BudgetUnitOption {
  code: string;
  name: string;
  bizplanNm?: string;
  /** 예산계정 코드 — 계정 인지 적요 추천(note-suggest)의 매칭 키. 내 부서/전체 그룹에만 실려
   * 오고 즐겨찾기엔 없을 수 있어(bgacctNm 만), 없으면 복합 code(BG|BIZPLAN|BGACCT)에서 뽑는다. */
  bgacctCd?: string;
  bgacctNm?: string;
  /** 과거 데이터 하위호환(미사용). */
  deptNm?: string;
}

/** 프로젝트 보기 한 항목(자주쓰는/검색결과 공용). 선택 단위는 WBS 행 — code=PJT_NO|WBS_NO 복합.
 * name=프로젝트명(PJT_NM), wbsNo=WBS요소, wbsNm=WBS요소명. */
export interface ProjectOption {
  code: string;
  name: string;
  wbsNo?: string;
  wbsNm?: string;
}

/** 그리드 개입의 예산단위 보기 — 자주쓰는 → 내 부서(이름 정규화 매칭) → 전사 전체. */
export interface HitlBudgetUnits {
  favorites?: BudgetUnitOption[];
  /** 내 부서 매칭(예: 소속 '인사/기획팀' ↔ 예산단위 '인사기획팀'). */
  mine?: BudgetUnitOption[];
  all?: BudgetUnitOption[];
}

// ── 계획서 개입(kind=planner) — 구매발주 BOM 계약 ───────────────────

/**
 * 발주 계획서 BOM 리프(부품, 트리그리드 getLevel()==4).
 * 백엔드 계획서 HITL(plannerBom)이 내려주는 shape — 백/프론트 공유 계약.
 */
export interface PlannerBomPart {
  itemCode: string;
  name: string;
  spec: string;
  unit: string;
  bomQty: number;
  remainQty: number;
  unitPrice: number;
  amount: number;
  /** 품목거래처명 — '가공품'/'판금품'은 의사 거래처(실거래처 지정 필요), 그 외는 실거래처. */
  vendorClass: string;
  account: string;
  purchasable: boolean;
}

/** 3레벨 모듈(SET) — 발주단위로 묶는 선택 단위(getLevel()==3). */
export interface PlannerBomModule {
  itemCode: string;
  name: string;
  spec: string;
  unit: string;
  bomQty: number;
  parts: PlannerBomPart[];
}

/** 장비(레벨 1). 레벨 2 구조행은 계층 접힘이라 modules 로 평탄화되어 온다. */
export interface PlannerBomMachine {
  itemCode: string;
  name: string;
  spec: string;
  unit: string;
  modules: PlannerBomModule[];
}

/** kind=planner 프레임의 plannerBom — 프로젝트 + 장비→모듈→부품 트리. */
export interface PlannerBom {
  project: { code: string; name: string; wbs: string };
  machines: PlannerBomMachine[];
}

/** 계획 제출의 발주단위 모듈(식별 3필드). */
export interface PlanUnitModule {
  itemCode: string;
  name: string;
  spec: string;
}

/** 계획 제출의 거래처 그룹 — 오버라이드가 없으면 파생 기본값으로 접힌 최종값. */
export interface PlanVendorGroup {
  vendorClass: string;
  /** 유효 거래처명 — 의사 거래처는 지정/기본 거래처, 실거래처는 vendorClass 그대로. 미지정 null. */
  vendor: string | null;
  parts: number;
  amount: number;
  dueDate: string;
  note: string;
}

/** 계획 제출의 발주단위 1건 — 구매요청 저장 1회(발주번호 1건)에 해당. */
export interface PlanUnit {
  seq: number;
  purchaseReason: string;
  dueDate: string;
  modules: PlanUnitModule[];
  vendorGroups: PlanVendorGroup[];
}

/** kind=planner 제출 계획(POST /runs/hitl plan) — 데모 buildPlanPayload 반환 shape 그대로. */
export interface PlanSubmit {
  project: { code: string; name: string };
  wbs: string;
  units: PlanUnit[];
}

/** 그리드 개입의 프로젝트 보기 — 자주쓰는 + ERP 검색 결과(질의 후 채워짐). */
export interface HitlProjects {
  favorites?: ProjectOption[];
  /** ERP 검색 응답. 검색 전이면 null. */
  searchResults?: ProjectOption[] | null;
  /** 직전 검색어(검색 전이면 null). */
  query?: string | null;
}

export interface LiveHitl {
  id: string;
  kind?: LiveHitlKind; // 미지정 시 select 취급
  title: string;
  prompt?: string;
  options?: LiveHitlOption[];
  /** 보기에 없을 때 직접 입력 허용(select/search). */
  allowText?: boolean;
  textLabel?: string;
  /** kind=search 일 때 검색창 placeholder. */
  searchPlaceholder?: string;
  /** kind=grid — 채워야 할 거래내역 행(없으면 빈 그리드). */
  rows?: LiveGridRow[];
  /** kind=invoice-grid — 고를 계산서 행(없으면 빈 그리드). */
  invoiceRows?: InvoiceGridRow[];
  /** kind=invoice-grid — 비용분할(증빙 11/13) 여부. true 면 계산서 1행 선택 + 분할 계획을 함께 받는다. */
  split?: boolean;
  /** kind=grid·invoice-grid — 예산단위 보기(자주쓰는/전체). */
  budgetUnits?: HitlBudgetUnits;
  /** kind=grid — 프로젝트 보기(자주쓰는/검색결과). invoice-grid 는 favorites 만 쓴다(검색은 카탈로그 API). */
  projects?: HitlProjects;
  /** kind=planner — 발주 계획서 BOM(프로젝트 + 장비→모듈→부품). */
  plannerBom?: PlannerBom;
  /** 재개입 공지 — 직전 저장(F7) 실패 사유+조치(왜 다시 선택해야 하는지). 첫 진입엔 없음. */
  notice?: string;
}

/** 그리드 개입 제출 한 행 — 비제외(skip=false) 행은 budgetUnit·note 필수, project 선택. */
export interface GridRowSubmit {
  no: number;
  /** 예산단위 조합 선택 — bizplanNm/bgacctNm 이 있으면 서버가 그 조합 행을 정확히 고른다. */
  budgetUnit: { code: string; name: string; bizplanNm?: string; bgacctNm?: string } | null;
  /** 프로젝트 WBS 행 — wbsNo 가 있으면 서버가 그 WBS 요소를 정확히 고른다. */
  project: { code: string; name: string; wbsNo?: string } | null;
  note: string;
  skip: boolean;
  /** 부가세구분(최종) — '과세' 또는 '불공'. 저장 2패스 파티션(증빙 01=과세 / 02=불공)을 구동한다. */
  vat?: string;
  /** 개입 학습용 — 사용자가 프리필값에서 **실제로 바꾼** 필드 표시. 바꾼 것만 학습한다
   * (프리필 그대로 수락은 학습 안 함 — 자기추천 되먹임 방지). */
  budgetEdited?: boolean;
  projectEdited?: boolean;
  noteEdited?: boolean;
}

/**
 * 비용분할 계획 한 행(kind='invoice-grid' 분할 모드) — ERP 분할처리 팝업의 행 1개에 대응.
 *
 * **마지막 행은 amount=null** — ERP 의 '차액반영' 버튼이 잔액을 흡수한다(수동 계산 금지).
 * 실행 전 폼 계약 `split_rows` 와 같은 규칙이며, 입력받는 자리만 개입 화면으로 옮겨졌다.
 */
export interface SplitPlanRowSubmit {
  note: string;
  /** 원 단위 정수(음수 허용 — 취소분). 마지막 행은 null=차액반영. */
  amount: number | null;
  costCenter: string;
  /** 프로젝트 WBS 요소(WBS_NO). */
  projectWbs: string;
}

/** SSE chat 프레임(백엔드 emit_chat) — 화면 표시용 ChatMessage 로 변환된다. */
export interface ChatFrame {
  id: string;
  role: ChatRole;
  content: string;
  streaming?: boolean;
  done?: boolean;
  /** action = 채움 실행로그 말풍선(누적 표시). 그 외 어시스턴트 메시지는 id 로 upsert. */
  note?: 'action';
}

export interface LiveTxColumn {
  key: string;
  header: string;
  align?: 'right';
}

export interface LiveTransactions {
  title: string;
  columns: LiveTxColumn[];
  rows: Array<Record<string, string | number>>;
}

// ── 프레임(와이어) ───────────────────────────────────────────────────

/**
 * 한 SSE 프레임. 하나의 판별 키만 존재한다. 파서는 키 존재로 좁혀서 상태에 반영한다.
 * (백엔드가 평탄한 dict 로 보내므로 태그드 유니온보다 이 형태가 파싱에 유리하다.)
 */
export interface LiveFrame {
  step?: string;
  status?: LiveStepStatus;
  ms?: number;
  /** 반복 스텝 진행 카운트(백엔드 emit_step progress) — 워크플로우 노드에 done/total 표시. */
  progress?: LiveStepProgress;
  log?: string;
  level?: LiveLogLevel;
  screenshot?: string;
  /**
   * 스크린샷/닫힘 프레임이 어느 브라우저 창인지 — 'parent'(주 페이지) 또는 'child'(진짜 두 번째
   * 창, 예: SSO 교차출처 전자결재 팝업). 없으면 'parent'(하위 호환 — 기존 단일 페이지 프레임).
   */
  window?: LiveWindow;
  /** 자식 창 닫힘 전이(window='child' 와 함께) — FE 는 자식 화면을 버리고 부모창으로 복귀한다. */
  closed?: boolean;
  hitl?: LiveHitl;
  chat?: ChatFrame;
  transactions?: LiveTransactions;
  result?: string;
  error?: string;
}

/** 라이브 뷰의 브라우저 창 구분 — 주 페이지(parent) / 팝업·자식 창(child). */
export type LiveWindow = 'parent' | 'child';

/** HITL 응답 페이로드 — 종류에 따라 하나 이상이 채워진다(POST /runs/hitl body). */
export interface HitlPayload {
  value?: string;
  values?: string[];
  text?: string;
  query?: string;
  message?: string;
  done?: boolean;
  /** kind=grid·invoice-grid 일괄 제출 — 행별 예산단위·프로젝트·적요·제외. */
  rows?: GridRowSubmit[];
  /** kind=invoice-grid 분할 모드 제출 — rows 와 함께 보낸다(선택 1행의 분할 계획). */
  splitPlan?: SplitPlanRowSubmit[];
  /** kind=planner 제출 — 발주 계획(발주단위·거래처 그룹). */
  plan?: PlanSubmit;
}

// ── UI 상태 ──────────────────────────────────────────────────────────

/** 라이브 런의 표시 상태. */
export type LiveRunStatus =
  | 'idle' // 세션 없음
  | 'connecting' // /runs/collect 연결 시도 중
  | 'running' // 흐름 진행 중
  | 'waiting_input' // HITL 대기(사용자 입력 필요)
  | 'succeeded' // result 수신(종료)
  | 'failed'; // error/연결실패(종료)

/** 누적 단계(스텝 이름으로 upsert). */
/** 반복 스텝 진행 카운트 — 예: 결재 순회 {done:2,total:5} → "2/5". */
export interface LiveStepProgress {
  done: number;
  total: number;
}

export interface LiveStepState {
  step: string;
  status: LiveStepStatus;
  ms?: number;
  progress?: LiveStepProgress;
}

/** 누적 로그 한 줄. */
export interface LiveLogLine {
  id: string;
  message: string;
  level: LiveLogLevel;
}

/** 화면 표시용 채팅 메시지(사용자 낙관 추가 + 어시스턴트 스트림 반영). */
export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  streaming?: boolean;
  /** 전송 실패한 사용자 말풍선 표시. */
  error?: boolean;
  note?: 'action';
}

/** useLiveRun 이 노출하는 라이브 상태 스냅샷 + 액션. */
export interface LiveRunState {
  /** 이 세션에 사용된 runId(재접속·HITL 에 동봉). 세션 미시작이면 null. */
  runId: string | null;
  status: LiveRunStatus;
  steps: readonly LiveStepState[];
  logs: readonly LiveLogLine[];
  /** 활성 창의 최신 스크린캐스트 dataURL(하위 호환 파생 — screenshots[activeWindow]). 없으면 null. */
  screenshot: string | null;
  /** 창별 최신 스크린캐스트 dataURL. 자식 창(팝업)이 없으면 child=null. */
  screenshots: { parent: string | null; child: string | null };
  /** 라이브 뷰에 현재 표시할 창 — 자식 창이 열리면 자동 활성화, 닫히면 parent 로 복귀. */
  activeWindow: LiveWindow;
  /** 활성 HITL(대기 중). 없으면 null. */
  hitl: LiveHitl | null;
  chat: readonly ChatMessage[];
  transactions: LiveTransactions | null;
  result: string | null;
  error: string | null;
  /** SSE 스트림이 현재 붙어 있는지(끊김 표시용). */
  connected: boolean;
}

export interface LiveRunActions {
  /** HITL 응답 전달(POST /runs/hitl). 성공 시 true. */
  sendHitl: (decisionId: string, payload: HitlPayload) => Promise<boolean>;
  /** 대화형 HITL 한 턴 — 사용자 말풍선 낙관 추가 + message 전송. */
  sendChat: (decisionId: string, text: string) => Promise<boolean>;
  /** 대화형 HITL 종료 — done 신호(BE 가 마무리 → result). */
  finishChat: (decisionId: string) => Promise<boolean>;
  /** 그리드 개입 — 프로젝트 ERP 검색 질의(BE 가 searchResults 를 채운 새 hitl 프레임을 보냄). */
  sendQuery: (decisionId: string, query: string) => Promise<boolean>;
  /** 그리드 개입 — 행 일괄 제출(채움 실행 재개). splitPlan 은 계산서 분할 개입에서만 동봉한다. */
  sendRows: (
    decisionId: string,
    rows: GridRowSubmit[],
    splitPlan?: SplitPlanRowSubmit[],
  ) => Promise<boolean>;
  /** 계획서 개입(kind=planner) — 발주 계획 확정 제출(실행 재개, 낙관적 clearHitl). */
  sendPlan: (decisionId: string, plan: PlanSubmit) => Promise<boolean>;
  /** 라이브 뷰 창 수동 전환(부모창/자식창 탭). 자식 창은 열릴 때 자동 활성화된다. */
  selectWindow: (window: LiveWindow) => void;
}

export type UseLiveRunReturn = LiveRunState & LiveRunActions;
