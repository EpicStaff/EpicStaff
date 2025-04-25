import logging
logger = logging.getLogger(__name__)
logger.debug(f"Entered {__file__}")
from utils.helpers              import load_env
#load_env("../../ENV/.env", ["OPENAI_API_KEY","OPENAI_BASE_URL"])
from utils.callable_registry    import CallableRegistry

from utils.safe_argment_parser  import parse_arguments
from utils.tools_llm_config     import get_config


import os
import re



class ToolsMapping:
    def __init__(self, tools_df, models_df):
        self.tool_registry = CallableRegistry()     ## Registry of all callables from all modules defined in tools_config.py... 
                                                    ## CallableRegistry itaretes through all allowed tool modules and registers all callables... 
                                                    ##...so that we can add tools by configuation in the tools_df
        self.tools = {}
        self.load_tools(tools_df, models_df)
    
    def load_tools(self, tools_df, models_df):
        """ Load tools from a DataFrame, considering only enabled tools. """
        for idx, row in tools_df.iterrows():
            if not row['On']:
                continue

            tool_name, class_or_func_details = row['Tool'], row['Class']
            if class_or_func_details is None:
                logger.warning(f"No class or function found for tool '{tool_name}'. Tool not created.")
                continue

            # Extract the base function or class name and any indices or arguments
            base_name = re.sub(r"\(.*$", "", class_or_func_details).strip()
            arguments = re.search(r"\((.*)\)", class_or_func_details)
            index_match = re.search(r"\)\[(\d+)\]", class_or_func_details)
            # Get the callable from the registry
            logger.info(f"Loading tool '{tool_name}' with base name '{base_name}' and arguments '{arguments.group(1) if arguments else ''}'.")
            class_or_func = self.tool_registry.get_callable(base_name)
            if class_or_func is None:
                logger.warning(f"No callable found for '{base_name}'. Tool '{tool_name}' not created.")
                continue

            if isinstance(class_or_func, list) and index_match:
                index = int(index_match.group(1))
                class_or_func = class_or_func[index]

            args, kwargs = parse_arguments(arguments.group(1) if arguments else '')
            if callable(class_or_func):
                    if row['Model'] is not None or row['Embedding Model'] is not None:
                        model = row['Model']
                        embedding_model = row['Embedding Model']
                        config = get_config(model=model, embedding_model=embedding_model, models_df=models_df)
                        if config is not None:
                            kwargs['config'] = config
                        else:
                            logger.info(f"'{tool_name}' does not have llm config.")
                
                    logger.info(f"Creating tool '{tool_name}' with allable {class_or_func} and arguments '{args}' and keyword arguments '{kwargs}'.")
                    #look at kwargs if ['congig]['llm'][provider] is "azure_openai" or ['congig]['embedder'][provider] is "azure_openai"  load the enviroment variables
                    # if 'config' in kwargs:
                    #     if 'llm' in kwargs['config']:
                    #         if 'provider' in kwargs['config']['llm']:
                    #             if kwargs['config']['llm']['provider'] == "azure_openai":
                    #                 load_env("../../ENV/.env", ["OPENAI_API_KEY","OPENAI_BASE_URL"])
                    #     if 'embedder' in kwargs['config']:
                    #         if 'provider' in kwargs['config']['embedder']:
                    #             if kwargs['config']['embedder']['provider'] == "azure_openai":
                    #load_env("../../ENV/.env", ["OPENAI_API_KEY","OPENAI_BASE_URL"])
                    #TODO see if more processing is neede here. There is potentia; to change up env variables for each tool and stay in the
                        #also print the config
                    #print(f"ToolsMapping about to add kwargs callable '{tool_name}': {kwargs['config']}")
                    self.tools[tool_name] = class_or_func(*args, **kwargs)
            else:
                logger.error(f"Callable for '{base_name}' is not a function or class constructor.")
        
        for tool_name, tool in self.tools.items():
            if isinstance(tool, list) and tool:
                self.tools[tool_name] = tool[0]

    def get_tools(self):
        """ Retrieve the dictionary of all tools. """
        return self.tools

# TODO
#   def tool_wrapper(tool_func, max_output_size):
#     def wrapped_function(*args, **kwargs):
#         output = tool_func(*args, **kwargs)
#         output_str = str(output)
#         if len(output_str) > max_output_size:
#             return "This tool has exceeded the allowed size limit."
#         else:
#             return output
#     return wrapped_function
# MAX_OUTPUT_SIZE=100 # Maximum size of output allowed for a tool

