"""건별 입력(그리드 HITL) 노드 — 행 그리드 방출·일괄 제출 검증·1차(과세) 반영."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app.config import get_settings
from app.db import get_sessionmaker
from app.live.events import emit_chat, emit_hitl, emit_log, emit_step
from app.live.hitl import close_hitl_channel, open_hitl_channel
from app.services import card_learning
from app.services.code_sync import dept_matches_budget_name

from .. import steps, vat as vat_rules
from . import _shared, batch, catalog, prefill
from .save import MAX_SAVE_RETRIES, _save_guidance  # 재개입 그리드 상단 직전 저장 실패 사유+조치.

logger = logging.getLogger("app.agents.card_collect.nodes.collect")


def _validate_grid_submit(rows_in: list[dict], n: int) -> tuple[bool, str]:
    """제출 rows 서버검증. 비스킵 행은 예산단위(code·name)·예산계정·프로젝트·적요 필수, 행번호는 1..n.

    행 집합은 정확히 {1..n}(중복·누락 불허) — 부분 제출을 허용하면 빠진 행이 조용히 pending
    으로 남고, 중복 no 는 같은 ERP 행을 이중 반영한다(리뷰 MEDIUM #3). (ok, reason) 반환.
    """
    seen: set[int] = set()
    for row in rows_in:
        no = row.get("no")
        if not isinstance(no, int) or not (1 <= no <= n):
            return False, f"행 번호가 올바르지 않습니다: {no!r}"
        if no in seen:
            return False, f"행 번호가 중복됐습니다: {no}"
        seen.add(no)
        if row.get("skip"):
            continue
        bu = row.get("budgetUnit") or {}
        if not (bu.get("code") and bu.get("name")):
            return False, f"{no}행 예산단위를 선택해 주세요."
        # 예산계정(bgacctNm)·프로젝트·적요는 ERP 저장 시 필수 — 비면 조용히 넘어가 F7 이
        # "상세그리드 필수값 미입력"으로 거부된다(사용자 규명 2026-07-10). 제출 단계에서 막는다.
        if not (bu.get("bgacctNm") or "").strip():
            return False, f"{no}행 예산계정이 비어 있습니다 — 예산단위를 다시 선택해 주세요."
        pj = row.get("project") or {}
        if not (pj.get("code") and pj.get("name")):
            return False, f"{no}행 프로젝트를 선택해 주세요."
        if not (row.get("note") or "").strip():
            return False, f"{no}행 적요를 입력해 주세요."
    if len(seen) != n:
        missing = sorted(set(range(1, n + 1)) - seen)[:5]
        return False, f"모든 행이 포함돼야 합니다(누락: {missing} …)."
    return True, ""


# ── 항목 처리(그리드 HITL): 행 그리드 방출 → 일괄 제출(rows) 을 순차 반영 ──────────────
def make_collect_rows_node(timeout_s: int | None = None):
    async def collect_rows(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        rows_list: list[dict] = state.get("rows_list") or []
        # 'AI 추천 준비(prefill)' — 이 노드에서 그리드가 뜨기 전 가장 오래 걸리는 자동 구간
        # (카탈로그·개입학습 로드 + Gemini 추천 콜). 화면이 멈춰 보인다는 피드백(2026-07-06)에
        # 따라 별도 스텝으로 방출해 레일·ETA 타임라인에 진행이 보이게 한다. 그래프 노드는
        # 아니고 노드 내부(intra-node) 스텝 — 픽스처·1:1 테스트에 같은 이름으로 선언돼 있다.
        await emit_step(events, "prefill", "running")
        t0 = time.monotonic()
        if not rows_list:
            period = state.get("period") or []
            period_txt = f"{period[0]} ~ {period[1]}" if len(period) == 2 else "이번 조회 기간"
            # 조회는 정상 실행됐지만 결과가 0건인 경우 — 채팅에 명확히 알리고 **그래프를 여기서
            # 종료**한다(no_rows 조건부 엣지 → END, 사용자 확정 2026-07-05: 뒤 단계(문서 반영·
            # 저장)를 돌리지 않고 '처리할 내역이 없습니다'로 즉시 끝낸다). 이미 전표로 처리된
            # 승인내역은 재조회에 안 나오므로, 직전 저장 후 재실행하면 이 경로가 정상이다.
            await emit_chat(
                events,
                chat_id="cc-empty",
                role="assistant",
                content=f"{period_txt} 기간에 해당하는 법인카드 승인내역이 0건입니다. 처리할 항목이 없어 이대로 종료합니다.",
                streaming=False,
            )
            await emit_log(events, "처리할 승인내역이 없습니다.", "warn")
            await emit_step(events, "prefill", "done", _shared._ms(t0))
            await emit_step(events, "collect_rows", "running")
            await emit_step(events, "collect_rows", "done", 0)
            return {
                "filled": 0,
                "no_rows": True,
                "result": f"처리할 내역이 없습니다 — {period_txt} 승인내역 0건.",
            }

        settings = get_settings()
        wait_timeout = timeout_s if timeout_s is not None else settings.hitl_timeout_s
        n = len(rows_list)

        # 행별 추천 적요(prefill) + 처리 현황(status)·적요(notes) 트래킹. status/notes 는
        # r.get("i", idx)(=행 인덱스, 제출행 no-1 과 동일)를 키로 쓴다(_status_table 과 같은 규칙).
        recs = {r.get("i", idx): _shared.recommend_note(r.get("TRAN_NM") or "", r.get("TRAN_AMT") or "")
                for idx, r in enumerate(rows_list)}
        status: dict[int, str] = {r.get("i", idx): "pending" for idx, r in enumerate(rows_list)}
        notes = dict(recs)

        # 즐겨찾기·부서(DB) + 예산단위 목록. 카탈로그 캐시(erp_code_catalog) 우선 — 라이브
        # 피커 전량 덤프(~3.4s)는 캐시가 빌 때만 폴백(속도 최적화 2026-07-04).
        budget_favs, project_favs, department = await catalog._load_user_favorites(state.get("owner"))
        try:
            all_units = await catalog._load_budget_catalog()
        except Exception:  # noqa: BLE001 — 캐시 조회 실패로 런을 죽이지 않는다.
            logger.exception("card-collect budget catalog load failed")
            all_units = []
        if all_units:
            await emit_log(events, f"예산단위 {len(all_units)}건 — 카탈로그 캐시 사용(덤프 생략).", "info")
        else:
            try:
                all_units = await steps.dump_budget_units(page)
            except Exception:  # noqa: BLE001 — 덤프 실패로 런을 죽이지 않는다.
                logger.exception("card-collect dump_budget_units failed")
                all_units = []
        if not all_units:
            await emit_log(events, "예산단위 목록을 불러오지 못했습니다(즐겨찾기·검색으로 진행).", "warn")

        # '내 부서' = 예산단위명 ↔ 소속부서 정규화 매칭('인사/기획팀' ↔ '인사기획팀').
        mine_units = [u for u in all_units if dept_matches_budget_name(department, u["name"])]
        # 소속 팀 비용구분(판관비→'(판)' / 제조원가→'(제)') 이 있으면 그 접두사 계정을 우선한다
        # (내 부서 목록·AI 후보·기본 폴백 순서에 반영). 없으면 기존 순서 유지.
        cost_type = (state.get("params") or {}).get("cost_type")
        cost_prefix = catalog._COST_PREFIX.get(cost_type or "")
        if cost_prefix:
            await emit_log(
                events, f"소속 팀 비용구분 '{cost_type}' → 예산계정 '{cost_prefix}' 우선 선택.", "info"
            )
            mine_units = sorted(
                mine_units,
                key=lambda u: 0 if (u.get("bgacctNm") or "").startswith(cost_prefix) else 1,
            )
        # 그리드 선택지는 자주쓰는 + 내 부서만(사용자 확정 — 전사 전체는 과다·캡 잘림으로 무의미).
        # 전량 덤프(all_units)는 내 부서 매칭·AI 추천 후보용으로만 쓴다.
        budget_units = {
            "favorites": budget_favs[:_shared._MAX_FAVORITES],
            "mine": mine_units[:_shared._MAX_BUDGET_UNITS],
        }
        project_favs = project_favs[:_shared._MAX_FAVORITES]

        # AI 추천 + 기본지정 폴백으로 행별 예산단위·프로젝트를 프리셀렉트한다(사용자는 수정 가능).
        # 기본지정 부재는 폴백이 조용히 비는 원인이므로 명시적으로 알려 진단을 돕는다.
        missing_defaults = [
            label
            for label, favs in (("예산단위", budget_favs), ("프로젝트", project_favs))
            if favs and not any(f.get("isDefault") for f in favs)
        ]
        if missing_defaults:
            await emit_log(
                events,
                f"{'/'.join(missing_defaults)} 기본지정이 없어 AI 추천 실패 시 빈 선택으로 둡니다"
                " (관리 페이지에서 '기본'을 지정하세요).",
                "info",
            )
        # 팀 비용구분 기본 프로젝트(제조원가→500/판관비→800) — 기본지정 즐겨찾기가 없을 때 폴백.
        cost_project = None
        try:
            cost_project = await catalog._load_cost_project(cost_type)
        except Exception:  # noqa: BLE001 — 기본값 조회 실패로 런을 죽이지 않는다.
            logger.exception("card-collect cost project load failed")
        if cost_project and not any(f.get("isDefault") for f in project_favs):
            await emit_log(
                events,
                f"팀 비용구분 '{cost_type}' → 기본 프로젝트 {cost_project['name']}({cost_project['wbsNo']}) 프리셀렉트.",
                "info",
            )
        # 개입 학습 조회: 이번 런 가맹점들에 대해서만 과거 확정분을 로드(전 이력 무관, 프롬프트
        # 크기는 행 수에 비례). 결정적 프리필(반복 가맹점) + AI 힌트로 쓴다.
        merchants = [r.get("TRAN_NM") or "" for r in rows_list]
        learned = await card_learning.retrieve_for_merchants(state.get("owner"), merchants)
        # 전사 기초자료(seed) 폴백 — 개인 학습이 없는 가맹점에 대해 과거 전사 관례를 힌트로.
        seed = await card_learning.retrieve_seed_for_merchants(merchants)
        if learned:
            await emit_log(events, f"과거 개입 학습 {len(learned)}개 가맹점 매칭 — 추천에 반영.", "info")
        if seed:
            await emit_log(events, f"전사 기초자료 {len(seed)}개 가맹점 매칭 — 개인 학습 없는 행에 반영.", "info")
        # 적요 반영: 개인 학습 적요 > 전사 seed 적요 > 키워드 휴리스틱(사용자의 실제 표현 우선).
        # recs(그리드 표시) · notes(반영/현황) 둘 다 갱신. 행별 출처(note_sources)를 함께 기록해
        # 프론트 배지(학습/전사)로 노출한다 — 키워드 휴리스틱은 None(배지 없음).
        note_sources: dict[int, str | None] = {
            r.get("i", idx): None for idx, r in enumerate(rows_list)
        }
        for idx, r in enumerate(rows_list):
            norm = card_learning.norm_merchant(r.get("TRAN_NM"))
            learned_note = (learned.get(norm) or {}).get("note")
            seed_note = (seed.get(norm) or {}).get("note")
            note_hint = learned_note or seed_note
            if note_hint and note_hint.strip():
                key = r.get("i", idx)
                recs[key] = note_hint.strip()
                notes[key] = note_hint.strip()
                note_sources[key] = "learned" if (learned_note or "").strip() else "seed"
        preselect = await prefill._prefill_selections(
            events, settings, rows_list, recs, budget_favs, mine_units, project_favs,
            cost_prefix=cost_prefix, cost_project=cost_project, learned=learned, seed=seed,
        )
        # 계정 인지 적요 재추천: 프리셀렉트된 예산계정(bgacctCd)으로 suggest_note 사다리를 태워
        # 초기 적요도 계정 인지되게 만든다(엔드포인트 /me/note-suggest 와 같은 리졸버 — 배치
        # 최초 추천·실시간 재추천 일관). 계정 없는 행은 위 가맹점-키 경로를 그대로 유지(회귀 방어).
        # noteSource 배지는 리졸버 source(learned/seed/category/heuristic)를 그대로 반영한다.
        acct_by_key: dict[int, tuple[str, str, str]] = {}
        for idx, r in enumerate(rows_list):
            bu = (preselect.get(idx + 1) or {}).get("budgetUnit") or {}
            acct_code = (bu.get("bgacctCd") or "").strip()
            if acct_code:
                acct_by_key[r.get("i", idx)] = (
                    r.get("TRAN_NM") or "",
                    acct_code,
                    (bu.get("bgacctNm") or "").strip(),
                )
        if acct_by_key:  # 계정이 하나라도 있을 때만 세션을 연다(계정 없는 런은 DB 접근 없음).
            try:
                async with get_sessionmaker()() as s:
                    for idx, r in enumerate(rows_list):
                        key = r.get("i", idx)
                        if key not in acct_by_key:
                            continue
                        merchant, acct_code, acct_nm = acct_by_key[key]
                        # ai_on_ambiguous_seed — 그 가맹점×계정의 seed 적요가 여러 갈래일 때만
                        # (dominance 미달) AI 로 계정 맞춤 적요를 만든다. 미학습 조합은 배치에서
                        # 생성하지 않고 결정적 tier 를 그대로 탄다(카드 런당 LLM 호출 억제).
                        res = await card_learning.suggest_note(
                            s,
                            user_id=state.get("owner"),
                            merchant=merchant,
                            acct_code=acct_code,
                            acct_name=acct_nm,
                            ai_on_ambiguous_seed=True,
                        )
                        note = (res.get("note") or "").strip()
                        if note:
                            recs[key] = note
                            notes[key] = note
                            note_sources[key] = res.get("source")
            except Exception:  # noqa: BLE001 — 적요 재추천 실패가 런을 죽여선 안 된다(부가기능).
                logger.exception("card-collect account-aware note suggest failed")
        # AI 추천 준비 끝 → 그리드(사람 개입) 구간 시작. 분리 측정해야 ETA 가 정직해진다
        # (prefill=자동·예측 대상, collect_rows=사람 시간·예측 제외).
        await emit_step(events, "prefill", "done", _shared._ms(t0))
        await emit_step(events, "collect_rows", "running")
        t_grid = time.monotonic()

        # 그리드 행(프론트 계약: no·card·merchant·amount·date·time·approved·vatType·note
        #  + 프리셀렉트 budgetUnit/project·출처 budgetSource/projectSource/noteSource).
        grid_rows = [
            {
                "no": idx + 1,
                "card": r.get("FINPRODUCT_NM") or "",
                "merchant": r.get("TRAN_NM") or "",
                "amount": _shared._fmt_won(r.get("TRAN_AMT")),
                "date": r.get("TRAN_DT") or "",
                "time": r.get("TRAN_TM") or "",
                "approved": r.get("APRVL_YN") or "",
                "vatType": r.get("VAT_TP") or "",
                # 부가세구분(과세/불공) 자동 분류 — 예산계정 불공목록·AI 가맹점 판정·VAT_TP 순.
                # 사용자가 그리드에서 덮어쓸 수 있고, 저장 파티션은 그 최종값을 쓴다.
                "vat": vat_rules.classify_vat(
                    r.get("VAT_TP"),
                    (preselect[idx + 1].get("budgetUnit") or {}).get("bgacctNm"),
                    preselect[idx + 1].get("vatDeduction"),
                ),
                "note": recs[r.get("i", idx)],
                "noteSource": note_sources[r.get("i", idx)],
                **preselect[idx + 1],
            }
            for idx, r in enumerate(rows_list)
        ]

        # 저장 실패 재시도(방식 1): 이전 제출 선택을 행 identity(_row_key)로 복원해 사용자가
        # 처음부터 다시 고르지 않게 한다(틀린 행만 고치면 됨). 복원값은 사용자 값이므로 배지 없음.
        retry_prefill = state.get("retry_prefill") or {}
        if retry_prefill:
            restored = 0
            for gr, r in zip(grid_rows, rows_list):
                prev = retry_prefill.get(_shared._row_key(r))
                if not prev:
                    continue
                if prev.get("budgetUnit"):
                    gr["budgetUnit"], gr["budgetSource"] = prev["budgetUnit"], None
                if prev.get("project"):
                    gr["project"], gr["projectSource"] = prev["project"], None
                if prev.get("note"):
                    gr["note"], gr["noteSource"] = prev["note"], None
                restored += 1
            if restored:
                await emit_log(events, f"이전 선택 {restored}건 복원(저장 실패 재시도) — 틀린 행만 고쳐 주세요.", "info")

        # 저장 거부 조치 안내: 해당 행에 '어떤 계정으로 고쳐야 하는지' 오류 메시지를 붙인다.
        issues = state.get("save_error_issues") or []
        by_row = {it["rowNo"]: it for it in issues if it.get("rowNo")}
        for gr in grid_rows:
            it = by_row.get(gr["no"])
            if not it:
                continue
            if it.get("requiredAccount"):
                gr["error"] = (
                    f"저장 거부 — 예산계정이 ‘{it['requiredAccount']}’와 같아야 합니다. "
                    "예산단위를 그 계정에 맞는 것으로 다시 선택하세요."
                )
                gr["budgetSource"] = None  # 재선택 유도 — 자동배지 제거
            else:
                gr["error"] = "저장 거부 — 예산단위를 다시 선택하세요."

        # 재개입(직전 저장 실패) 사유 배너 — 계정 불일치는 위 행별 오류로도 뜨지만, 필수값 미입력·
        # 일반 ERP 오류 등은 행별로 안 잡히므로 **왜 1회차가 실패했고 무엇을 고칠지**를 그리드 상단
        # notice 로 항상 알려준다(사용자 피드백: 재개입만 하고 이유를 안 알려줌). 첫 진입엔 None.
        save_error = state.get("save_error_msg")
        retry_no = state.get("save_retries") or 0
        retry_notice = _save_guidance(issues, save_error) if save_error else None
        if retry_notice and retry_no:
            retry_notice = f"[저장 재시도 {retry_no}/{MAX_SAVE_RETRIES}] {retry_notice}"

        # 지속 HITL 채널: decision_id 1개로 노드 수명 내내 큐를 유지한다(query 재검색·재제출을
        # 같은 채널로 받는다). 소유권·런바인딩은 오픈 시점에 등록해 /runs/hitl 레이스 창을 없앤다.
        decision_id = uuid.uuid4().hex
        q = open_hitl_channel(decision_id, owner=state.get("owner"), run_id=state.get("run_id"))

        async def _emit_frame(search_results: list | None, query: str | None) -> None:
            # 프론트는 run.hitl 을 통째로 교체하므로, 재방출 시 rows/budgetUnits/favorites 를 매번 싣는다.
            await emit_hitl(
                events,
                decision_id=decision_id,
                kind="grid",
                title="승인내역 정리",
                prompt=(
                    "행별로 예산단위·프로젝트·적요를 입력한 뒤 '입력 완료'를 누르세요. "
                    "과세 행은 법인카드(01), 나머지는 법인카드(불공)(02)으로 자동 전환해 "
                    "반영하고, 마지막에 저장(F7)까지 자동 진행합니다."
                ),
                rows=grid_rows,
                budgetUnits=budget_units,
                projects={"favorites": project_favs, "searchResults": search_results, "query": query},
                notice=retry_notice,
            )

        last_results: list | None = None  # 마지막 프로젝트 검색 결과(무효 제출 시 프레임 유지용).
        last_query: str | None = None
        submitted: list[dict] | None = None
        await _emit_frame(None, None)
        try:
            while True:
                try:
                    resp = await asyncio.wait_for(q.get(), timeout=wait_timeout)
                except asyncio.TimeoutError:
                    await emit_step(events, "collect_rows", "failed")
                    return {"error": f"입력 대기 시간 초과({wait_timeout // 60}분). 저장 전 반영 0건."}

                query = resp.get("query")
                if isinstance(query, str) and query.strip():
                    kw = query.strip()[:50]
                    try:
                        found = await steps.dump_projects(page, kw)
                    except Exception:  # noqa: BLE001 — 검색 실패로 런을 죽이지 않는다.
                        logger.exception("card-collect dump_projects failed")
                        found = []
                    last_results = [
                        {
                            "code": p.get("code"),
                            "name": p.get("name"),
                            "wbsNo": p.get("wbsNo", ""),
                            "wbsNm": p.get("wbsNm", ""),
                        }
                        for p in found
                    ][:_shared._MAX_PROJECT_RESULTS]
                    last_query = kw
                    await _emit_frame(last_results, last_query)
                    continue

                rows_in = resp.get("rows")
                if isinstance(rows_in, list):
                    ok, reason = _validate_grid_submit(rows_in, n)
                    if not ok:
                        await emit_log(events, f"입력값을 확인해 주세요: {reason}", "warn")
                        await _emit_frame(last_results, last_query)  # 프레임 유지 — 재제출 유도.
                        continue
                    submitted = rows_in
                    break

                # done/기타 — 그리드에선 사용하지 않는다(무시하고 계속 대기).
                logger.debug("card-collect grid: 무시된 메시지 %r", resp)
                continue

            # 제출 수락 = 사람 몫 끝. 개입 스텝(collect_rows)을 여기서 닫고, 이후 그리드 행
            # 실입력(~수십 초 기계 작업)은 'fill_rows' 스텝으로 분리 방출한다 — 제출 후에도
            # "건별 입력에 머묾 + 남은 예상 정지"로 보이던 문제 수정(사용자 피드백 2026-07-06).
            await emit_step(events, "collect_rows", "done", _shared._ms(t_grid))
            await emit_step(events, "fill_rows", "running")
            t_fill = time.monotonic()

            # ── 부가세구분 분할: 과세 → 1차(법인카드) 즉시 반영, 그 외 → 2차(불공) 대기 ──
            # 사용자 입력은 이 그리드 1회가 전부 — 2차는 여기 보존한 입력을 재조회 행에
            # (APRVL_NO+일자+금액) 키로 매칭해 자동 적용한다(재입력 없음).
            apply_rows = sorted((r for r in submitted if not r.get("skip")), key=lambda r: r["no"])
            skipped = 0
            for r in submitted:
                if r.get("skip"):
                    status[r["no"] - 1] = "skipped"
                    skipped += 1

            taxable_work: list[dict] = []
            pending_nontax: list[dict] = []
            for row in apply_rows:
                idx = row["no"] - 1
                src = rows_list[idx]
                entry = {
                    "idx": idx,
                    "label": row["no"],
                    "budgetUnit": row.get("budgetUnit") or {},
                    "project": row.get("project") or None,
                    "note": (row.get("note") or "").strip(),
                    # 개입 학습: 사용자가 프리필에서 실제로 바꾼 필드만 학습(프론트가 표시).
                    "budgetEdited": bool(row.get("budgetEdited")),
                    "projectEdited": bool(row.get("projectEdited")),
                    "noteEdited": bool(row.get("noteEdited")),
                }
                # 부가세구분 파티션 — 사용자 최종 제출값(vat) 우선, 없으면(구클라) 계정+VAT_TP 자동분류.
                row_vat = (row.get("vat") or "").strip() or vat_rules.classify_vat(
                    src.get("VAT_TP"), (row.get("budgetUnit") or {}).get("bgacctNm")
                )
                if row_vat == vat_rules.TAXABLE:
                    taxable_work.append(entry)
                else:
                    pending_nontax.append(
                        {**entry, "key": _shared._row_key(src), "merchant": src.get("TRAN_NM") or ""}
                    )
                    status[idx] = "wait2"
                    notes[idx] = entry["note"]

            # 행 분류 전문 로깅 — 승인취소(음수) 행이 어느 패스로 갔는지 사후 진단용.
            def _row_desc(e: dict, tag: str) -> str:
                src2 = rows_list[e["idx"]]
                return (
                    f"{e['label']}행 {(src2.get('TRAN_NM') or '?')[:10]} {src2.get('TRAN_AMT', '?')}"
                    f"(승인 {src2.get('APRVL_NO', '?')}·'{src2.get('VAT_TP', '')}'→{tag})"
                )

            split_desc = ", ".join(
                [_row_desc(e, "과세") for e in taxable_work]
                + [_row_desc(e, "불공") for e in pending_nontax]
            )
            await emit_log(events, f"부가세구분 분류: {split_desc}", "info")

            # 개입 학습(필드 단위): 사용자가 프리필에서 **실제로 바꾼 필드만** 가맹점 단위로 누적한다
            # (사용자 확정 2026-07-05: 프리필 그대로 수락은 학습 안 함 — 자기추천 되먹임 방지).
            # 안 바꾼 필드는 None 으로 둬 record 가 기존 스냅샷을 덮지 않게 한다. owner 없으면 no-op.
            learn_entries = []
            for e in [*taxable_work, *pending_nontax]:
                budget = (
                    e["budgetUnit"]
                    if e["budgetEdited"] and (e["budgetUnit"] or {}).get("code")
                    else None
                )
                project = e["project"] if e["projectEdited"] else None
                note = e["note"] if (e["noteEdited"] and e["note"]) else None
                if budget or project or note:  # 바꾼 게 하나라도 있을 때만 학습.
                    learn_entries.append(
                        {
                            "merchant": rows_list[e["idx"]].get("TRAN_NM") or "",
                            "budget": budget,
                            "project": project,
                            "note": note,
                        }
                    )
            _owner = state.get("owner")
            learned_n = await card_learning.record_selections(_owner, learn_entries)
            # (가맹점 × 계정) → 적요 학습: 사람이 적요를 바꾼 행을, **그 행에 확정된 계정
            # (budgetUnit.bgacctCd/bgacctNm)** 단위로 누적한다(record_selections 와 병행). 다음 런에서
            # 같은 가맹점의 같은 계정이 나오면 그 계정 전용 적요를 결정적으로 추천하기 위한 데이터.
            # 계정코드 없으면 record_account_notes 가 skip(방어).
            note_entries = []
            for e in [*taxable_work, *pending_nontax]:
                if not (e["noteEdited"] and e["note"]):
                    continue
                bu = e.get("budgetUnit") or {}
                acct_code = (bu.get("bgacctCd") or "").strip()
                if not acct_code:
                    continue
                note_entries.append(
                    {
                        "merchant": rows_list[e["idx"]].get("TRAN_NM") or "",
                        "acct_code": acct_code,
                        "acct_name": (bu.get("bgacctNm") or "").strip() or None,
                        "note": e["note"],
                    }
                )
            account_notes_n = await card_learning.record_account_notes(_owner, note_entries)
            # 항상 로깅(진단): owner 유무·편집 플래그 도착 여부·후보·저장. 0건이면 원인을 바로 좁힌다.
            # 편집표시 0인데 사용자가 바꿨다면 → 프론트 번들 stale(budgetEdited 미전송) 신호.
            _all = [*taxable_work, *pending_nontax]
            _eb = sum(1 for e in _all if e.get("budgetEdited"))
            _en = sum(1 for e in _all if e.get("noteEdited"))
            _ep = sum(1 for e in _all if e.get("projectEdited"))
            await emit_log(
                events,
                f"개입 학습: owner={'있음' if _owner else '없음'} · 편집표시(예산 {_eb}·적요 {_en}·프로젝트 {_ep})"
                f" · 후보 {len(learn_entries)}건 · 저장 {learned_n}건 · 계정적요 {account_notes_n}건.",
                "info" if learned_n or account_notes_n else "warn",
            )

            filled, failures, applied_idx = await batch._apply_batch(
                page, events, rows_list, taxable_work, status, notes, chat_id="cc-status"
            )
        finally:
            close_hitl_channel(decision_id)

        # ── 요약(1차) ─────────────────────────────────────────────────────
        summary = (
            f"1차(법인카드·과세) 반영 {filled}건 · 2차(불공) 대기 {len(pending_nontax)}건 · "
            f"건너뜀 {skipped}건 · 실패 {len(failures)}건"
        )
        if failures:
            summary += "\n\n실패 상세:\n- " + "\n- ".join(failures)
        await emit_chat(
            events,
            chat_id="cc-summary",
            role="assistant",
            content=summary + "\n\n" + _shared._status_table(rows_list, status, notes),
            streaming=False,
        )
        await emit_log(events, f"1차(과세) 처리 완료 — {filled}건 반영(저장 전).", "ok")
        await emit_step(events, "fill_rows", "done", _shared._ms(t_fill))
        # 저장 실패 시 재시도 그리드에서 복원할 수 있게 이번 제출 선택을 행 identity 로 보존.
        # 제외(skip) 행은 복원 대상 아님(재시도 시 사용자가 다시 정함) → 실입력 행만.
        retry_prefill = {
            _shared._row_key(rows_list[row["no"] - 1]): {
                "budgetUnit": row.get("budgetUnit"),
                "project": row.get("project"),
                "note": row.get("note"),
            }
            for row in submitted
            if not row.get("skip")
        }
        out = {
            "filled": filled,
            "pending_nontax": pending_nontax,
            "pass1_applied_idx": applied_idx,
            "pass1_failed": len(failures),
        }
        if retry_prefill:  # 보존할 실입력이 있을 때만(없으면 상태 오염 없이 원래 반환).
            out["retry_prefill"] = retry_prefill
        return out

    return collect_rows
