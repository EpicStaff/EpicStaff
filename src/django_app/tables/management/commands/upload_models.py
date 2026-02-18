from pathlib import Path
from django.core.management.base import BaseCommand

from tables.models import (
    Tool,
    ToolConfigField,
    EmbeddingModel,
    LLMModel,
    Provider,
    RealtimeModel,
    RealtimeTranscriptionModel,
    DefaultRealtimeAgentConfig,
)
from tables.models.crew_models import (
    Agent,
    DefaultAgentConfig,
    DefaultCrewConfig,
    DefaultToolConfig,
)
from tables.models.embedding_models import DefaultEmbeddingConfig
from tables.models.llm_models import DefaultLLMConfig
from tables.management.commands.helpers import load_json_from_file
from tables.management.commands.upload_tools import upload_tools
from tables.models.tag_models import LLMModelTag, EmbeddingModelTag


class Command(BaseCommand):
    help = "Upload predefined models to database"

    def handle(self, *args, **kwargs):
        upload_tags()
        upload_providers()
        upload_llm_models()
        upload_realtime_agent_models()
        upload_realtime_transcription_models()
        upload_embedding_models()
        upload_tools()
        upload_default_llm_config()
        upload_default_embedding_config()
        upload_default_realtime_agent_config()
        upload_default_agent_config()
        upload_default_crew_config()
        upload_default_tool_config()
        upload_legacy_tools()
        upload_realtime_agents()


LLM_MODELS_JSON = "llm_models.json"
EMBEDDING_MODELS_JSON = "embedding_models.json"
REALTIME_MODELS_JSON = "realtime_models.json"
TRANSCRIPTION_MODELS_JSON = "transcription_models.json"

MODEL_JSON_FILES = [
    LLM_MODELS_JSON,
    EMBEDDING_MODELS_JSON,
    REALTIME_MODELS_JSON,
    TRANSCRIPTION_MODELS_JSON,
]
PREDEFINED_TAGS = {
    "llm_model": ["recommended"],
    "embedding_model": ["recommended"],
}

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROVIDER_MODELS_DIR = BASE_DIR / "provider_models"


def upload_tags():

    llm_tag_names = PREDEFINED_TAGS["llm_model"]

    for tag in llm_tag_names:
        LLMModelTag.objects.update_or_create(name=tag, defaults={"predefined": True})

    LLMModelTag.objects.filter(predefined=True).exclude(name__in=llm_tag_names).delete()

    embed_tag_names = PREDEFINED_TAGS["embedding_model"]

    for tag in embed_tag_names:
        EmbeddingModelTag.objects.update_or_create(
            name=tag, defaults={"predefined": True}
        )

    EmbeddingModelTag.objects.filter(predefined=True).exclude(
        name__in=embed_tag_names
    ).delete()


def get_all_providers_from_files():
    all_providers = set()
    for path in MODEL_JSON_FILES:
        js_path = PROVIDER_MODELS_DIR / path
        data = load_json_from_file(js_path)
        all_providers.update(data.keys())
    return all_providers


def upload_providers():
    current_provider_names = get_all_providers_from_files()
    for name in current_provider_names:
        Provider.objects.get_or_create(name=name)

    Provider.objects.exclude(name__in=current_provider_names).delete()


def upload_llm_models():
    path = PROVIDER_MODELS_DIR / LLM_MODELS_JSON
    models_by_provider = load_json_from_file(path)

    recommended_tag, _ = LLMModelTag.objects.get_or_create(
        name="recommended", defaults={"predefined": True}
    )

    active_ids = []

    for provider_name, model_list in models_by_provider.items():
        provider, _ = Provider.objects.get_or_create(name=provider_name)

        for model_data in model_list:
            model_name = model_data["name"]
            is_recommended = model_data["recommended"]

            llm_model, created = LLMModel.objects.update_or_create(
                llm_provider=provider,
                name=model_name,
                defaults={
                    "predefined": True,
                },
            )

            if is_recommended:
                llm_model.tags.add(recommended_tag)
            else:
                llm_model.tags.remove(recommended_tag)

            active_ids.append(llm_model.pk)

    LLMModel.objects.filter(predefined=True, is_custom=False).exclude(
        pk__in=active_ids
    ).delete()


