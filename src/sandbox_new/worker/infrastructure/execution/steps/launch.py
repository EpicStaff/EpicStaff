"""Runs the wrapped code in a confined subprocess and captures its streams.

Spawns the child under the launcher (which applies the Landlock/seccomp plan),
dropped to ``sandboxuser`` and in its own session so a timeout can kill the whole
process group. Records raw ``stdout``/``stderr``/``returncode`` on the context; the
capture step reads the result file and scrubs secrets afterwards. A timeout is
reported as return code 124. Nothing here raises: a failure to launch surfaces as a
failed context.

The timeout a run gets is decided here by ``effective_timeout``, not by the caller: the
per-job value is a request, bounded by the deployment's configured minimum and maximum.
"""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

from worker.application.context import ExecutionContext
from worker.domain.enums import NetworkPolicy
from worker.domain.models import IsolationPlan
from worker.infrastructure.execution.privileges import privilege_drop_kwargs

__all__ = ["LaunchStep", "effective_timeout"]

# Referenced by path, never imported: launcher.py must run as a script so its
# flat ``import landlock`` resolves against its own directory on sys.path.
LAUNCHER_PATH = Path(__file__).parents[2] / "isolation" / "launcher.py"

# Bound the post-kill wait for communicate() to drain the pipes. A grandchild
# that escaped the process group could still hold a pipe's write end open, which
# would keep communicate() from ever seeing EOF; without this bound that hangs.
_TIMEOUT_DRAIN_GRACE_SECONDS = 5


def effective_timeout(
    requested: float | None, *, default: float, minimum: float, maximum: float | None
) -> float:
    """Return the timeout to actually run with, in seconds.

    The requested value reaches the sandbox from a python tool's configuration and is
    untrusted, so ``maximum`` is the security bound it is capped at (None there means no
    upper limit) and ``minimum`` keeps a too-small value from killing every run before it
    starts. ``default`` only fills in a request that carries no timeout of its own.
    """
    timeout = default if requested is None else max(requested, minimum)
    if maximum is None:
        return timeout
    return min(timeout, maximum)


class LaunchStep:
    def __init__(self, *, default_timeout: float, min_timeout: float, max_timeout: float | None):
        self._default_timeout = default_timeout
        self._min_timeout = min_timeout
        self._max_timeout = max_timeout

    async def __call__(self, context: ExecutionContext) -> None:
        isolation = context.isolation
        timeout = effective_timeout(
            context.job.timeout,
            default=self._default_timeout,
            minimum=self._min_timeout,
            maximum=self._max_timeout,
        )

        env = dict(context.env)
        self._apply_network_marker(env, isolation)

        argv = self._build_argv(
            isolation=isolation,
            python_executable=context.python_executable,
            code_path=context.code_path,
        )

        job = context.job
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="exec_launched",
            session_id=job.session_id,
            execution_id=job.execution_id,
        )
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(context.work_dir),
            start_new_session=True,
            **privilege_drop_kwargs(),
        )

        comm_task = asyncio.ensure_future(process.communicate())
        done, _ = await asyncio.wait({comm_task}, timeout=timeout)

        timed_out = comm_task not in done
        if timed_out:
            await self._capture_timeout(context, process, comm_task, timeout)
        else:
            stdout_bytes, stderr_bytes = comm_task.result()
            context.stdout = stdout_bytes.decode("utf-8", errors="replace")
            context.stderr = stderr_bytes.decode("utf-8", errors="replace")
            context.returncode = process.returncode
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="exec_exited",
            session_id=job.session_id,
            execution_id=job.execution_id,
            returncode=context.returncode,
            timed_out=timed_out,
        )

    @staticmethod
    def _apply_network_marker(env: dict[str, str], isolation: IsolationPlan) -> None:
        # Lets the wrapped code's preamble tell a genuine network denial apart
        # from an unrelated Landlock filesystem EACCES and pick the right wording.
        if isolation.network.policy is NetworkPolicy.BLOCK_ALL:
            env["SANDBOX_NETWORK_BLOCKED"] = "all"
        elif isolation.network.policy is NetworkPolicy.ALLOW_PORTS:
            env["SANDBOX_NETWORK_BLOCKED"] = "storage_only"

    @staticmethod
    def _build_argv(
        *, isolation: IsolationPlan, python_executable: Path, code_path: Path
    ) -> list[str]:
        argv = [str(python_executable), str(code_path)]

        use_launcher = (
            isolation.landlock_abi >= 1 or isolation.network.policy is NetworkPolicy.BLOCK_ALL
        )
        if not use_launcher:
            return argv

        jail = None
        if isolation.jail is not None:
            jail = {
                "read_write": list(isolation.jail.read_write),
                "read_only": list(isolation.jail.read_only),
                "read_exec": list(isolation.jail.read_exec),
            }

        if isolation.network.policy is NetworkPolicy.BLOCK_ALL:
            network = {"mode": "block_all"}
        elif isolation.network.policy is NetworkPolicy.ALLOW_PORTS:
            network = {"mode": "allow_ports", "ports": list(isolation.network.allowed_tcp_ports)}
        else:
            network = {"mode": "unrestricted"}

        plan = {
            "jail": jail,
            "network": network,
            "isolate_signals": isolation.isolate_signals,
        }
        return [sys.executable, str(LAUNCHER_PATH), json.dumps(plan), *argv]

    async def _capture_timeout(
        self,
        context: ExecutionContext,
        process: asyncio.subprocess.Process,
        comm_task: asyncio.Task,
        timeout: float,
    ) -> None:
        """Terminate a hung execution and record it as a timed-out result."""
        execution_id = context.job.execution_id
        logger.error(
            "Execution {} exceeded {} seconds; killing process tree.",
            execution_id,
            f"{timeout:g}",
        )

        killed = _kill_process_tree(process, execution_id=execution_id)

        stdout_bytes, stderr_bytes = b"", b""
        if killed:
            done, _ = await asyncio.wait({comm_task}, timeout=_TIMEOUT_DRAIN_GRACE_SECONDS)
            if comm_task in done:
                try:
                    stdout_bytes, stderr_bytes = comm_task.result()
                except Exception:
                    logger.exception(
                        "Failed to drain partial output for timed-out execution {}",
                        execution_id,
                    )
            else:
                comm_task.cancel()
                logger.warning(
                    "Could not recover partial output for timed-out execution {} within "
                    "{} seconds; a grandchild may still hold a pipe open.",
                    execution_id,
                    _TIMEOUT_DRAIN_GRACE_SECONDS,
                )
        else:
            comm_task.cancel()

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        timeout_message = f"Execution exceeded {timeout:g} seconds and was terminated."
        if not killed:
            timeout_message += " Process could not be terminated and may still be running."
        stderr = f"{stderr}\n{timeout_message}" if stderr else timeout_message

        context.stdout = stdout
        context.stderr = stderr
        context.returncode = 124


def _kill_process_tree(process: asyncio.subprocess.Process, execution_id: str) -> bool:
    """Kill a timed-out execution and every child it spawned."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True
    except (AttributeError, OSError):
        pass

    try:
        process.kill()
        return True
    except ProcessLookupError:
        return True
    except OSError as kill_error:
        logger.error(
            "Could not signal timed-out execution {}: {}. Process is still running / "
            "has leaked; the container is likely missing CAP_KILL.",
            execution_id,
            kill_error,
        )
        return False
