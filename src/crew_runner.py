import os
import sys
from textwrap import dedent
from crewai import Crew, Task, Agent, Process

import pandas as pd

from utils.agent_crew_llm import get_llm
from utils.tools_mapping import ToolsMapping
from utils.import_tool_data_builder import ImportToolDataBuilder
from docker_tools.langchain.import_tool import import_tool


def create_agents_from_df(row, models_df=None, tools_df=None):

    def get_agent_tools(tools_string):
        tool_aliases = [tool.strip() for tool in tools_string.split(",")]
        itdb = ImportToolDataBuilder(force_build=True)
        itdb_list = []
        for alias in tool_aliases:
            itdb_list.append(itdb.get_import_class_data(alias))
        
        proxies = []
        for it in itdb_list:
            proxy_class = import_tool(it)
            proxies.append(proxy_class())

        return proxies
        
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


def create_crew(created_agents, created_tasks, crew_df, models_df):
    # Embedding model (Memory)
    memory = crew_df["Memory"][0]
    embedding_model = crew_df["Embedding model"].get(0)

    if embedding_model is None or pd.isna(embedding_model):
        # logger.info(
        #     "No embedding model for crew specified in the sheet. Turning off memory."
        # )
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
        elif provider == "openai":
            embedder_config["api_key"] = os.environ.get("SECRET_OPENAI_API_KEY")
            os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
        elif provider == "ollama":
            if base_url is not None:
                embedder_config["base_url"] = base_url
        else:  # Any other openai compatible e.g. ollama or llama-cpp
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
