"""Tests for the opt-in daily refresh of litellm's model map from GitHub.

The refresh trusts unpinned upstream data, so with LITELLM_MODEL_COST_REFRESH_ENABLED
off the web server must schedule nothing, make no request and ignore any snapshot a
previous run left on disk. The scheduler is replaced by a fake that records jobs: a
real BackgroundScheduler would start a thread that outlives the test.
"""

import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import litellm
import pytest
import yaml
from django.conf import settings as django_settings

from tables.utils import litellm_model_info
from tables.utils.litellm_model_info import (
    FALLBACK_CONTEXT_WINDOW,
    refresh_litellm_model_cost,
    resolve_context_window,
    start_litellm_refresh_if_owner,
)

SNAPSHOT_ONLY_MODEL = "epicstaff-snapshot-only-model"
SNAPSHOT_CONTEXT_WINDOW = 123_456


class FakeScheduler:
    instances: list["FakeScheduler"] = []

    def __init__(self, **options):
        self.jobs: list[dict] = []
        self.started = False
        FakeScheduler.instances.append(self)

    def add_job(self, func, **options):
        self.jobs.append({"func": func, **options})

    def start(self):
        self.started = True


@pytest.fixture
def snapshot_path(monkeypatch, tmp_path_factory):
    path = tmp_path_factory.mktemp("litellm_snapshot") / "litellm_model_cost_snapshot.json"
    monkeypatch.setattr(litellm, "model_cost", dict(litellm.model_cost))
    monkeypatch.setenv("LITELLM_MODEL_COST_SNAPSHOT_PATH", str(path))
    monkeypatch.setattr(litellm_model_info, "_loaded_snapshot_mtime", None)
    monkeypatch.setattr(litellm_model_info, "_refresh_owner_lock", None)
    litellm.utils._invalidate_model_cost_lowercase_map()
    yield path
    owner_lock = litellm_model_info._refresh_owner_lock
    if owner_lock is not None:
        owner_lock.release()
    litellm.utils._invalidate_model_cost_lowercase_map()


@pytest.fixture
def stale_snapshot(snapshot_path):
    snapshot_path.write_text(
        json.dumps(
            {
                SNAPSHOT_ONLY_MODEL: {
                    "litellm_provider": "openai",
                    "mode": "chat",
                    "max_input_tokens": SNAPSHOT_CONTEXT_WINDOW,
                }
            }
        ),
        encoding="utf-8",
    )
    return snapshot_path


@pytest.fixture
def scheduler(monkeypatch):
    FakeScheduler.instances = []
    monkeypatch.setattr(litellm_model_info, "BackgroundScheduler", FakeScheduler)
    return FakeScheduler


@pytest.fixture
def no_network(monkeypatch):
    def refuse_connection(self, address):
        raise AssertionError(f"opened a connection to {address}")

    def refuse_get(url, **kwargs):
        raise AssertionError(f"GET {url}")

    monkeypatch.setattr(socket.socket, "connect", refuse_connection)
    monkeypatch.setattr(httpx, "get", refuse_get)


def test_refresh_is_off_in_every_environment_default():
    schema = yaml.safe_load(
        (Path(django_settings.BASE_DIR).parent / "env.yaml").read_text(encoding="utf-8")
    )
    defaults = schema["groups"]["django"]["vars"]["LITELLM_MODEL_COST_REFRESH_ENABLED"]["default"]

    assert defaults == {"prod": "false", "dev": "false"}


def test_disabled_schedules_nothing_and_makes_no_request(
    settings, snapshot_path, scheduler, no_network
):
    settings.LITELLM_MODEL_COST_REFRESH_ENABLED = False

    assert start_litellm_refresh_if_owner() is False

    assert scheduler.instances == []
    assert litellm_model_info._refresh_owner_lock is None
    assert not Path(str(snapshot_path) + ".lock").exists()


def test_disabled_ignores_a_snapshot_left_on_disk(settings, stale_snapshot, scheduler, no_network):
    settings.LITELLM_MODEL_COST_REFRESH_ENABLED = False

    start_litellm_refresh_if_owner()
    context_window, _, is_trusted = resolve_context_window(SNAPSHOT_ONLY_MODEL)

    assert SNAPSHOT_ONLY_MODEL not in litellm.model_cost
    assert (context_window, is_trusted) == (FALLBACK_CONTEXT_WINDOW, False)


def test_enabled_schedules_the_daily_refresh_an_hour_after_start(
    settings, snapshot_path, scheduler, no_network
):
    settings.LITELLM_MODEL_COST_REFRESH_ENABLED = True
    before = datetime.now(UTC)

    assert start_litellm_refresh_if_owner() is True

    (owner_scheduler,) = scheduler.instances
    assert owner_scheduler.started is True
    (job,) = owner_scheduler.jobs
    assert job["func"] is refresh_litellm_model_cost
    assert (job["trigger"], job["days"]) == ("interval", 1)
    assert before + timedelta(hours=1) <= job["next_run_time"] <= datetime.now(UTC) + timedelta(
        hours=1
    )


def test_enabled_merges_the_snapshot_on_disk(settings, stale_snapshot, scheduler, no_network):
    settings.LITELLM_MODEL_COST_REFRESH_ENABLED = True

    start_litellm_refresh_if_owner()

    assert resolve_context_window(SNAPSHOT_ONLY_MODEL) == (SNAPSHOT_CONTEXT_WINDOW, None, True)