def upload_realtime_agent_models():
    path = PROVIDER_MODELS_DIR / REALTIME_MODELS_JSON
    models_by_provider = load_json_from_file(path)
    current_model_tuples = set()

    for provider_name, model_names in models_by_provider.items():
        provider, _ = Provider.objects.get_or_create(name=provider_name)
        for model_name in model_names:
            current_model_tuples.add((provider.pk, model_name))
            RealtimeModel.objects.get_or_create(name=model_name, provider=provider)

    RealtimeModel.objects.filter(is_custom=False).exclude(
        provider_id__in=[pid for pid, _ in current_model_tuples],
        name__in=[name for _, name in current_model_tuples],
    ).delete()


def upload_realtime_transcription_models():
    path = PROVIDER_MODELS_DIR / TRANSCRIPTION_MODELS_JSON
    models_by_provider = load_json_from_file(path)
    current_model_tuples = set()

    for provider_name, model_names in models_by_provider.items():
        provider, _ = Provider.objects.get_or_create(name=provider_name)
        for model_name in model_names:
            current_model_tuples.add((provider.pk, model_name))
            RealtimeTranscriptionModel.objects.get_or_create(
                name=model_name, provider=provider
            )

    RealtimeTranscriptionModel.objects.filter(is_custom=False).exclude(
        provider_id__in=[pid for pid, _ in current_model_tuples],
        name__in=[name for _, name in current_model_tuples],
    ).delete()


def upload_embedding_models():
    path = PROVIDER_MODELS_DIR / EMBEDDING_MODELS_JSON
    models_by_provider = load_json_from_file(path)

    recommended_tag, _ = EmbeddingModelTag.objects.get_or_create(
        name="recommended", defaults={"predefined": True}
    )

    active_ids = []

    for provider_name, model_list in models_by_provider.items():
        provider, _ = Provider.objects.get_or_create(name=provider_name)

        for model_data in model_list:
            model_name = model_data["name"]
            is_recommended = model_data["recommended"]

            embedding_model, created = EmbeddingModel.objects.update_or_create(
                embedding_provider=provider,
                name=model_name,
                defaults={
                    "predefined": True,
                },
            )

            if is_recommended:
                embedding_model.tags.add(recommended_tag)
            else:
                embedding_model.tags.remove(recommended_tag)

            active_ids.append(embedding_model.pk)

    EmbeddingModel.objects.filter(predefined=True, is_custom=False).exclude(
        pk__in=active_ids
    ).delete()


def upload_realtime_agents():
    from tables.models.realtime_models import RealtimeAgent

    agent_list = Agent.objects.all()
    for agent in agent_list:
        RealtimeAgent.objects.get_or_create(
            agent=agent,
            defaults={
                "wake_word": None,
                "stop_prompt": None,
                "language": None,
            },
        )

    pass


def upload_default_llm_config():
    DefaultLLMConfig.objects.filter().delete()
    DefaultLLMConfig.objects.create(id=1)


def upload_default_embedding_config():
    DefaultEmbeddingConfig.objects.filter().delete()
    DefaultEmbeddingConfig.objects.create(id=1)


def upload_default_agent_config():
    DefaultAgentConfig.objects.all().delete()
    DefaultAgentConfig.objects.create(id=1)


def upload_default_realtime_agent_config():
    DefaultRealtimeAgentConfig.objects.all().delete()
    DefaultRealtimeAgentConfig.objects.create(id=1)


def upload_default_crew_config():
    DefaultCrewConfig.objects.all().delete()
    DefaultCrewConfig.objects.create(id=1)


def upload_default_tool_config():
    DefaultToolConfig.objects.all().delete()
    DefaultToolConfig.objects.create(id=1)


