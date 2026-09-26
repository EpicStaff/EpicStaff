"""Unit coverage for decide_network_policy(): a pure decision function, no
chain, no Redis, no syscalls."""

import dataclasses

import pytest

from network_policy import NetworkDecision, NetworkPolicy, decide_network_policy

_STORAGE_PORT = 9000


class TestDecideNetworkPolicy:
    def test_block_network_false_is_always_unrestricted(self):
        for use_storage in (False, True):
            for landlock_abi in (0, 3, 4, 5):
                decision = decide_network_policy(
                    block_network=False,
                    use_storage=use_storage,
                    landlock_abi=landlock_abi,
                    storage_port=_STORAGE_PORT,
                )
                assert decision.policy is NetworkPolicy.UNRESTRICTED
                assert decision.allowed_tcp_ports == ()

    def test_block_network_without_storage_blocks_all_regardless_of_abi(self):
        for landlock_abi in (0, 1, 3, 4, 5):
            decision = decide_network_policy(
                block_network=True,
                use_storage=False,
                landlock_abi=landlock_abi,
                storage_port=_STORAGE_PORT,
            )
            assert decision.policy is NetworkPolicy.BLOCK_ALL
            assert decision.allowed_tcp_ports == ()

    def test_block_network_with_storage_and_sufficient_abi_allows_storage_port(self):
        decision = decide_network_policy(
            block_network=True,
            use_storage=True,
            landlock_abi=4,
            storage_port=_STORAGE_PORT,
        )
        assert decision.policy is NetworkPolicy.ALLOW_PORTS
        assert decision.allowed_tcp_ports == (_STORAGE_PORT,)

    def test_block_network_with_storage_and_higher_abi_allows_storage_port(self):
        decision = decide_network_policy(
            block_network=True,
            use_storage=True,
            landlock_abi=5,
            storage_port=_STORAGE_PORT,
        )
        assert decision.policy is NetworkPolicy.ALLOW_PORTS
        assert decision.allowed_tcp_ports == (_STORAGE_PORT,)

    def test_block_network_with_storage_and_insufficient_abi_refuses(self):
        decision = decide_network_policy(
            block_network=True,
            use_storage=True,
            landlock_abi=3,
            storage_port=_STORAGE_PORT,
        )
        assert decision.policy is NetworkPolicy.REFUSE
        assert decision.allowed_tcp_ports == ()

    def test_block_network_with_storage_and_no_landlock_refuses(self):
        decision = decide_network_policy(
            block_network=True,
            use_storage=True,
            landlock_abi=0,
            storage_port=_STORAGE_PORT,
        )
        assert decision.policy is NetworkPolicy.REFUSE

    def test_allowed_tcp_ports_threads_through_a_different_storage_port(self):
        decision = decide_network_policy(
            block_network=True,
            use_storage=True,
            landlock_abi=4,
            storage_port=12345,
        )
        assert decision.allowed_tcp_ports == (12345,)

    def test_decision_is_frozen(self):
        decision = NetworkDecision(policy=NetworkPolicy.BLOCK_ALL)

        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.policy = NetworkPolicy.UNRESTRICTED
