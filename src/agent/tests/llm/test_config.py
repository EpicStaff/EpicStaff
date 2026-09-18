from __future__ import annotations

import litellm
import pytest

from app.llm.config import configure_litellm


@pytest.fixture(autouse=True)
def _restore_drop_params():
    original = litellm.drop_params
    yield
    litellm.drop_params = original


def test_configure_litellm_enables_drop_params():
    configure_litellm(True)
    assert litellm.drop_params is True


def test_configure_litellm_disables_drop_params():
    configure_litellm(False)
    assert litellm.drop_params is False
