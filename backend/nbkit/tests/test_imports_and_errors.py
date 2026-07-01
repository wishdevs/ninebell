"""임포트 표면 + 예외 계층 — 라이브 브라우저 없이 전 모듈이 import 되는지."""

from __future__ import annotations

import importlib

import pytest

_MODULES = [
    "nbkit",
    "nbkit.browser.actions",
    "nbkit.browser.waits",
    "nbkit.browser.frames",
    "nbkit.browser.detection",
    "nbkit.browser.debug",
    "nbkit.grid.provider",
    "nbkit.grid.strategies",
    "nbkit.grid.validation",
    "nbkit.omnisol.auth",
    "nbkit.omnisol.navigator",
    "nbkit.omnisol.selectors",
    "nbkit.omnisol.js_lib",
    "nbkit.omnisol.menu_schemas",
    "nbkit.omnisol.profile",
    "nbkit.omnisol.errors",
    "nbkit.patterns.login_flow",
    "nbkit.patterns.menu_navigate_flow",
    "nbkit.patterns.grid_read_flow",
    "nbkit.patterns.user_type_flow",
]


@pytest.mark.parametrize("mod", _MODULES)
def test_module_imports(mod):
    assert importlib.import_module(mod) is not None


def test_public_api_surface():
    import nbkit

    for name in (
        "omnisol_login",
        "switch_user_type",
        "navigate_menu",
        "read_profile",
        "GridProvider",
        "GridExtractor",
        "CollectionStrategy",
        "ensure_logged_in",
        "ensure_user_type",
        "read_grid_with_fallback",
    ):
        assert hasattr(nbkit, name), f"nbkit.{name} 공개 API 누락"


def test_error_hierarchy():
    from nbkit.omnisol.errors import (
        AuthError,
        ErpAuthError,
        GridError,
        MenuError,
        OmnisolError,
        PopupError,
        UserTypeError,
    )

    for exc in (AuthError, GridError, MenuError, UserTypeError, PopupError):
        assert issubclass(exc, OmnisolError)
    assert ErpAuthError is AuthError  # 친숙성 별칭
