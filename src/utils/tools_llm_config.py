import os
import logging
import pandas as pd
from utils.helpers import load_env

logger = logging.getLogger(__name__)
# load_env("../../ENV/.env", ["OPENAI_API_KEY",])


# Class to manage the configuration of the LLM to Tools
class ConfigurationManager:
    def __init__(self, models_df):
        self.df = models_df

    def select(self, target_column, where_column, equals):
        try:
            result = self.df.loc[self.df[where_column] == equals, target_column].iloc[0]
            return result if not pd.isna(result) else None
        except IndexError:
            logger.info(f"No match found for {equals} in {where_column}")
            return None

    def get_model_details(self, model=None, embedding_model=None):
        # Default settings for OpenAI if specific model details are not provided

        details = {
            "model": model if model else "gpt-4-turbo-preview",
            "provider": self.select("Provider", "Model", model) if model else None,
            "deployment_name": (
                self.select("Deployment", "Model", model) if model else None
            ),
            "base_url": self.select("base_url", "Model", model) if model else None,
            "api_key": "NA",
            "embedding_model": (
                embedding_model if embedding_model else "text-embedding-3-small"
            ),
            "provider_embedding": (
                self.select("Provider", "Model", embedding_model)
                if embedding_model
                else None
            ),
            "deployment_name_embedding": (
                self.select("Deployment", "Model", embedding_model)
                if embedding_model
                else None
            ),
            "base_url_embedding": (
                self.select("base_url", "Model", embedding_model)
                if embedding_model
                else None
            ),
            "api_key_embedding": "NA",
        }
        return details

    def build_config(self, model=None, embedding_model=None):
        details = self.get_model_details(model, embedding_model)
        config = {
            "llm": {
                "provider": details["provider"],
                "config": {
                    "model": details["model"],
                    "deployment_name": details["deployment_name"],
                    "base_url": details["base_url"],
                    "temperature": 0.1,
                    "api_key": details["api_key"],
                },
            },
            "embedder": {
                "provider": details["provider_embedding"],
                "config": {
                    "model": details["embedding_model"],
                    "deployment_name": details["deployment_name_embedding"],
                    "base_url": details["base_url_embedding"],
                    "api_base": details["base_url_embedding"],
                    "api_key": details["api_key_embedding"],
                },
            },
        }
        return config


def get_config(model=None, embedding_model=None, models_df=None):
    if not model and not embedding_model:
        return None

    config_manager = ConfigurationManager(models_df)
    config = config_manager.build_config(model=model, embedding_model=embedding_model)

    # Define actions based on provider specific settings.
    provider_actions = {
        "azure_openai": ("base_url", "api_base"),
        "openai_compatible": ("deployment_name"),
        "openai": ("deployment_name", "base_url"),
        "groq": ("deployment_name",),
        "ollama": ("api_base", "api_key"),
    }

    for component_key in ["llm", "embedder"]:
        component_config = config[component_key]["config"]
        provider = config[component_key]["provider"]

        # Provider specific settings:
        # Additional API key handling based on provider specifications
        if provider is None or pd.isna(provider):
            logger.info(f"No provider found for {component_key}")
            config.pop(component_key)
            continue
        if provider == "openai_compatible":
            config[component_key]["config"][
                "api_key"
            ] = "NA"  # TODO: - get api_key from table
        elif (
            provider == "azure_openai"
            and config[component_key]["config"]["api_key"] == "NA"
        ):
            config[component_key]["config"]["api_key"] = os.environ["AZURE_OPENAI_KEY"]
        elif provider == "openai":
            config[component_key]["config"]["api_key"] = os.environ.get(
                "SECRET_OPENAI_API_KEY"
            )
        elif provider == "ollama":
            # Nothin to do
            pass
        else:
            env_var = f"{provider.upper().replace('-', '_')}_API_KEY"
            config[component_key]["config"]["api_key"] = os.environ.get(env_var)

        # Remove certain fields based on provider
        fields_to_remove = provider_actions.get(provider, [])
        for field in fields_to_remove:
            config[component_key]["config"].pop(field, None)

        # Fibnal cleanup - remove keys with None values directly within the dictionary comprehension
        config[component_key]["config"] = {
            k: v for k, v in component_config.items() if v is not None
        }

    return config


# TODO: support all of the providers
# LLM providers suppoerted by langchain: 'openai', 'azure_openai', 'anthropic', 'huggingface', 'cohere', 'together', 'gpt4all', 'ollama', 'jina', 'llama2', 'vertexai', 'google', 'aws_bedrock', 'mistralai', 'vllm', 'groq', 'nvidia'
# Embedder providers supported by langchain: # 'openai', 'gpt4all', 'huggingface', 'vertexai', 'azure_openai', 'google', 'mistralai', 'nvidia'.

# template: Optional[Template] = None,
# prompt: Optional[Template] = None,
# model: Optional[str] = None,
# temperature: float = 0,
# max_tokens: int = 1000,
# top_p: float = 1,
# stream: bool = False,
# deployment_name: Optional[str] = None,
# system_prompt: Optional[str] = None,
# where: dict[str, Any] = None,
# query_type: Optional[str] = None,
# callbacks: Optional[list] = None,
# api_key: Optional[str] = None,
# base_url: Optional[str] = None,
# endpoint: Optional[str] = None,
# model_kwargs: Optional[dict[str, Any]] = None,
# local: Optional[bool] = False,
