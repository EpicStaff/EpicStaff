import logging

logger = logging.getLogger(__name__)
logger.debug(f"Entered {__file__}")
from rich.markdown import Markdown
from rich.console import Console
from rich.table import Table
import os
from dotenv import load_dotenv

import numpy as np
from config.config import AppConfig

template_sheet_url = AppConfig.template_sheet_url


# ASCII art and greetings print functions
def greetings_print():
    console = Console()
    console = Console(force_terminal=True, force_interactive=True)
    # ASCII art
    ascii_art = """
[green] ██████ ██████  ███████ ██     ██      █████  ██      ██████  ██    ██ ██
[yellow]██      ██   ██ ██      ██     ██     ██   ██ ██     ██       ██    ██ ██
[orange]██      ██████  █████   ██  █  ██     ███████ ██     ██   ███ ██    ██ ██
[red]██      ██   ██ ██      ██ ███ ██     ██   ██ ██     ██    ██ ██    ██ ██
[magenta] ██████ ██   ██ ███████  ███ ███      ██   ██ ██      ██████   ██████  ██
[blue]███████ ███████ ███████ ███████ ███████ ███████ ████████ ██████ ██████ ███████
"""

    console.print(ascii_art)
    # Create a markdown string for the greeting message
    greeting_message = f"""
# Howdy, ready to use this awsome app?

To get you started, copy this sheet template and create your agents and tasks. I'm waiting for you inside the sheet! :D
[{template_sheet_url}]({template_sheet_url})
"""
    # Print the greeting using Rich's Markdown support for nice formatting
    console.print(Markdown(greeting_message))
    console.print("\n")


def after_read_sheet_print(agents_df, tasks_df):
    console = Console()
    terminal_width = console.width  # Get the current width of the terminal
    terminal_width = max(terminal_width, 120)

    # Create a table for agents
    agents_table = Table(show_header=True, header_style="bold magenta")
    agent_role_width = max(
        int(terminal_width * 0.1), 10
    )  # 20% of terminal width, at least 20 characters
    goal_width = max(
        int(terminal_width * 0.3), 30
    )  # 40% of terminal width, at least 40 characters
    backstory_width = max(
        int(terminal_width * 0.6), 60
    )  # 40% of terminal width, at least 40 characte
    agents_table.add_column("Agent Role", style="dim", width=agent_role_width)
    agents_table.add_column("Goal", width=goal_width)
    agents_table.add_column("Backstory", width=backstory_width)

    for index, row in agents_df.iterrows():
        agents_table.add_row()
        agents_table.add_row(row["Agent Role"], row["Goal"], row["Backstory"])

    # Tasks Table
    task_name_width = max(
        int(terminal_width * 0.1), 10
    )  # 20% of terminal width, at least 20 characters
    agent_width = max(
        int(terminal_width * 0.2), 20
    )  # 20% of terminal width, at least 20 characters
    instructions_width = max(
        int(terminal_width * 0.7), 70
    )  # 60% of terminal width, at least 60 characters
    tasks_table = Table(show_header=True, header_style="bold magenta")
    tasks_table.add_column("Task Name", style="dim", width=task_name_width)
    tasks_table.add_column("Agent", width=agent_width)
    tasks_table.add_column("Instructions", width=instructions_width)

    for index, row in tasks_df.iterrows():
        tasks_table.add_row()
        tasks_table.add_row(row["Task Name"], row["Agent"], row["Instructions"])

    console.print(
        "\nI found these agents and tasks in the google sheet. Let's get your crew runing:"
    )
    # Display the tables
    console.print(agents_table)
    console.print(tasks_table)


# Function to load environment variables
def load_env(env_path, expected_vars=None):
    """
    Load environment variables from a .env file and verify expected variables with stylized print output.

    :param env_path: Path to the .env file, can be relative or absolute.
    :param expected_vars: A list of environment variable names that are expected to be set.
    """
    # Convert to absolute path if necessary
    if not os.path.isabs(env_path):
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), env_path)

    loaded = load_dotenv(env_path)
    if not loaded:
        print(
            f"I failed to load the .env file from '{env_path}'. I'm so sorry, the environmen variables may not be set."
        )
        return

    if expected_vars:
        missing_vars = [var for var in expected_vars if not os.getenv(var)]
        if missing_vars:
            logger.info(
                f"I was expecting these environemnt variables,: {', '.join(missing_vars)}, but maybe it will be ok...\n"
            )


import re
from urllib.parse import urlparse


def is_valid_google_sheets_url(url):
    if not url:  # Early return if URL is None or empty
        return False

    try:
        parsed_url = urlparse(url)
        if parsed_url.netloc != "docs.google.com" or not parsed_url.path.startswith(
            "/spreadsheets/d/"
        ):
            print(
                "I'm confused, it says its' not a Google Sheet URL *confused face* :/"
            )
            return False

        # Updated regex for improved accuracy
        match = re.match(r"^/spreadsheets/d/([a-zA-Z0-9-_]+)", parsed_url.path)
        if not match:
            print(
                "You fonnd the fist easter egg. This looks like a partially correct Google Sheet URL. Let's try again? : "
            )
            return False

        return True
    except Exception as e:
        print(f"The computer says: Error parsing URL... {e}")
        return False


def get_sheet_url_from_user():
    sheet_url = input("Let's copy paste the Google Sheet url and get started: ")
    while not is_valid_google_sheets_url(sheet_url):
        sheet_url = input(
            "Could you doule check the URL? This silly box is saying it's invalid :/ : "
        )
    return sheet_url


# # Helper function to convert strings to boolean
# def str_to_bool(value_str):
#     if isinstance(value_str, (bool, np.bool_)):
#         return value_str
#     else:
#         return value_str.lower() in ['true', '1', 't', 'y', 'yes']
