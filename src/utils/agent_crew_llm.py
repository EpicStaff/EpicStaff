import logging
logger = logging.getLogger(__name__)

#from langchain_community.llms  import Ollama
from utils.ollama_loader  import OllamaLoader
import config.config as config
from langchain_community.llms import HuggingFaceEndpoint
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI, AzureOpenAI, AzureChatOpenAI
#from langchain_groq import ChatGroq
from utils.groq import TokenThrottledChatGroq
from utils.helpers import load_env
from ollama  import pull, list
import os
from tqdm import tqdm

def get_llm(model_name= None, temperature=0.7, num_ctx = None, provider  = None, base_url = None, 
            deployment=None,  **kwargs):
    """
    Retrieves an appropriate LLM based on specified parameters, including provider and model specifics.
    The function checks if the specific model or a base model already exists in Ollama and does not pull
    it if it does; otherwise, it attempts to pull the model.

    Parameters:
    - model_name (str): The name of the model to load, potentially including a version.
    - temperature (float): The temperature setting for the model. Affects the randomness of the responses.
    - num_ctx (int): Reserved for future use. Currently not used.
    - provider (str): The provider of the model ('openai', 'azure_openai', 'anthropic', etc.).
    - base_url (str): Base URL for the API requests, applicable for some providers like OpenAI and Azure.
    - deployment (str): Deployment specifics, primarily used for Azure.
    - progress (object): Progress tracking object, usually a UI element to indicate progress to the user.
    - llm_task (object): Task identifier for updating progress status.
    #TODO: - **kwargs: Additional keyword arguments that may be required by specific providers. Pass 

    Returns:
    - An instance of the LLM based on the provider, configured with the given settings.

    Each provider uses different parameters:
    - 'anthropic': Uses 'model_name' and 'temperature'.
    - 'azure_openai': Uses 'deployment', 'base_url', 'temperature'.
    - 'openai': Uses 'model_name', 'temperature', 'base_url'.
    - 'huggingface': Uses 'model_name' and might use API token configurations internally.
    """

    #load_env("../../ENV/.env", ["OPENAI_API_KEY","OPENAI_BASE_URL"])

    #Anthropic. 
    if provider.lower() == "anthropic":
        logger.info(f"Using Anthropic model '{model_name}' with temperature {temperature}.")
        try:  
            return ChatAnthropic(
                model_name  = model_name,                            #use model_name as endpoint
                api_key     = os.environ.get("ANTHROPIC_API_KEY"),
                temperature = temperature,
                #stop = ["\nObservation"] 
            )
        except Exception as e:
            print(f"Hey, I've failed to configure Anthropic model '{model_name}'. Could you check if the API KEY is set? :\n{e}")
            return None
    
    #Azure OpenaI   
    if provider.lower() == "azure_openai":
        logger.info(f"Trying {provider} model '{model_name}' with temperature {temperature}," \
                f"deployment {deployment}, azure_andpoint {base_url}, AZURE_OPENAI_KEY, AZURE_OPENAI_VERSION.")
        try:
            return AzureChatOpenAI(
                azure_deployment = deployment,                            
                azure_endpoint   = base_url,                           
                api_key          = os.environ.get("AZURE_OPENAI_KEY"),
                api_version=os.environ.get("AZURE_OPENAI_VERSION"),
                temperature=temperature
                )
        except Exception as e:
            print(f"Hey, I've failed to configure Azure OpenAI model '{model_name}'. Could you check if the API KEY is set? :\n{e}")
            return None
        
    #OpenAI
    if provider.lower() == "openai":
        logger.info(f"Trying {provider} model '{model_name}' with temperature {temperature}," 
                f"base_url {base_url}, api_key via env.")
        try:
            os.environ['OPENAI_API_KEY'] = os.environ.get("SECRET_OPENAI_API_KEY")
            if base_url is None: 
                base_url= "https://api.openai.com/v1"                      
            return ChatOpenAI(
                model           = model_name, 
                temperature     = temperature,
                base_url        = base_url,
                )
        except Exception as e:
            print(f"Hey, I've failed to configure OpenAI model '{model_name}'. Could you check if the API KEY is set? :\n{e}")
            return None
    
    #OpenAI comatipble via /v1 protocol LM Studio, llamacpp, ollama, etc
    if provider.lower() == "openai_compatible":
        logger.info(f"Trying {provider} model '{model_name}' with temperature {temperature}, base_url {base_url}")
        try:
            return ChatOpenAI(
                model           = model_name, 
                temperature     = temperature,
                base_url        = base_url,
                openai_api_key  = 'NA' #TODO suppoert for local llm API key's
                )
        except Exception as e:
            print(f"Hey, I've failed to configure OpenAI model '{model_name}'. Could you check if the API KEY is set? :\n{e}")
            return None
    
    #Groq
    if provider.lower() == "groq":
        max_tokens = config.GroqConfig.max_tokens
        rate_limit = config.GroqConfig.get_rate_limit(model_name)
        logger.info(f"Trying {provider} model '{model_name}' with temperature {temperature}") 
        try:
            return TokenThrottledChatGroq( #custom class to throttle tokens
                rate_limit       = rate_limit,
                model            = model_name, 
                temperature      = temperature,
                max_tokens       = max_tokens,
                
                #base_url        = base_url,
                )
        except Exception as e:
            print(f"Hey, I've failed to configure Groq model '{model_name}'. Could you check if the API KEY is set?\n{e}")
            return None
        
    #huggingface
    if provider.lower() == "huggingface":   
        logger.info(f"Trying {provider} repo_id '{model_name}' with hugingfacehub_api_token. via env")       
        try:
            return HuggingFaceEndpoint(
                repo_id=model_name,
                huggingfacehub_api_token=os.environ.get("HUGGINGFACEHUB_API_TOKEN"),
                stop_sequences = config.HuggingFaceConfig.stop_sequences,
                #model_kwargs = {"max_length": 10000}                #need to read documentation
                #max_new_tokens = 1000,                              #need to read documentation
                #max_length = 1000,                                  #need to read documentation
                #task="text-generation",
            )
        except Exception as e:
            print(f"Hey, I've failed to configure HuggingFace model '{model_name}'. Could you check if the API KEY is set? \n{e}")  
            return None
    #Ollama
    if provider.lower() == "ollama":
        logger.info(f"Trying {provider} model '{model_name}' with num_ctx {num_ctx}.")
        try:
           return OllamaLoader.load(
                model_name  = model_name, 
                temperature = temperature, 
                num_ctx = num_ctx, 
                base_url = base_url,
                stop = config.OllamaConfig.stop_words #don't pass - crewai aleady does this itself.
            )
        except Exception as e:
            print(f"Hey, I've failed to configure Ollama model '{model_name}':\n{e}")
            return None

    logger.error(f"Provider '{provider}' not recognized. Please use one of the supported providers: 'anthropic', 'azure_openai', 'openai', 'huggingface', 'ollama'.")   
    return None





    