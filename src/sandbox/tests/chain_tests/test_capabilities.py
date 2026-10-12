"""CAP_NET_ADMIN is dropped, and only after the egress firewall is installed.

`capabilities.drop_net_admin` must clear exactly the CAP_NET_ADMIN bit from the
thread's capability sets (leaving the sandbox's other capabilities intact), and
`main.init` must call it only once `egress_firewall.apply` has succeeded, so the
firewall is already in place before the capability that could flush it is gone.

libc's capget/capset are faked, so the capability logic is exercised without
touching the real process credentials.
"""

import os

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: Linux capability syscalls via ctypes; runs in the Linux image",
)

import capabilities
from capabilities import drop_net_admin

_CAP_NET_ADMIN_BIT = 1 << 12
_ALL_BITS = 0xFFFFFFFF


class _FakeLibc:
    """Records capset input and returns preset capabilities from capget."""

    def __init__(self, preset: int = _ALL_BITS, capget_rc: int = 0, capset_rc: int = 0):
        self._preset = preset
        self._capget_rc = capget_rc
        self._capset_rc = capset_rc
        self.capset_calls: list[tuple[int, int, int]] = []

    def capget(self, header_ref, data):
        data[0].effective = self._preset
        data[0].permitted = self._preset
        data[0].inheritable = self._preset
        return self._capget_rc

    def capset(self, header_ref, data):
        self.capset_calls.append(
            (data[0].effective, data[0].permitted, data[0].inheritable)
        )
        return self._capset_rc


def test_drop_net_admin_clears_only_the_net_admin_bit(monkeypatch):
    fake = _FakeLibc(preset=_ALL_BITS)
    monkeypatch.setattr(capabilities, "_libc", fake)

    drop_net_admin()

    assert len(fake.capset_calls) == 1
    effective, permitted, inheritable = fake.capset_calls[0]
    for word in (effective, permitted, inheritable):
        assert word & _CAP_NET_ADMIN_BIT == 0
    # Every other capability the sandbox holds stays set.
    assert permitted == (_ALL_BITS & ~_CAP_NET_ADMIN_BIT)


def test_drop_net_admin_raises_when_capset_fails(monkeypatch):
    monkeypatch.setattr(capabilities, "_libc", _FakeLibc(capset_rc=-1))

    with pytest.raises(OSError):
        drop_net_admin()


def test_drop_net_admin_raises_when_capget_fails(monkeypatch):
    monkeypatch.setattr(capabilities, "_libc", _FakeLibc(capget_rc=-1))

    with pytest.raises(OSError):
        drop_net_admin()


@pytest.fixture
def main_module(tmp_path):
    """Import main, whose module-level os.chdir('savefiles') runs at import time.

    `main` does a relative `os.chdir("savefiles")` on import, so the cwd must
    contain that directory or the import raises FileNotFoundError. Run it from a
    throwaway dir that has it, and restore the cwd afterwards.
    """
    saved_cwd = os.getcwd()
    (tmp_path / "savefiles").mkdir()
    os.chdir(tmp_path)
    try:
        import main

        yield main
    finally:
        os.chdir(saved_cwd)


@pytest.mark.asyncio
async def test_init_drops_net_admin_after_firewall_apply(main_module, monkeypatch):
    main = main_module
    order: list[str] = []

    monkeypatch.setattr(main.settings, "BLOCK_PRIVATE_NETWORK", True)
    monkeypatch.setattr(main, "sweep_output_path", lambda: None)
    monkeypatch.setattr(main, "log_secret_masking_state", lambda: None)
    monkeypatch.setattr(main, "log_isolation_state", lambda: None)
    monkeypatch.setattr(
        main.egress_firewall, "apply", lambda uid: order.append("apply")
    )
    monkeypatch.setattr(
        main.capabilities, "drop_net_admin", lambda: order.append("drop")
    )

    async def _connect():
        order.append("connect")

    monkeypatch.setattr(main.redis_service, "connect", _connect)

    await main.init()

    assert order == ["apply", "drop", "connect"]


@pytest.mark.asyncio
async def test_init_skips_drop_when_firewall_apply_fails(main_module, monkeypatch):
    main = main_module
    order: list[str] = []

    monkeypatch.setattr(main.settings, "BLOCK_PRIVATE_NETWORK", True)
    monkeypatch.setattr(main, "sweep_output_path", lambda: None)
    monkeypatch.setattr(main, "log_secret_masking_state", lambda: None)
    monkeypatch.setattr(main, "log_isolation_state", lambda: None)

    def _failing_apply(uid):
        raise main.egress_firewall.EgressFirewallUnavailableError("no iptables")

    monkeypatch.setattr(main.egress_firewall, "apply", _failing_apply)
    monkeypatch.setattr(
        main.capabilities, "drop_net_admin", lambda: order.append("drop")
    )

    async def _connect():
        order.append("connect")

    monkeypatch.setattr(main.redis_service, "connect", _connect)

    await main.init()

    assert "drop" not in order
