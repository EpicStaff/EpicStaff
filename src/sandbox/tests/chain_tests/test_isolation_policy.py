"""Unit coverage for the pure isolation decision functions:
decide_network_policy() and decide_signal_isolation_policy(). No chain, no
Redis, no syscalls."""

import pytest

from network_policy import NetworkPolicy, decide_network_policy
from signal_isolation_policy import SignalIsolationPolicy, decide_signal_isolation_policy

_STORAGE_PORT = 9000


_UNRESTRICTED = (NetworkPolicy.UNRESTRICTED, ())
_BLOCK_ALL = (NetworkPolicy.BLOCK_ALL, ())
_REFUSE = (NetworkPolicy.REFUSE, ())
_STORAGE_PORT_ONLY = (NetworkPolicy.ALLOW_PORTS, (_STORAGE_PORT,))


@pytest.mark.parametrize(
    ("block_network", "use_storage", "landlock_abi", "expected"),
    [
        *[(False, use_storage, abi, _UNRESTRICTED) for use_storage in (False, True) for abi in (0, 3, 4, 5)],
        *[(True, False, abi, _BLOCK_ALL) for abi in (0, 1, 3, 4, 5)],
        # The storage port carve-out needs Landlock net (ABI 4); below it, refuse
        # rather than silently drop the confinement the execution asked for.
        (True, True, 0, _REFUSE),
        (True, True, 3, _REFUSE),
        (True, True, 4, _STORAGE_PORT_ONLY),
        (True, True, 5, _STORAGE_PORT_ONLY),
    ],
)
def test_network_policy(block_network, use_storage, landlock_abi, expected):
    decision = decide_network_policy(
        block_network=block_network,
        use_storage=use_storage,
        landlock_abi=landlock_abi,
        storage_port=_STORAGE_PORT,
    )

    assert (decision.policy, decision.allowed_tcp_ports) == expected


def test_allowed_port_is_the_configured_storage_port():
    decision = decide_network_policy(
        block_network=True, use_storage=True, landlock_abi=4, storage_port=12345
    )

    assert decision.allowed_tcp_ports == (12345,)


class TestDecideSignalIsolationPolicy:
    @pytest.mark.parametrize("landlock_abi", [6, 7, 8])
    @pytest.mark.parametrize("require_signal_isolation", [True, False])
    def test_signal_isolation_is_always_enforced_when_the_kernel_supports_it(
        self, landlock_abi, require_signal_isolation
    ):
        policy = decide_signal_isolation_policy(
            landlock_abi=landlock_abi, require_signal_isolation=require_signal_isolation
        )

        assert policy is SignalIsolationPolicy.ENFORCE

    @pytest.mark.parametrize("landlock_abi", [1, 4, 5])
    def test_old_landlock_refuses_when_signal_isolation_is_required(self, landlock_abi):
        policy = decide_signal_isolation_policy(
            landlock_abi=landlock_abi, require_signal_isolation=True
        )

        assert policy is SignalIsolationPolicy.REFUSE

    @pytest.mark.parametrize("landlock_abi", [1, 4, 5])
    def test_old_landlock_runs_unisolated_when_signal_isolation_is_not_required(
        self, landlock_abi
    ):
        policy = decide_signal_isolation_policy(
            landlock_abi=landlock_abi, require_signal_isolation=False
        )

        assert policy is SignalIsolationPolicy.UNISOLATED

    @pytest.mark.parametrize("require_signal_isolation", [True, False])
    def test_no_landlock_defers_to_the_filesystem_isolation_decision(
        self, require_signal_isolation
    ):
        policy = decide_signal_isolation_policy(
            landlock_abi=0, require_signal_isolation=require_signal_isolation
        )

        assert policy is SignalIsolationPolicy.NOT_APPLICABLE
