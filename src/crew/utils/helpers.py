import logging
import sys

from utils.envpy import load_env_from_yaml_config

logger = logging.getLogger(__name__)
logger.debug(f"Entered {__file__}")
import os


def signal_handler(sig, frame):
    print(
        "\n\nI received a termination signal. You are the Terminator?! I'll shut down gracefully...\n\n"
    )
    sys.exit(0)


# Function to load environment variables
def load_env(config_path, expected_vars=None):
    """
    Load environment variables from a confi.yaml file and verify expected variables with stylized print output.

    :param config_path: Path to the confi.yaml file, can be relative or absolute.
    :param expected_vars: A list of environment variable names that are expected to be set.
    """
    # Convert to absolute path if necessary
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_path)

    loaded = load_env_from_yaml_config(config_path)
    if not loaded:
        print(
            f"I failed to load the config.yaml file from '{config_path}'. I'm so sorry, the environmen variables may not be set."
        )
        return

    if expected_vars:
        missing_vars = [var for var in expected_vars if not os.getenv(var)]
        if missing_vars:
            logger.info(
                f"I was expecting these environemnt variables,: {', '.join(missing_vars)}, but maybe it will be ok...\n"
            )
