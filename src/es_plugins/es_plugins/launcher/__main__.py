"""Entry point of the es_plugins container: `python -m es_plugins.launcher` as PID 1, root."""

import os
import signal
import sys

from loguru import logger

from es_plugins.hardening import make_not_dumpable
from es_plugins.launcher.directory_setup import DirectorySetup
from es_plugins.launcher.kill_by_uid import signal_uid
from es_plugins.launcher.privileged_launcher import (
    LauncherOperations,
    LauncherServer,
    serve_until_agent_exits,
)
from es_plugins.launcher.process_spawn import SpawnSpec, spawn_process
from es_plugins.layout import AGENT_GID, AGENT_UID, NodeLayout
from es_plugins.logging_setup import configure_logging
from es_plugins.process_table import ProcessTable
from es_plugins.uid_range import UidRange

# The container's variables the agent needs; nothing else of the launcher's reaches it.
AGENT_VARIABLES = (
    "PLUGINS_NODE_NAME",
    "PLUGINS_NODE_KEY",
    # plugins_admin's password: only the agent holds it, never pip, a venv or a plugin.
    "PLUGINS_DB_ADMIN_PASSWORD",
    # plugins_backup's: the agent holds it for pg_dump, the one process it is given to.
    "PLUGINS_DB_BACKUP_PASSWORD",
    "PLUGINS_NODE_UID_RANGE",
    "PLUGINS_INTERNAL_API_URL",
    "ES_PLUGINS_DISK_MB_PER_PLUGIN",
    "ES_PLUGINS_FILES_PER_PLUGIN",
    "RUN_IN_DOCKER",
    "PATH",
    "PYTHONPATH",
    "VIRTUAL_ENV",
)
AGENT_STOP_TIMEOUT_SECONDS = 8.0
EXIT_CONFIGURATION_ERROR = 64


def agent_environment(layout: NodeLayout) -> dict[str, str]:
    environment = {name: os.environ[name] for name in AGENT_VARIABLES if name in os.environ}
    environment.update(
        HOME=str(layout.agent_directory),
        TMPDIR=str(layout.agent_temporary_directory),
        LANG="C.UTF-8",
        PYTHONSAFEPATH="1",
        PYTHONUNBUFFERED="1",
        PYTHONDONTWRITEBYTECODE="1",
        PIP_NO_CACHE_DIR="1",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
    )
    return environment


def main() -> int:
    configure_logging("launcher")
    make_not_dumpable()
    os.umask(0o022)
    try:
        uid_range = UidRange.parse(os.environ.get("PLUGINS_NODE_UID_RANGE", ""))
    except ValueError as error:
        logger.error("{}", error)
        return EXIT_CONFIGURATION_ERROR
    layout = NodeLayout()
    directory_setup = DirectorySetup(layout)
    directory_setup.prepare_tree()
    operations = LauncherOperations(layout, uid_range, directory_setup, ProcessTable())
    server = LauncherServer(layout.launcher_socket, operations, agent_uid=AGENT_UID)
    server.listen(group=AGENT_GID)

    stopping = False

    def request_stop(signal_number: int, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    agent_pid = spawn_process(
        SpawnSpec(
            uid=AGENT_UID,
            gid=AGENT_GID,
            argv=(sys.executable, "-m", "es_plugins.agent"),
            environment=agent_environment(layout),
            working_directory=layout.agent_directory,
        )
    )
    logger.info("Started the agent as UID {} (pid {})", AGENT_UID, agent_pid)
    while not stopping:
        server.serve_once()
        exit_code = operations.exit_code_of(agent_pid)
        if exit_code is not None:
            logger.error("The agent exited with status {}; stopping the node", exit_code)
            server.close()
            return exit_code if exit_code > 0 else 1
    logger.info("Stopping: asking the agent to stop its plugins")
    # The launcher has no CAP_KILL, so the signal comes from a helper running as the agent.
    signal_uid(AGENT_UID, signal.SIGTERM)
    # Keep serving while the agent shuts down: its graceful stop of each plugin (SIGTERM, then
    # SIGKILL) and its final report go through these requests, so the socket must stay open.
    if not serve_until_agent_exits(server, operations, agent_pid, AGENT_STOP_TIMEOUT_SECONDS):
        logger.warning("The agent did not stop in time")
    server.close()
    # Leaving PID 1 makes the kernel kill every process left in the container.
    return 0


if __name__ == "__main__":
    sys.exit(main())
