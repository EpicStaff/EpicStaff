import logging
import os
import sys
import signal

from rich.console import Console
from rich.logging import RichHandler


###
console = Console()
logging.basicConfig(
    level="ERROR",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True)],
)
logger = logging.getLogger("rich")
###


###
os.environ["HAYSTACK_TELEMETRY_ENABLED"] = "False"  # Attmpt to turn off telemetry
os.environ["ANONYMIZED_TELEMETRY"] = "False"  # Disable interpreter telemetry
os.environ["EC_TELEMETRY"] = "False"  # Disable embedchain telemetry


###
def signal_handler(sig, frame):
    print(
        "\n\nI received a termination signal. You are the Terminator?! I'll shut down gracefully...\n\n"
    )
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
###
from rich.table import Table
from textwrap import dedent
from crewai import Crew, Task, Agent, Process

from utils.agent_crew_llm import get_llm
from utils.tools_mapping import ToolsMapping
from utils.cli_parser import get_parser
from utils.helpers import load_env, is_valid_google_sheets_url, get_sheet_url_from_user
from utils import Sheets, helpers

import pandas as pd
import sentry_sdk
from config.config import AppConfig


def create_agents_from_df(row, models_df=None, tools_df=None):
    def get_agent_tools(tools_string):
        tool_names = [tool.strip() for tool in tools_string.split(",")]
        tools_mapping = ToolsMapping(
            tools_df, models_df
        )  # Get the ToolsMapping instance
        tools_dict = (
            tools_mapping.get_tools()
        )  # Get the dictionary of tools from the instance
        return [tools_dict[tool] for tool in tool_names if tool in tools_dict]

    role = row.get("Agent Role", "Assistant")
    goal = row.get("Goal", "To assist the human in their tasks")
    model_name = row.get("Model Name", "gpt-4-turbo-preview").strip()
    backstory = row.get("Backstory", "...")
    temperature = row.get("Temperature", 0.8)
    max_iter = row.get("Max_iter", 15)
    verbose = row.get("Verbose", True)
    memory = row.get("Memory", True)
    tools_string = row.get("Tools")
    tools = get_agent_tools(tools_string)
    allow_delegation = row.get("Allow delegation", False)

    # Retrieve Agent model details
    model_details = models_df[
        models_df["Model"].str.strip() == model_name
    ]  # Filter the models dataframe for the specific model

    if model_details.empty:
        llm = None
        raise ValueError(
            f"Failed to retrieve or initialize the language model for {model_name}"
        )
    else:
        # Retrieve each attribute, ensuring it exists and is not NaN; otherwise, default to None
        num_ctx = (
            int(model_details["Context size (local only)"].iloc[0])
            if "Context size (local only)" in model_details.columns
            and not pd.isna(model_details["Context size (local only)"].iloc[0])
            else None
        )
        provider = (
            str(model_details["Provider"].iloc[0])
            if "Provider" in model_details.columns
            and not pd.isna(model_details["Provider"].iloc[0])
            else None
        )
        base_url = (
            str(model_details["base_url"].iloc[0])
            if "base_url" in model_details.columns
            and not pd.isna(model_details["base_url"].iloc[0])
            else None
        )
        deployment = (
            str(model_details["Deployment"].iloc[0])
            if "Deployment" in model_details.columns
            and not pd.isna(model_details["Deployment"].iloc[0])
            else None
        )

        llm = get_llm(
            model_name=model_name,
            temperature=temperature,
            num_ctx=num_ctx,
            provider=provider,
            base_url=base_url,
            deployment=deployment,
        )

        # Retrieve function calling model details
    function_calling_model_name = row.get("Function Calling Model", model_name)
    if isinstance(function_calling_model_name, str):
        # print(function_calling_model_name)
        function_calling_model_name = function_calling_model_name.strip()
        function_calling_model_details = models_df[
            models_df["Model"].str.strip() == function_calling_model_name
        ]
    else:
        function_calling_model_details = None

    if function_calling_model_details is None or function_calling_model_details.empty:
        function_calling_llm = llm
    else:
        num_ctx = (
            int(function_calling_model_details["Context size (local only)"].iloc[0])
            if "Context size (local only)" in function_calling_model_details.columns
            and not pd.isna(
                function_calling_model_details["Context size (local only)"].iloc[0]
            )
            else None
        )
        provider = (
            function_calling_model_details["Provider"].iloc[0]
            if "Provider" in function_calling_model_details.columns
            and not pd.isna(function_calling_model_details["Provider"].iloc[0])
            else None
        )
        base_url = (
            function_calling_model_details["base_url"].iloc[0]
            if "base_url" in function_calling_model_details.columns
            and not pd.isna(function_calling_model_details["base_url"].iloc[0])
            else None
        )
        deployment = (
            function_calling_model_details["Deployment"].iloc[0]
            if "Deployment" in function_calling_model_details.columns
            and not pd.isna(function_calling_model_details["Deployment"].iloc[0])
            else None
        )

        function_calling_llm = get_llm(
            model_name=function_calling_model_name,
            temperature=temperature,
            num_ctx=num_ctx,
            provider=provider,
            base_url=base_url,
            deployment=deployment,
        )

    agent_config = {
        # agent_executor:                                            #An instance of the CrewAgentExecutor class.
        "role": role,
        "goal": goal,
        "backstory": backstory,
        "allow_delegation": allow_delegation,  # Whether the agent is allowed to delegate tasks to other agents.
        "verbose": verbose,  # Whether the agent execution should be in verbose mode.
        "tools": tools,  # Tools at agents disposal
        "memory": memory,  # Whether the agent should have memory or not.
        "max_iter": max_iter,
        # TODO: Remove hardcoding #Maximum number of iterations for an agent to execute a task.
        "llm": llm,  # The language model that will run the agent.
        "function_calling_llm": function_calling_llm,
        # The language model that will the tool calling for this agent, it overrides the crew function_calling_llm.
        # step_callback:                                             #Callback to be executed after each step of the agent execution.
        # callbacks:                                                 #A list of callback functions from the langchain library that are triggered during the agent's execution process
    }
    if llm is None:
        print(
            f"I couldn't manage to create an llm model for the agent. {role}. The model was supposed to be {model_name}."
        )
        print(
            f"Please check the api keys and model name and the configuration in the sheet. Exiting..."
        )
        sys.exit(0)
    else:
        return Agent(config=agent_config)


