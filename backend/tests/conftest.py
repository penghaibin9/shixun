"""测试环境必须显式打开开发身份适配器，生产默认保持关闭。"""

import pytest


@pytest.fixture(autouse=True)
def explicit_test_identity_environment(monkeypatch):
    monkeypatch.setenv("YUEKE_ENV", "test")
    monkeypatch.setenv("YUEKE_ALLOW_DEV_IDENTITY_HEADERS", "1")
