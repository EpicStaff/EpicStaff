import pytest
from loguru import logger

from src.shared.envtools import Env, EnvironmentNotFoundError

VARIABLE = "EPICSTAFF_PROBE_LOG_LEVEL"


@pytest.mark.parametrize("raw_value", ["debug", "Debug", " DEBUG "])
def test_normalises_case_and_whitespace(monkeypatch, raw_value):
    monkeypatch.setenv(VARIABLE, raw_value)

    assert Env().log_level(VARIABLE, "INFO") == "DEBUG"


def test_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)

    assert Env().log_level(VARIABLE, "INFO") == "INFO"


def test_raises_when_unset_without_default(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)

    with pytest.raises(EnvironmentNotFoundError, match=VARIABLE):
        Env().log_level(VARIABLE)


@pytest.mark.parametrize("raw_value", ["verbose", "", "NOTSET", "10", "none", "NONE"])
def test_rejects_unknown_level_naming_the_variable(monkeypatch, raw_value):
    monkeypatch.setenv(VARIABLE, raw_value)

    with pytest.raises(ValueError, match=f"{VARIABLE} must be one of TRACE, DEBUG, INFO, SUCCESS, WARNING"):
        Env().log_level(VARIABLE, "INFO")


@pytest.mark.parametrize("level", Env.LOG_LEVELS)
def test_every_accepted_level_is_a_loguru_level(level):
    assert logger.level(level).name == level


def test_accepts_loguru_success_level(monkeypatch):
    monkeypatch.setenv(VARIABLE, "success")

    assert Env().log_level(VARIABLE) == "SUCCESS"


def test_bench_is_rejected_unless_the_service_allows_it(monkeypatch):
    monkeypatch.setenv(VARIABLE, "bench")

    with pytest.raises(ValueError, match=f"{VARIABLE} must be one of TRACE, DEBUG, INFO, SUCCESS"):
        Env().log_level(VARIABLE, "INFO")
    assert Env().log_level(VARIABLE, "INFO", allowed=Env.LOG_LEVELS_WITH_BENCH) == "BENCH"


@pytest.mark.parametrize("level", Env.LOG_LEVELS_WITH_BENCH)
def test_every_bench_service_level_is_a_loguru_level(level):
    import src.shared.bench_log  # noqa: F401 -- registers BENCH

    assert logger.level(level).name == level