def get_agent_by_role(agents, desired_role):
    return next((agent for agent in agents if agent.role == desired_role), None)


def create_tasks_from_df(row, assignment, created_agents, **kwargs):
    description = row["Instructions"].replace("{assignment}", assignment)
    desired_role = row["Agent"]

    return Task(
        description=dedent(description),
        expected_output=row["Expected Output"],
        agent=get_agent_by_role(created_agents, desired_role),
    )


def create_crew(created_agents, created_tasks, crew_df):
    # Embedding model (Memory)
    memory = crew_df["Memory"][0]
    embedding_model = crew_df["Embedding model"].get(0)

    if embedding_model is None or pd.isna(embedding_model):
        logger.info(
            "No embedding model for crew specified in the sheet. Turning off memory."
        )
        deployment_name = None
        provider = None
        base_url = None
        memory = False
        embedder_config = None
    else:
        deployment_name = models_df.loc[
            models_df["Model"] == embedding_model, "Deployment"
        ].values[0]
        provider = models_df.loc[
            models_df["Model"] == embedding_model, "Provider"
        ].values[0]
        base_url = models_df.loc[
            models_df["Model"] == embedding_model, "base_url"
        ].values[0]

        # Create provider specific congig and load proveder specific ENV variables if it can't be avoided
        embedder_config = {
            "model": embedding_model,
        }

    if provider == "azure-openai":
        embedder_config["deployment_name"] = (
            deployment_name  # Set azure specific config
        )
        # os.environ["AZURE_OPENAI_DEPLOYMENT"] = deployment_name #Wrokarond since azure
        os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_KEY"]

    if provider == "openai":
        embedder_config["api_key"] = os.environ.get("SECRET_OPENAI_API_KEY")
        os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"

    if provider == "ollama":
        if base_url is not None:
            embedder_config["base_url"] = base_url

    elif (
        embedder_config is not None
    ):  # Any other openai compatible e.g. ollama or llama-cpp
        provider = "openai"
        api_key = "NA"
        embedder_config["base_url"] = base_url
        embedder_config["api_key"] = api_key

    # Groq doesn't have an embedder

    # Manager LLM
    manager_model = crew_df["Manager LLM"][0]
    manager_provider = models_df.loc[
        models_df["Model"] == manager_model, "Provider"
    ].values[0]
    manager_temperature = crew_df["t"][0]
    manager_num_ctx = crew_df["num_ctx"][0]
    manager_base_url = models_df.loc[
        models_df["Model"] == manager_model, "base_url"
    ].values[0]
    manager_deployment = models_df.loc[
        models_df["Model"] == manager_model, "Deployment"
    ].values[0]

    if manager_model and manager_provider is not None:
        manager_llm = get_llm(
            model_name=manager_model,
            temperature=manager_temperature,
            num_ctx=manager_num_ctx,
            provider=manager_provider,
            base_url=manager_base_url,
            deployment=manager_deployment,
        )

    verbose = crew_df["Verbose"][0]
    process = (
        Process.hierarchical
        if crew_df["Process"][0] == "hierarchical"
        else Process.sequential
    )

    return Crew(
        agents=created_agents,
        tasks=created_tasks,
        verbose=verbose,
        process=process,
        memory=memory,
        manager_llm=manager_llm,
        embedder={"provider": provider, "config": embedder_config},
    )


