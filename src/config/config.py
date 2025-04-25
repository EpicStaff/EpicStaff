
import   logging
logger = logging.getLogger(__name__)
from     utils.import_package_modules import import_package_modules
from     langchain.agents.load_tools  import load_tools
import   langchain_community.utilities    as lcutils
import   langchain_community.tools        as lctools  
import   crewai_tools
import   tools 

class AppConfig:
    version = "0.5.3"
    name= "crewai-sheets-ui"
    template_sheet_url = "https://docs.google.com/spreadsheets/d/1J975Flh82qPjiyUmDE_oKQ2l4iycUq6B3457G5kCD18/copy"
    pass

class ToolsConfig:
    # DEFINE MODULES FROM WHICH TO IMPORT TOOLS
    # [package, "alias",]
    modules_list        = [(tools, "tools"),]
    callables_list      = [load_tools,]                                 # Define specific callables to register e.g. in case they are not callable without specific parameters  
    integration_dict    = {}                                            # Dictionary to which public module members are added   
    import_package_modules(crewai_tools, modules_list, integration_dict)                  # Add to modules listAdd all tool modules from crewai_tools
    import_package_modules(lctools,      modules_list, integration_dict, recursive = True) 
    import_package_modules(lcutils,      modules_list, integration_dict, recursive = True)    # Add to modules list all tool modules from langchain_community.tools 
    pass                                                                

class OllamaConfig:
    #patch_stop_words = True
    #patch_num_ctx = True
    stop_words = []     

class HuggingFaceConfig:
    stop_sequences = ['\nObservation'] 

class GroqConfig:
    max_tokens = 1000
    stop = []
    def get_rate_limit(model_name:str):
        model_rate_dict = {
            'llama2-70b-4096'   :15000,
            'mixtral-8x7b-32768':9000,
            'gemma-7b-it'       :15000,
            'llama3-70b-8192'   :5000,
            'llama3-8b-8192'	:12000,
        }
        if model_name in model_rate_dict:
            return model_rate_dict[model_name]
        else:
            return 5000
    