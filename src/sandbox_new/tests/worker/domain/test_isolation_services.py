"""Behavior of the isolation decision services.

Pure policy: each function takes the kernel's Landlock ABI plus the configured
requirement flags and returns what to confine. The matrices below are the policy, so a
change to any of them should be a deliberate, reviewed change.
"""

from pathlib import Path

import pytest

from worker.domain.enums import (
    FilesystemIsolationPolicy,
    NetworkPolicy,
    SignalIsolationPolicy,
)
from worker.domain.services import (
    build_jail,
    decide_filesystem_isolation_policy,
    decide_network_policy,
    decide_signal_isolation_policy,
)

STORAGE_PORT = 9000


@pytest.mark.parametrize("abi", [0, 3, 4, 6])
@pytest.mark.parametrize("use_storage", [False, True])
def test_an_unblocked_network_is_unrestricted_whatever_the_kernel(abi, use_storage):
    decision = decide_network_policy(
        block_network=False, use_storage=use_storage, landlock_abi=abi, storage_port=STORAGE_PORT
    )
    assert decision.policy is NetworkPolicy.UNRESTRICTED
    assert decision.allowed_tcp_ports == ()


@pytest.mark.parametrize("abi", [0, 3, 4, 6])
def test_a_blocked_network_without_storage_blocks_everything(abi):
    decision = decide_network_policy(
        block_network=True, use_storage=False, landlock_abi=abi, storage_port=STORAGE_PORT
    )
    assert decision.policy is NetworkPolicy.BLOCK_ALL


@pytest.mark.parametrize("abi", [0, 1, 3])
def test_storage_on_a_kernel_too_old_for_the_port_carve_out_is_refused(abi):
    decision = decide_network_policy(
        block_network=True, use_storage=True, landlock_abi=abi, storage_port=STORAGE_PORT
    )
    assert decision.policy is NetworkPolicy.REFUSE


@pytest.mark.parametrize("abi", [4, 5, 6])
def test_storage_on_a_new_enough_kernel_allows_only_the_storage_port(abi):
    decision = decide_network_policy(
        block_network=True, use_storage=True, landlock_abi=abi, storage_port=STORAGE_PORT
    )
    assert decision.policy is NetworkPolicy.ALLOW_PORTS
    assert decision.allowed_tcp_ports == (STORAGE_PORT,)


@pytest.mark.parametrize("require", [False, True])
def test_signal_isolation_does_not_apply_without_landlock(require):
    assert (
        decide_signal_isolation_policy(landlock_abi=0, require_signal_isolation=require)
        is SignalIsolationPolicy.NOT_APPLICABLE
    )


@pytest.mark.parametrize("abi", [6, 7])
@pytest.mark.parametrize("require", [False, True])
def test_signal_isolation_is_enforced_from_abi_6(abi, require):
    assert (
        decide_signal_isolation_policy(landlock_abi=abi, require_signal_isolation=require)
        is SignalIsolationPolicy.ENFORCE
    )


@pytest.mark.parametrize("abi", [1, 3, 5])
def test_required_signal_isolation_on_an_old_kernel_is_refused(abi):
    assert (
        decide_signal_isolation_policy(landlock_abi=abi, require_signal_isolation=True)
        is SignalIsolationPolicy.REFUSE
    )


@pytest.mark.parametrize("abi", [1, 3, 5])
def test_optional_signal_isolation_on_an_old_kernel_runs_unisolated(abi):
    assert (
        decide_signal_isolation_policy(landlock_abi=abi, require_signal_isolation=False)
        is SignalIsolationPolicy.UNISOLATED
    )


@pytest.mark.parametrize("abi", [1, 4, 6])
@pytest.mark.parametrize("require", [False, True])
def test_any_landlock_can_enforce_the_filesystem_jail(abi, require):
    assert (
        decide_filesystem_isolation_policy(landlock_abi=abi, require_isolation=require)
        is FilesystemIsolationPolicy.ENFORCE
    )


def test_required_isolation_without_landlock_is_refused():
    assert (
        decide_filesystem_isolation_policy(landlock_abi=0, require_isolation=True)
        is FilesystemIsolationPolicy.REFUSE
    )


def test_optional_isolation_without_landlock_runs_unconfined():
    assert (
        decide_filesystem_isolation_policy(landlock_abi=0, require_isolation=False)
        is FilesystemIsolationPolicy.UNCONFINED
    )


def build_test_jail(tmp_path: Path):
    return build_jail(
        exec_dir=tmp_path / "executions" / "exec-1",
        venv_path=tmp_path / "venvs" / "venv-1abc",
    )


def test_the_jail_grants_write_access_only_to_the_runs_own_workspace(tmp_path):
    jail = build_test_jail(tmp_path)
    exec_dir = tmp_path / "executions" / "exec-1"

    assert set(jail.read_write) == {
        str(exec_dir),
        str(exec_dir / "home"),
        str(exec_dir / "tmp"),
    }


def test_the_jail_grants_execute_access_to_the_venv_and_system_directories(tmp_path):
    jail = build_test_jail(tmp_path)

    assert str(tmp_path / "venvs" / "venv-1abc") in jail.read_exec
    assert set(jail.read_exec) - {str(tmp_path / "venvs" / "venv-1abc")} == {
        "/usr",
        "/lib",
        "/lib64",
        "/bin",
    }


def test_every_jail_path_is_absolute(tmp_path):
    jail = build_test_jail(tmp_path)

    for path in (*jail.read_write, *jail.read_only, *jail.read_exec):
        assert Path(path).is_absolute(), path


@pytest.mark.parametrize(
    "forbidden", ["/etc/shadow", "/etc/passwd", "/root", "/proc", "/sys", "/etc"]
)
def test_the_jail_does_not_grant_sensitive_system_paths(tmp_path, forbidden):
    jail = build_test_jail(tmp_path)

    assert forbidden not in (*jail.read_write, *jail.read_only, *jail.read_exec)
