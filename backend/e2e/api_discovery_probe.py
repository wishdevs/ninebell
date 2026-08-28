"""ERP API 실측 캡처 프로브 — 옴니솔을 순수 HTTP 로 다룰 수 있는지 판정하기 위한
읽기전용 네트워크 캡처.

카드결의 진입 체인(login→user_type→menu_nav→set_gubun→add_row→open_evdn→select_evdn)을
태우며 전 구간 request/response 를 기록하고, 각 스텝 직후 localStorage/sessionStorage/
Cookie 스냅샷을 떠 JWT 저장 위치·TTL 을 특정한다. 이후 카드 일괄적용 폼의 예산단위(bg_cd)
/프로젝트(pjt_cd)/거래처(partner_cd) 코드피커를 각각 열어 빈검색 1회(pjt_cd 는 +1라운드
ArrowDown 페이징)를 수행해 XHR 을 유발한다.

⚠ 읽기 전용 — F7/저장/상신/보관 절대 금지. 로그인·메뉴 진입·코드피커 열기·검색만 수행한다.
⚠ 캡처 파일(out/api_discovery_capture.json)에는 로그인 요청 전문·토큰이 평문으로 남을 수
  있다 — .gitignore 대상(e2e/out/)이며 이트라이브2(e2e 프로브 전용 계정)로만 실행한다.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/api_discovery_probe.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Response, async_playwright  # noqa: E402

from app.agents.card_collect.steps import dump_budget_units, dump_projects_scroll  # noqa: E402
from app.agents.common.nodes import (  # noqa: E402
    make_add_row_node,
    make_login_node,
    make_menu_nav_node,
    make_open_evdn_node,
    make_select_evdn_node,
    make_set_gubun_node,
    make_user_type_node,
)
from app.agents.trip_domestic.steps import dump_partners  # noqa: E402
from app.config import get_settings  # noqa: E402

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(errors="ignore").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

USERID = os.environ.get("E2E_USERID") or ""
PASSWORD = os.environ.get("E2E_PASSWORD") or ""
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(exist_ok=True)
CAPTURE_PATH = OUT_DIR / "api_discovery_capture.json"

# 캡처 대상 리소스 타입 — 정적 자산(script/stylesheet/image/font)은 API 판정에 무관해 제외.
RESOURCE_TYPES = {"document", "xhr", "fetch"}
BODY_CAP_BYTES = 1_000_000  # 이 초과면 앞 200KB 만 보존 + 총길이 기록.
BODY_HEAD_BYTES = 200_000


class Capture:
    """스텝(phase) 태그가 붙은 request/response 캡처 버퍼."""

    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.failed: list[dict] = []
        self.phase = "init"
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


async def _on_response(resp: Response, cap: Capture) -> None:
    req = resp.request
    if req.resource_type not in RESOURCE_TYPES:
        return
    entry: dict[str, Any] = {
        "seq": cap.next_seq(),
        "phase": cap.phase,
        "ts": time.time(),
        "url": req.url,
        "method": req.method,
        "resourceType": req.resource_type,
        "status": resp.status,
    }
    try:
        entry["requestHeaders"] = await req.all_headers()
    except Exception as exc:  # noqa: BLE001 — 캡처 실패가 프로브를 죽이지 않는다.
        entry["requestHeadersError"] = str(exc)
    try:
        entry["postData"] = req.post_data
    except Exception:  # noqa: BLE001
        entry["postData"] = None
    try:
        entry["responseHeaders"] = await resp.all_headers()
    except Exception as exc:  # noqa: BLE001
        entry["responseHeadersError"] = str(exc)
    try:
        buf = await resp.body()
        raw_len = len(buf)
        entry["bodyLen"] = raw_len
        if raw_len > BODY_CAP_BYTES:
            entry["body"] = buf[:BODY_HEAD_BYTES].decode("utf-8", errors="replace")
            entry["bodyTruncated"] = True
        else:
            entry["body"] = buf.decode("utf-8", errors="replace")
            entry["bodyTruncated"] = False
    except Exception as exc:  # noqa: BLE001 — 리다이렉트 등 body 획득 불가는 흔함.
        entry["bodyError"] = str(exc)
    cap.entries.append(entry)


def _on_request_failed(req, cap: Capture) -> None:
    if req.resource_type not in RESOURCE_TYPES:
        return
    cap.failed.append(
        {
            "phase": cap.phase,
            "ts": time.time(),
            "url": req.url,
            "method": req.method,
            "failure": getattr(req, "failure", None),
        }
    )


async def dump_storage(page: Any, label: str) -> dict:
    """localStorage/sessionStorage 전체 키값 + 쿠키 목록 스냅샷."""
    data = await page.evaluate(
        "() => ({local: Object.fromEntries(Object.entries(localStorage)), "
        "session: Object.fromEntries(Object.entries(sessionStorage))})"
    )
    cookies = await page.context.cookies()
    return {
        "label": label,
        "ts": time.time(),
        "localStorage": data.get("local"),
        "sessionStorage": data.get("session"),
        "cookies": cookies,
    }


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _decode_jwt(token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        header = json.loads(_b64url_decode(parts[0]))
        payload = json.loads(_b64url_decode(parts[1]))
    except Exception:  # noqa: BLE001 — JWT 형태가 아닌 점(.) 포함 문자열.
        return None
    return {"header": header, "payload": payload}


def find_jwts(snap: dict) -> list[dict]:
    """스냅샷(localStorage/sessionStorage/cookies) 전체에서 JWT 형태 값을 찾아 디코드."""
    found: list[dict] = []

    def scan(d: dict | None, source: str) -> None:
        for k, v in (d or {}).items():
            if isinstance(v, str) and v.count(".") == 2 and len(v) > 20:
                decoded = _decode_jwt(v)
                if decoded:
                    found.append({"source": source, "key": k, "decoded": decoded})

    scan(snap.get("localStorage"), "localStorage")
    scan(snap.get("sessionStorage"), "sessionStorage")
    for c in snap.get("cookies") or []:
        v = c.get("value") or ""
        if v.count(".") == 2 and len(v) > 20:
            decoded = _decode_jwt(v)
            if decoded:
                found.append({"source": f"cookie:{c.get('name')}", "key": c.get("name"), "decoded": decoded})
    return found


async def main() -> int:
    if not (USERID and PASSWORD):
        print("E2E_USERID / E2E_PASSWORD 를 .env 에 채우고 실행하세요.", file=sys.stderr)
        return 2

    base = get_settings().erp_base
    cap = Capture()
    storage_snapshots: list[dict] = []
    budget_rows: list[dict] = []
    project_rows: list[dict] = []
    project_total: int | None = None
    project_raw = 0
    partner_rows: list[dict] = []
    step_errors: dict[str, str] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        page.on("response", lambda r: asyncio.ensure_future(_on_response(r, cap)))
        page.on("requestfailed", lambda r: _on_request_failed(r, cap))

        events: asyncio.Queue = asyncio.Queue()

        async def _drain() -> None:
            while True:
                await events.get()

        drainer = asyncio.create_task(_drain())
        state: dict[str, Any] = {
            "page": page,
            "events": events,
            "userid": USERID,
            "password": PASSWORD,
            "params": {},
        }

        entry_steps = [
            ("login", make_login_node()),
            ("user_type", make_user_type_node("회계")),
            ("menu_nav", make_menu_nav_node()),
            ("set_gubun", make_set_gubun_node("카드")),
            ("add_row", make_add_row_node()),
            ("open_evdn", make_open_evdn_node()),
            ("select_evdn", make_select_evdn_node("01")),
        ]
        try:
            for name, node in entry_steps:
                cap.phase = name
                t0 = time.monotonic()
                out = await node(state)
                state.update(out or {})
                dt = int((time.monotonic() - t0) * 1000)
                err = state.get("error")
                print(f"[{name}] {dt}ms error={err}", flush=True)
                try:
                    storage_snapshots.append(await dump_storage(state["page"], f"post_{name}"))
                except Exception as exc:  # noqa: BLE001 — 스냅샷 실패는 진입 자체를 막지 않는다.
                    print(f"  스냅샷 실패({name}): {exc}", file=sys.stderr)
                try:
                    await state["page"].screenshot(path=str(ARTIFACTS / f"api_discovery_{name}.png"))
                except Exception:  # noqa: BLE001
                    pass
                if err:
                    step_errors[name] = err
                    raise RuntimeError(f"진입 실패({name}): {err}")

            page2 = state["page"]

            cap.phase = "budget_picker"
            try:
                budget_rows = await dump_budget_units(page2)
            except Exception as exc:  # noqa: BLE001
                step_errors["budget_picker"] = str(exc)
            print(f"[budget_picker] rows={len(budget_rows)}", flush=True)
            try:
                await page2.screenshot(path=str(ARTIFACTS / "api_discovery_budget_picker.png"))
            except Exception:  # noqa: BLE001
                pass

            cap.phase = "project_picker"
            try:
                project_rows, project_total, project_raw = await dump_projects_scroll(page2, max_rounds=1)
            except Exception as exc:  # noqa: BLE001
                step_errors["project_picker"] = str(exc)
            print(
                f"[project_picker] rows={len(project_rows)} total={project_total} raw={project_raw}",
                flush=True,
            )
            try:
                await page2.screenshot(path=str(ARTIFACTS / "api_discovery_project_picker.png"))
            except Exception:  # noqa: BLE001
                pass

            cap.phase = "partner_picker"
            try:
                partner_rows = await dump_partners(page2, max_rounds=0)
            except Exception as exc:  # noqa: BLE001
                step_errors["partner_picker"] = str(exc)
            print(f"[partner_picker] rows={len(partner_rows)}", flush=True)
            try:
                await page2.screenshot(path=str(ARTIFACTS / "api_discovery_partner_picker.png"))
            except Exception:  # noqa: BLE001
                pass

            cap.phase = "final"
            try:
                storage_snapshots.append(await dump_storage(page2, "post_pickers"))
            except Exception as exc:  # noqa: BLE001
                print(f"  최종 스냅샷 실패: {exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 — 실패해도 지금까지의 캡처는 반드시 저장한다.
            print(f"프로브 중단: {exc}", file=sys.stderr)
            step_errors.setdefault("_fatal", str(exc))
        finally:
            drainer.cancel()
            await ctx.close()
            await browser.close()

    jwt_findings: list[dict] = []
    for snap in storage_snapshots:
        for j in find_jwts(snap):
            jwt_findings.append({"snapshotLabel": snap["label"], **j})

    result = {
        "meta": {
            "base": base,
            "userid": USERID,
            "generatedAt": time.time(),
            "stepErrors": step_errors,
            "networkEntryCount": len(cap.entries),
            "failedRequestCount": len(cap.failed),
        },
        "storageSnapshots": storage_snapshots,
        "jwtFindings": jwt_findings,
        "sampleRows": {
            "budget": budget_rows[:5],
            "project": project_rows[:5],
            "partner": partner_rows[:5],
        },
        "rowCounts": {
            "budget": len(budget_rows),
            "project": len(project_rows),
            "projectServerTotal": project_total,
            "projectRawLoaded": project_raw,
            "partner": len(partner_rows),
        },
        "failedRequests": cap.failed,
        "network": cap.entries,
    }
    CAPTURE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(f"\n캡처 저장: {CAPTURE_PATH} (entries={len(cap.entries)}, failed={len(cap.failed)})")
    print(f"JWT 후보: {len(jwt_findings)}건")
    for j in jwt_findings:
        exp = j["decoded"]["payload"].get("exp")
        print(f"  - {j['snapshotLabel']} / {j['source']} / key={j['key']} / exp={exp}")
    return 1 if step_errors.get("_fatal") else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
