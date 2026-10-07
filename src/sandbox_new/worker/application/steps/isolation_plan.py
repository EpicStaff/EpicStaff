"""Gathers the inputs the isolation decisions need and records the plan.

This step makes no decisions itself: it reads the kernel's Landlock ABI through the
probe port and the configured requirement flags, hands them to the domain services,
and stores the resulting ``IsolationPlan`` on the context. When a service refuses
(storage without a new enough kernel, or isolation required but unavailable), it
fails the context so the pipeline stops before anything is launched -- the error is
returned, never raised.
"""

from loguru import logger

from worker.application.context import ExecutionContext
from worker.application.ports.isolation_probe import AbstractIsolationProbe
from worker.domain.enums import (
    FilesystemIsolationPolicy,
    NetworkPolicy,
    SignalIsolationPolicy,
)
from worker.domain.models import IsolationPlan
from worker.domain.services import (
    build_jail,
    decide_filesystem_isolation_policy,
    decide_network_policy,
    decide_signal_isolation_policy,
)

__all__ = ["BuildIsolationPlan"]

_FILESYSTEM_REFUSED = "Sandbox isolation unavailable (kernel lacks Landlock); refusing to execute."
_SIGNAL_REFUSED = (
    "Sandbox signal isolation unavailable: executions require Landlock ABI 6+ "
    "(Linux 6.12+) to stop them signalling each other; refusing to execute. "
    "Set SANDBOX_REQUIRE_SIGNAL_ISOLATION=false to run without it."
)
_NETWORK_REFUSED = (
    "Sandbox network isolation unavailable: storage-enabled executions require "
    "Landlock ABI 4+ (Linux 6.7+) to restrict outbound connections to the storage "
    "port; refusing to execute. Set SANDBOX_BLOCK_NETWORK=false to disable network "
    "isolation for this execution."
)


class BuildIsolationPlan:
    def __init__(
        self,
        probe: AbstractIsolationProbe,
        *,
        require_isolation: bool,
        block_network: bool,
        require_signal_isolation: bool,
        storage_port: int,
    ):
        self._probe = probe
        self._require_isolation = require_isolation
        self._block_network = block_network
        self._require_signal_isolation = require_signal_isolation
        self._storage_port = storage_port

    async def __call__(self, context: ExecutionContext) -> None:
        execution_id = context.job.execution_id
        abi = self._probe.landlock_abi()

        filesystem = decide_filesystem_isolation_policy(
            landlock_abi=abi, require_isolation=self._require_isolation
        )
        if filesystem is FilesystemIsolationPolicy.REFUSE:
            logger.error("Filesystem isolation unavailable; refusing to execute {}.", execution_id)
            context.fail(_FILESYSTEM_REFUSED)
            return
        if filesystem is FilesystemIsolationPolicy.UNCONFINED:
            logger.warning(
                "Filesystem isolation unavailable; executing {} UNCONFINED.", execution_id
            )

        signal = decide_signal_isolation_policy(
            landlock_abi=abi, require_signal_isolation=self._require_signal_isolation
        )
        if signal is SignalIsolationPolicy.REFUSE:
            logger.error(
                "Signal isolation unavailable (Landlock ABI {} < 6); refusing to execute {}.",
                abi,
                execution_id,
            )
            context.fail(_SIGNAL_REFUSED)
            return
        if signal is SignalIsolationPolicy.UNISOLATED:
            logger.warning(
                "Signal isolation unavailable (Landlock ABI {} < 6); executing {} UNISOLATED.",
                abi,
                execution_id,
            )

        network = decide_network_policy(
            block_network=self._block_network,
            use_storage=context.job.use_storage,
            landlock_abi=abi,
            storage_port=self._storage_port,
        )
        if network.policy is NetworkPolicy.REFUSE:
            logger.error(
                "Network isolation unavailable (Landlock ABI {} < 4); refusing to execute "
                "{} because it uses storage.",
                abi,
                execution_id,
            )
            context.fail(_NETWORK_REFUSED)
            return

        jail = None
        if filesystem is FilesystemIsolationPolicy.ENFORCE:
            jail = build_jail(
                exec_dir=context.exec_dir,
                venv_path=context.python_executable.parent.parent,
                savefiles_root=context.savefiles_root,
            )

        context.isolation = IsolationPlan(
            landlock_abi=abi,
            network=network,
            isolate_signals=signal is SignalIsolationPolicy.ENFORCE,
            jail=jail,
        )
