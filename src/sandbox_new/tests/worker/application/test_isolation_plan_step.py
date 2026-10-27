"""Behavior of the isolation-plan step.

It decides nothing itself: it reads the ABI through the probe, hands it to the domain
services, and either records the plan or fails the context. A refusal must leave
``isolation`` unset, because that is what keeps the launch step from running anything.
"""

import pytest

from worker.application.steps import BuildIsolationPlan
from worker.domain.enums import NetworkPolicy
from tests.builders import make_context, make_worker_job
from tests.fakes import FakeIsolationProbe

STORAGE_PORT = 9000


def build_step(abi: int, **flags) -> BuildIsolationPlan:
    settings = {
        "require_isolation": True,
        "block_network": True,
        "require_signal_isolation": True,
        "storage_port": STORAGE_PORT,
    }
    settings.update(flags)
    return BuildIsolationPlan(FakeIsolationProbe(abi), **settings)


@pytest.fixture
def context(tmp_path):
    exec_dir = tmp_path / "executions" / "exec-1"
    exec_dir.mkdir(parents=True)
    return make_context(
        exec_dir=exec_dir,
        python_executable=tmp_path / "venvs" / "venv-1abc" / "bin" / "python",
    )


async def test_a_modern_kernel_blocks_the_network_and_isolates_signals(context):
    await build_step(6)(context)

    assert context.completed is False
    assert context.isolation.landlock_abi == 6
    assert context.isolation.network.policy is NetworkPolicy.BLOCK_ALL
    assert context.isolation.isolate_signals is True
    assert context.isolation.jail is not None


async def test_the_jail_is_rooted_at_the_execution_workspace_and_the_venv(context, tmp_path):
    await build_step(6)(context)

    jail = context.isolation.jail
    assert str(context.exec_dir) in jail.read_write
    assert str(tmp_path / "venvs" / "venv-1abc") in jail.read_exec


async def test_a_kernel_without_landlock_refuses_when_isolation_is_required(context):
    await build_step(0)(context)

    assert context.isolation is None
    assert context.completed is True
    assert context.returncode == 1
    assert "kernel lacks Landlock" in context.stderr


async def test_a_kernel_without_landlock_runs_unconfined_when_isolation_is_optional(context):
    await build_step(0, require_isolation=False, require_signal_isolation=False)(context)

    assert context.completed is False
    assert context.isolation.jail is None
    assert context.isolation.isolate_signals is False
    assert context.isolation.network.policy is NetworkPolicy.BLOCK_ALL


async def test_required_signal_isolation_on_an_old_kernel_refuses(context):
    await build_step(3)(context)

    assert context.isolation is None
    assert context.completed is True
    assert "Landlock ABI 6+" in context.stderr


async def test_storage_on_a_kernel_too_old_for_the_port_carve_out_refuses(context):
    context.job = make_worker_job(use_storage=True, storage_org_prefix="org1")

    await build_step(3, require_signal_isolation=False)(context)

    assert context.isolation is None
    assert context.completed is True
    assert "Landlock ABI 4+" in context.stderr


async def test_storage_on_a_new_enough_kernel_allows_only_the_storage_port(context):
    context.job = make_worker_job(use_storage=True, storage_org_prefix="org1")

    await build_step(5, require_signal_isolation=False)(context)

    assert context.isolation.network.policy is NetworkPolicy.ALLOW_PORTS
    assert context.isolation.network.allowed_tcp_ports == (STORAGE_PORT,)
    assert context.isolation.isolate_signals is False


async def test_an_unblocked_network_leaves_the_execution_unrestricted(context):
    await build_step(6, block_network=False)(context)

    assert context.isolation.network.policy is NetworkPolicy.UNRESTRICTED
