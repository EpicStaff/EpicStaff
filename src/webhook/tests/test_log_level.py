import pytest
from run import uvicorn_log_level
from uvicorn.config import LOG_LEVELS as UVICORN_LOG_LEVELS

from src.shared.envtools import Env


@pytest.mark.parametrize("level", Env.LOG_LEVELS)
def test_every_accepted_log_level_maps_to_a_uvicorn_level(level):
    assert uvicorn_log_level(level) in UVICORN_LOG_LEVELS


def test_success_maps_to_uvicorn_info():
    assert uvicorn_log_level("SUCCESS") == "info"
