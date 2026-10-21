"""`python -m es_plugins.agent`: started by the launcher as UID 10000."""

import asyncio
import os
import sys

from loguru import logger

from es_plugins.agent.main import run_agent
from es_plugins.agent.port_reservation import PortReservationError
from es_plugins.agent.settings import AgentSettings, AgentSettingsError
from es_plugins.egress.policy_writer import EgressPolicyError
from es_plugins.hardening import make_not_dumpable
from es_plugins.layout import NodeLayout
from es_plugins.logging_setup import configure_logging

EXIT_CONFIGURATION_ERROR = 64
EXIT_PORTS_UNAVAILABLE = 71


def main() -> int:
    configure_logging("agent")
    make_not_dumpable()
    os.umask(0o022)
    try:
        settings = AgentSettings.from_environment()
    except AgentSettingsError as error:
        logger.error("{}", error)
        return EXIT_CONFIGURATION_ERROR
    try:
        asyncio.run(run_agent(settings, NodeLayout()))
    except EgressPolicyError as error:
        logger.error("{} (is the plugin_egress_policy volume mounted?)", error)
        return EXIT_CONFIGURATION_ERROR
    except PortReservationError as error:
        logger.error("{}", error)
        return EXIT_PORTS_UNAVAILABLE
    return 0


if __name__ == "__main__":
    sys.exit(main())