if __name__ == "__main__":
    release = f"{AppConfig.name}@{AppConfig.version}"
    if os.environ.get("CREWAI_SHEETS_SENRY") != "False":
        sentry_sdk.init(
            dsn="https://fc662aa323fcc1629fb9ea7713f63137@o4507186870157312.ingest.de.sentry.io/4507186878414928",
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
            release=release,
        )
    helpers.greetings_print()
    args = get_parser()
    log_level = args.loglevel.upper() if hasattr(args, "loglevel") else "ERROR"
    logger.setLevel(log_level)

    load_env(
        args.env_path,
        [
            "OPENAI_API_KEY",
        ],
    )

    if (
        hasattr(args, "sheet_url")
        and args.sheet_url
        and is_valid_google_sheets_url(args.sheet_url)
    ):
        sheet_url = args.sheet_url
    else:
        sheet_url = get_sheet_url_from_user()

    # Define a function to handle termination signals
    terminal_width = console.width
    terminal_width = max(terminal_width, 120)

    # Enter main process
    agents_df, tasks_df, crew_df, models_df, tools_df = Sheets.parse_table(sheet_url)
    helpers.after_read_sheet_print(
        agents_df, tasks_df
    )  # Print overview of agents and tasks

    # Create Agents
    agents_df["crewAIAgent"] = agents_df.apply(
        lambda row: create_agents_from_df(row, models_df=models_df, tools_df=tools_df),
        axis=1,
    )
    created_agents = agents_df["crewAIAgent"].tolist()

    # Create Tasks
    assignment = crew_df["Assignment"][0]
    tasks_df["crewAITask"] = tasks_df.apply(
        lambda row: create_tasks_from_df(row, assignment, created_agents), axis=1
    )
    created_tasks = tasks_df["crewAITask"].tolist()

    # Creating crew
    crew = create_crew(created_agents, created_tasks, crew_df)
    console.print(
        "[green]I've created the crew for you. Let's start working on these tasks! :rocket: [/green]"
    )

    try:
        results = crew.kickoff()
    except Exception as e:
        console.print(
            f"[red]I'm sorry, I couldn't complete the tasks :( Here's the error I encountered: {e}"
        )
        sys.exit(0)

    # Create a table for results
    result_table = Table(show_header=True, header_style="bold magenta")
    result_table.add_column(
        "Here are the results, see you soon =) ", style="green", width=terminal_width
    )

    result_table.add_row(str(results))
    console.print(result_table)
    console.print("[bold green]\n\n")
