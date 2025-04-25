import logging

logger = logging.getLogger(__name__)
import argparse
from config.config import AppConfig

name, version = AppConfig.name, AppConfig.version


def get_parser():
    # ANSI escape codes for coloring
    green = "\033[92m"
    cyan = "\033[96m"
    red = "\033[91m"
    reset = "\033[0m"

    version_string = f"{green}{name}: {cyan}{version}{reset}"
    parser = argparse.ArgumentParser(
        description="This program processes data from a Google Sheet and sets logging preferences.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--sheet_url",
        help="The URL of the Google Sheet.\nExample: https://docs.google.com/spreadsheets/d/123abc/ \n",
    )

    parser.add_argument(
        "--loglevel",
        type=str,
        default="ERROR",
        help="""Set the log level to control logging output. \nChoices include:
    DEBUG - Low-level system information for debugging
    INFO - General system information
    WARNING - Information about minor problems
    ERROR - Information about major problems
    CRITICAL - Information about critical problems \nDefault: ERROR
    """,
    )
    parser.add_argument("--env_path", type=str, default="../ENV/.env")

    parser.add_argument(
        "--version",
        action="version",
        version=version_string,
        help="Show program's version number and exit",
    )

    # Parse the arguments to check the validity of loglevel
    args = parser.parse_args()
    if getattr(logging, args.loglevel.upper(), None) is None:
        parser.error(f"{red}Invalid log level: {args.loglevel}{reset}")

    return args