def upload_legacy_tools():
    tools = [
        {
            "name": "Wikipedia Tool",
            "name_alias": "wikipedia",
            "description": "Tool for Wikipedia searching",
        },
        {
            "name": "DuckDuckGo Search",
            "name_alias": "ddg_search",
            "description": "Tool for DuckDuckGo searching",
        },
        {
            "name": "Gmail Draft Creator",
            "name_alias": "create_draft",
            "description": "Tool for creating Gmail drafts",
            "enabled": False,
        },
        {
            "name": "Code Docs Search Tool",
            "name_alias": "code_docs_search",
            "description": "Tool for searching through code documentation",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "docs_url",
                    "description": "Specifies the URL of the code documentation to be searched.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "CSV Search Tool",
            "name_alias": "csv_search",
            "description": "Tool for searching within CSV files",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "csv",
                    "description": "The path to the CSV file you want to search. \
                        This is a mandatory argument if the tool was initialized without a specific CSV file; \
                        otherwise, it is optional.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "DALL-E Tool",
            "name_alias": "dalle",
            "description": "Tool for generating images with DALL-E",
            "fields": [
                {
                    "name": "model",
                    "description": "DALL-E model. Default = dall-e-3",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "size",
                    "description": "Picture size. Default = 1024x1024",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "quality",
                    "description": "Picture quality. Default = standard",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "n",
                    "description": "Number of pictures. Default = 1",
                    "data_type": ToolConfigField.FieldType.INTEGER,
                    "required": False,
                },
            ],
        },
        {
            "name": "Directory Read Tool",
            "name_alias": "directory_read",
            "description": "Tool for reading files in directories",
            "fields": [
                {
                    "name": "directory",
                    "description": "An argument that specifies the path to the directory whose contents you wish to list. \
                        It accepts both absolute and relative paths, guiding the tool to the desired directory for content listing.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "Directory Search Tool",
            "name_alias": "directory_search",
            "description": "Tool for searching within directories",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "directory",
                    "description": "A string argument that specifies the search directory. \
                        This is optional during initialization but required for searches if not set initially.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "DOCX Search Tool",
            "name_alias": "docx_search",
            "description": "Tool for searching within DOCX files",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "docx",
                    "description": "An argument that specifies the path to the DOCX file you want to search. \
                        If not provided during initialization, the tool allows for later specification of \
                            any DOCX file’s content path for searching.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "EXA Search Tool",
            "name_alias": "exa_search",
            "description": "Tool for EXA data searching",
            "enabled": False,
        },
        {
            "name": "File Read Tool",
            "name_alias": "file_read",
            "description": "Tool for reading files",
            "fields": [
                {
                    "name": "file_path",
                    "description": "The path to the file you want to read. \
                        It accepts both absolute and relative paths. \
                        Ensure the file exists and you have the necessary permissions to access it.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "File Writer Tool",
            "name_alias": "file_writer",
            "description": "Tool for writing files",
        },
        {
            "name": "GitHub Search Tool",
            "name_alias": "github_search",
            "description": "Tool for searching GitHub repositories",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "github_repo",
                    "description": "The URL of the GitHub repository where the search will be conducted. \
                        \nThis is a mandatory field and specifies the target repository for your search.\
                            Example: https://github.com/example/repo",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": True,
                },
                {
                    "name": "gh_token",
                    "description": "Your GitHub Personal Access Token (PAT) required for authentication.\
                        \nYou can create one in your GitHub account settings under Developer Settings > Personal Access Tokens.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": True,
                },
                {
                    "name": "content_types",
                    "description": "Specifies the types of content to include in your search. \
                        \nExample: ['code', 'repo', 'pr', 'issue']\
                        \nYou must provide a list of content types from the following options: \
                            \ncode for searching within the code, \
                            \nrepo for searching within the repository’s general information, \
                            \npr for searching within pull requests, and \
                            \nissue for searching within issues. \
                        This field is mandatory and allows tailoring the search to specific content types within the GitHub repository.",
                    "data_type": ToolConfigField.FieldType.ANY,
                    "required": True,
                },
            ],
        },
        {
            "name": "Serper.dev Tool",
            "name_alias": "serper_dev",
            "description": "Tool for Serper.dev search",
            "fields": [
                {
                    "name": "search_url",
                    "description": "The URL endpoint for the search API. \
                        (Default is https://google.serper.dev/search)",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "country",
                    "description": "Specify the country for the search results.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "location",
                    "description": "Specify the location for the search results.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "locale",
                    "description": "Specify the locale for the search results.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "n_results",
                    "description": "Number of search results to return. Default is 10.",
                    "data_type": ToolConfigField.FieldType.INTEGER,
                    "required": False,
                },
            ],
        },
        {
            "name": "JSON Search Tool",
            "name_alias": "json_search",
            "description": "Tool for searching JSON files",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "json_path",
                    "description": "Specifies the path to the JSON file to be searched. \
                        This argument is not required if the tool is initialized for a general search. \
                        When provided, it confines the search to the specified JSON file.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "MDX Search Tool",
            "name_alias": "mdx_search",
            "description": "Tool for searching MDX files",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "mdx",
                    "description": "Specifies the MDX file path for the search. It can be provided during initialization.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "MySQL Search Tool",
            "name_alias": "my_sql_search",
            "description": "Tool for searching MySQL databases",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "db_uri",
                    "description": "A string representing the URI of the MySQL database to be queried. \
                        This argument is mandatory and must include the necessary authentication details \
                            and the location of the database.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": True,
                },
                {
                    "name": "table_name",
                    "description": "A string specifying the name of the table within the database on which the semantic search will be performed. This argument is mandatory.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": True,
                },
            ],
        },
        {
            "name": "NL2SQL Tool",
            "name_alias": "nl2sql",
            "description": "Tool for natural language to SQL queries",
            "enabled": False,
            "fields": [
                {
                    "name": "db_uri",
                    "description": "The URI of the database to connect to.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": True,
                },
                {
                    "name": "tables",
                    "description": "List of database tables",
                    "data_type": ToolConfigField.FieldType.ANY,
                    "required": False,
                },
                {
                    "name": "columns",
                    "description": "dict of database columns",
                    "data_type": ToolConfigField.FieldType.ANY,
                    "required": False,
                },
            ],
        },
        {
            "name": "PDF Search Tool",
            "name_alias": "pdf_search",
            "description": "Tool for searching PDF documents",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "pdf",
                    "description": "The PDF path for the search. \
                        Can be provided at initialization or within run by agent. \
                        If provided at initialization, the tool confines its search to the specified document.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "PostgreSQL Search Tool",
            "name_alias": "pg_search",
            "description": "Tool for searching PostgreSQL databases",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "db_uri",
                    "description": "A string representing the URI of the PostgreSQL database to be queried. \
                        This argument will be mandatory and must include the necessary authentication details \
                            and the location of the database.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": True,
                },
                {
                    "name": "table_name",
                    "description": "A string specifying the name of the table within the database \
                        on which the semantic search will be performed.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": True,
                },
            ],
        },
        {
            "name": "Scrape Website Tool",
            "name_alias": "scrape_website",
            "description": "Tool for scraping websites",
            "fields": [
                {
                    "name": "website_url",
                    "description": "Website URL.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": True,
                },
            ],
        },
        {
            "name": "Selenium Scraping Tool",
            "name_alias": "selenium_scraping",
            "description": "Tool for scraping websites using Selenium",
            "enabled": False,
            "fields": [
                {
                    "name": "website_url",
                    "description": "Specifies the URL of the website from which content is to be scraped.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "css_element",
                    "description": "The CSS selector for a specific element to target on the website, \
                        enabling focused scraping of a particular part of a webpage.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "cookie",
                    "description": "A dictionary containing cookie information, \
                        useful for simulating a logged-in session to access restricted content.",
                    "data_type": ToolConfigField.FieldType.ANY,
                    "required": False,
                },
                {
                    "name": "wait_time",
                    "description": "Specifies the delay (in seconds) before scraping, \
                        allowing the website and any dynamic content to fully load.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "TXT Search Tool",
            "name_alias": "txt_search",
            "description": "Tool for searching TXT files",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "txt",
                    "description": "The path to the text file you want to search. \
                        This argument is only required if the tool was not initialized with a specific text file; \
                        otherwise, the search will be conducted within the initially provided text file.\
                        \nExample: path/to/text/file.txt",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "Vision Tool",
            "name_alias": "vision",
            "description": "Tool for image analysis",
        },
        {
            "name": "Website Search Tool",
            "name_alias": "website_search",
            "description": "Tool for searching websites",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "website",
                    "description": "An optional argument intended to specify the website URL for focused searches. \
                        This argument is designed to enhance the tool’s flexibility by allowing targeted searches when necessary.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "XML Search Tool",
            "name_alias": "xml_search",
            "description": "Tool for searching XML files",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "xml",
                    "description": "This is the path to the XML file you wish to search. \
                        It is an optional parameter during the tool’s initialization \
                        but must be provided either at initialization or as part of the run method’s arguments to execute a search.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": True,
                },
            ],
        },
        {
            "name": "YouTube Channel Search Tool",
            "name_alias": "youtube_channel_search",
            "description": "Tool for searching YouTube channels",
            "enabled": False,
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "youtube_channel_handle",
                    "description": "A mandatory string representing the Youtube channel handle. \
                        This parameter is crucial for initializing the tool to specify the channel you want to search within. \
                        The tool is designed to only search within the content of the provided channel handle.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "YouTube Video Search Tool",
            "name_alias": "youtube_video_search",
            "description": "Tool for searching YouTube videos",
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
                {
                    "name": "youtube_video_url",
                    "description": "An optional argument at initialization but required if targeting a specific Youtube video. \
                        It specifies the Youtube video URL path you want to search within.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "Firecrawl Crawl Website Tool",
            "name_alias": "firecrawl_crawl_website",
            "description": "Crawl and convert websites into clean markdown or structured data.",
            "fields": [
                {
                    "name": "api_key",
                    "description": "Specifies Firecrawl API key. \
                        Defaults is the FIRECRAWL_API_KEY environment variable.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "Firecrawl Scrape Website Tool",
            "name_alias": "firecrawl_scrape_website",
            "description": "Tool for scraping websites with Firecrawl",
            "fields": [
                {
                    "name": "api_key",
                    "description": "Specifies Firecrawl API key. \
                        Defaults is the FIRECRAWL_API_KEY environment variable.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "Firecrawl Search Tool",
            "name_alias": "firecrawl_search",
            "description": "Tool for searching with Firecrawl",
            "fields": [
                {
                    "name": "api_key",
                    "description": "Specifies Firecrawl API key. \
                        Defaults is the FIRECRAWL_API_KEY environment variable.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "Spider Scraper",
            "name_alias": "spider_scraper",
            "description": "Tool for web scraping with Spider",
            "fields": [
                {
                    "name": "api_key",
                    "description": "Specifies Spider API key. \
                        If not specified, it looks for SPIDER_API_KEY in environment variables.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
            ],
        },
        {
            "name": "Composio Tool",
            "name_alias": "composio",
            "description": "Tool for document composition with Composio",
            "enabled": False,
        },
        {
            "name": "Browserbase Load Tool",
            "name_alias": "browserbase_load",
            "description": "Tool for browser-based loading with Browserbase",
            "fields": [
                {
                    "name": "api_key",
                    "description": "Browserbase API key.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "project_id",
                    "description": "Browserbase Project ID.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "text_content",
                    "description": "Retrieve only text content. Default is False.",
                    "data_type": ToolConfigField.FieldType.BOOLEAN,
                    "required": False,
                },
                {
                    "name": "session_id",
                    "description": "Provide an existing Session ID.",
                    "data_type": ToolConfigField.FieldType.STRING,
                    "required": False,
                },
                {
                    "name": "proxy",
                    "description": "Enable/Disable Proxies. Default is False.",
                    "data_type": ToolConfigField.FieldType.BOOLEAN,
                    "required": False,
                },
            ],
        },
        {
            "name": "Wolfram Alpha Tool",
            "name_alias": "wolfram_alpha",
            "description": "Tool for querying Wolfram Alpha",
        },
        {
            "name": "Custom Create Draft Tool",
            "name_alias": "custom_create_draft",
            "description": "Tool for creating custom drafts",
            "enabled": False,
        },
        {
            "name": "Custom File Append Tool",
            "name_alias": "custom_file_append",
            "description": "Tool for appending content to files",
        },
        {
            "name": "Custom File Line Count Tool",
            "name_alias": "custom_file_count_lines",
            "description": "Tool for counting lines in a file",
        },
        {
            "name": "Custom File Create Tool",
            "name_alias": "custom_create_file",
            "description": "Tool for creating new files",
        },
        {
            "name": "Custom File Edit Tool",
            "name_alias": "custom_edit_file",
            "description": "Tool for editing files",
        },
        {
            "name": "Custom File Line Read Tool",
            "name_alias": "custom_line_read_file",
            "description": "Tool for reading specific lines from a file",
        },
        {
            "name": "Custom Folder Tool",
            "name_alias": "custom_folder_tool",
            "description": "Tool for managing folders",
        },
        {
            "name": "Custom CLI Tool",
            "name_alias": "custom_cli",
            "description": "Tool for executing custom CLI commands",
            "fields": [
                {
                    "name": "llm_config",
                    "description": "Field for LLM Configuration",
                    "data_type": ToolConfigField.FieldType.LLM_CONFIG,
                    "required": True,
                },
                {
                    "name": "embedding_config",
                    "description": "Field for Embedding Configuration",
                    "data_type": ToolConfigField.FieldType.EMBEDDING_CONFIG,
                    "required": True,
                },
            ],
        },
    ]

    for tool_data in tools:
        tool, created = Tool.objects.get_or_create(
            name_alias=tool_data["name_alias"],
            defaults={
                "name": tool_data["name"],
                "description": tool_data["description"],
                "enabled": tool_data.get("enabled", True),
            },
        )

        if not created:  # If existed
            tool.name = tool_data["name"]
            tool.description = tool_data["description"]
            tool.save(update_fields=["name", "description"])

        field_list = tool_data.get("fields", list())

        # removing fields that not in schema
        ToolConfigField.objects.filter(tool=tool).exclude(
            name__in={field["name"] for field in field_list}
        ).delete()

        for field in field_list:
            ToolConfigField.objects.update_or_create(
                tool=tool,
                name=field["name"],
                defaults={
                    "description": field["description"],
                    "data_type": field["data_type"],
                    "required": field["required"],
                },
            )