# def wrap_class(original_class, args, *kwargs):
#     class WrappedClass(original_class):
#         def _run(self):
#             print("extra actions before _run")
#             result = super()._run(*args, **kwargs)
#             print("extra afctions after _run")
#             return result
#     WrappedClass.__name_ = original_class.__name_
#     return WrappedClass


# class ToolsMapping:
#     code_docs_search_tool = wrap_class(CodeDocsSearchTool) # A RAG tool optimized for searching through code documentation and related technical documents.
#     csv_search_tool = CSVSearchTool()  # A RAG tool designed for searching within CSV files, tailored to handle structured data.
#     directory_search_tool = wrap_class(DirectorySearchTool) 


#old def Tools: just in case we need it
#         code_docs_search_tool           = CodeDocsSearchTool(config=config) # A RAG tool optimized for searching through code documentation and related technical documents.
#         csv_search_tool                 = CSVSearchTool(config=config)      # A RAG tool designed for searching within CSV files, tailored to handle structured data.
#         directory_search_tool           = DirectorySearchTool(config=config) # A RAG tool for searching within directories, useful for navigating through file systems.
#         docx_search_tool                = DOCXSearchTool(config=config)      # A RAG tool aimed at searching within DOCX documents, ideal for processing Word files.
#         directory_read_tool             = DirectoryReadTool(config=config)  # Facilitates reading and processing of directory structures and their contents.
#         file_read_tool                  = FileReadTool()        # Enables reading and extracting data from files, supporting various file formats.
#         #github_search_tool = GithubSearchTool(content_types=['code', 'repo', 'pr', 'issue'])
#         # Options: code, repo, pr, issue), 		#A RAG tool for searching within GitHub repositories, useful for code and documentation search.
#         # '#seper_dev_tool'		:seper_dev_tool, # A specialized tool for development purposes, with specific functionalities under development.
#         txt_search_tool                 = TXTSearchTool(config=config)       # A RAG tool focused on searching within text (.txt) files, suitable for unstructured data.
#         json_search_tool                = JSONSearchTool(config=config)      # A RAG tool designed for searching within JSON files, catering to structured data handling.
#         mdx_search_tool                 = MDXSearchTool(config=config)       # A RAG tool tailored for searching within Markdown (MDX) files, useful for documentation.
#         pdf_search_tool                 = PDFSearchTool(config=config)       # A RAG tool aimed at searching within PDF documents, ideal for processing scanned documents.
#         #pg_search_tool= PGSearchTool() #pg_search_tool,        #A RAG tool optimized for searching within PostgreSQL databases, suitable for database queries.
#         rag_tool                        = RagTool(config=config)        # A general-purpose RAG tool capable of handling various data sources and types.
#         scrape_element_from_website_tool= ScrapeElementFromWebsiteTool()# Enables scraping specific elements from websites, useful for targeted data extraction.
#         scrape_website_tool             = ScrapeWebsiteTool()           # Facilitates scraping entire websites, ideal for comprehensive data collection.
#         website_search_tool              = WebsiteSearchTool(config=config)           # A RAG tool for searching website content, optimized for web data extraction.
#         xml_search_tool                 = XMLSearchTool(config=config)               # A RAG tool designed for searching within XML files, suitable for structured data formats.
#         youtube_channel_sarch_tool      = YoutubeChannelSearchTool(config=config)    # A RAG tool for searching within YouTube channels, useful for video content analysis.
#         youtube_video_saarch_tool       = YoutubeVideoSearchTool(config=config)      # A RAG tool aimed at searching within YouTube videos, ideal for video data extraction.
#         # langchain------------------------------------------
#         human_tools                     = load_tools(["human"])[0]      # A Tool that allows the Agents to talk to the n .
#         search                          = DuckDuckGoSearchResults(config=config)     # Duck duck go Search
#         # crewai--sheets-ui 
#         executor                        = CLITool.execute_cli_command   # executor_tool,  			#interpreter CLI command
#         folder_tool                     = FolderTool.list_files         # Lists all files into > a file so context is not spammed. Recursive option. 
#         file_tool                       = FileTool()        # Manages files with various actions including reading, appending text, editing lines, creating files, counting lines, and retrieving specific lines. xx
#         bs_code_tool                    = BSharpCodeTool()
        