import logging
import socket
from langchain_community.llms.ollama import Ollama
from rich.progress import Progress
from ollama import list, pull, Client

logger = logging.getLogger(__name__)


def running_in_docker():
    try:
        # This will try to resolve the special Docker DNS name for the host.
        host_ip = socket.gethostbyname("host.docker.internal")
        # print(f"Hey, it looks like I'm running inside a docker container.")
        # print(f"There was no base_url set for this model, so I'll assume it's {host_ip}:11434.")
        return True if host_ip else False
    except socket.gaierror:
        # The name is not known, which likely means not running inside Docker
        return False


class OllamaLoader:

    def handle_progress_updates(progress_update, progress, llm_task):
        """
        Handles progress updates during model download and initialization.
        """
        if "total" in progress_update:
            progress.update(llm_task, total=progress_update["total"])
        if "completed" in progress_update:
            current_completed = progress.tasks[llm_task].completed
            new_advance = progress_update["completed"] - current_completed
            progress.advance(llm_task, advance=new_advance)
        if "status" in progress_update:
            progress.update(
                llm_task,
                advance=0,
                description=f"[cyan]LLM: {progress_update['status']}",
            )

    def load(model_name=None, temperature=0.8, num_ctx=None, base_url=None, **kwargs):
        """
        Loads the specified model from Ollama, or pulls it if it does not exist.
        """

        if running_in_docker():
            if base_url is None:
                base_url = "http://host.docker.internal:11434"  # TODO: Move to config
            ollama_client = Client(host=base_url)
        else:
            ollama_client = None

        parts = model_name.split(":")
        if len(parts) < 2:
            print(
                f"Ollama models usually have a version, like {model_name}:instruct, or {model_name}:latest. That's ok, I'll take a guess and use the latest version."
            )

        model_list = (
            list()["models"]
            if ollama_client is None
            else ollama_client.list()["models"]
        )

        for model in model_list:
            if model["name"] == model_name:
                logger.info(f"Model '{model_name}' found in Ollama, loading directly.")

                if base_url is not None:
                    return Ollama(
                        model=model_name,
                        temperature=temperature,
                        num_ctx=num_ctx,
                        base_url=base_url,
                    )
                else:
                    return Ollama(
                        model=model_name, temperature=temperature, num_ctx=num_ctx
                    )

        logger.info(f"No local matching model found for '{model_name}' in Ollama.")
        print(
            f"I'm trying to download '{model_name}' from Ollama... This may take a while. Why not grab a cup of coffee..."
        )

        progress = Progress(expand=True, transient=True)
        with progress:
            llm_task = progress.add_task(f"Downloading '{model_name}'", total=1000)
            if ollama_client is None:
                for response in pull(model=model_name, stream=True):
                    OllamaLoader.handle_progress_updates(response, progress, llm_task)
            else:
                for response in ollama_client.pull(model=model_name, stream=True):
                    OllamaLoader.handle_progress_updates(response, progress, llm_task)

        logger.info(f"Model '{model_name}' successfully pulled")
        logger.info(f"Attempting to load model '{model_name}'...")
        print(f"Model '{model_name}' successfully pulled. Now I'm trying to load it...")
        if base_url is not None:
            return Ollama(
                model=model_name,
                temperature=temperature,
                num_ctx=num_ctx,
                base_url=base_url,
            )
        else:
            return Ollama(model=model_name, temperature=temperature, num_ctx=num_ctx)


# def load_model(self):
#         """Selects the appropriate method to load the model based on the model name.
#         If the model is not found in Ollama, it attempts to pull it with streaming enabled.
#         Finds the best matching model from the list of existing models based on a structured naming convention.
#         Models can have different suffixes and versions, and this method tries to find the most appropriate match
#         based on predefined rules.
#             #exact match1  <model>_crewai_<num_ctx>:<version>  == <existing_model>_crewai_num_ctx:<version>
#             #exact match2  <model>_crewai_<num_ctx>            == <existing_model>_crewai_num_ctx:latest
#                 -->just lod the model
#             #crew match1   <model>_crew:<version>            == <existing_model>_crew:<version>
#             #crew match2   <model>_crew                      == <existing_model>_crew:latest
#             #model match   <model>:<version>                 == <existing_model>:<version>
#             #model match   <model>                           == <existing_model>:latest
#                 -->meed to patch modelfile first
#         """
#         if self.model_name is None:
#             logger.error("Model name is None, cannot load model.")
#             return None
#         version = 'latest' if ':' not in self.model_name else self.model_name.split(':')[1]
#         model_base = self.model_name.split(':')[0]
#         model_name_crewai_num_ctx = f"{model_base}_crewai_{self.num_ctx}"
#         model_name_crewai = f"{model_base}_crewai"
#         model_name_base = model_base
#         model_base_version = f"{model_base}:{version}"

#         ollama_models = list()['models']
#         match = None
#         for o_model in ollama_models:
#             o_model_name = o_model['name']
#             # Check for exact matches including num_ctx and version
#             if o_model_name == f"{model_name_crewai_num_ctx}:{version}":
#                 match = "crewai_num_ctx"
#             # Check for matches with 'crewai' suffix and possibly handling versions
#             elif o_model_name == f"{model_name_crewai}:{version}":
#                 match = "crewai"
#             # Check for base model matches with versions
#             elif o_model_name == f"{model_name_base}:{version}":
#                 match = "base"
#             return self.ollama_patch_and_load(o_model=model_base_version, num_ctx=self.num_ctx, match=match)

#         logger.info(f"No local matching model found for '{self.model_name}' in Ollama.")
#         logger.info(f"Attempting to pull {self.model_name} with streaming enabled.")
#         return self.ollama_pull_and_load(model_name = self.model_name)

#     def ollama_patch_and_load(self, o_model, num_ctx, match=None):
#         """
#         Patches the model file with specific configurations such as num_ctx and stop words, then loads it.
#         """
#         patch_stop_words = OllamaConfig.patch_stop_words
#         patch_num_ctx    = OllamaConfig.patch_num_ctx
#         stop_words       = OllamaConfig.stop_words

#         #No patching required, skip all, load the model directly
#         if  (patch_stop_words == False and (patch_num_ctx == False or num_ctx is None)) or \
#             (patch_num_ctx == False and stop_words == []):
#             logger.info(f"No patching required for model '{o_model}', loading directly...")
#             return Ollama(model=o_model)
#         #<-----

#         #get the base model modelfile num_ctx and stop words
#         o_model_details = show(o_model)
#         o_modelfile = o_model_details['modelfile']
#         c_modelfile_nctx_list = re.findall(r'PARAMETER num_ctx (\d+)', c_modelfile)
#         c_modelfile_stop_list = re.findall(r'PARAMETER stop (.*)', c_modelfile)

#         #get the crewai model modelfile num_ctx and stop words for comparison
#         version = 'latest' if ':' not in o_model else o_model.split(':')[1]
#         if match == "crewai_num_ctx":
#             crewai_model_name = o_model.split(':')[0] + "_crewai_" + str(num_ctx) + "_:" + version
#             c_model_details = show(crewai_model_name)
#             c_modelfile = c_model_details['modelfile']
#         elif match == "crewai":
#             crewai_model_name = o_model.split(':')[0] + "_crewai" + version
#             c_model_details = show(crewai_model_name)
#             c_modelfile = c_model_details['modelfile']
#         else:
#             c_modelfile = o_modelfile
#         c_modelfile_nctx = c_modelfile_nctx_list[0] if c_modelfile_nctx_list else None #there is only one num_ctx
#         combined_stop_words = list(set(stop_words + c_modelfile_stop_list))

#         #num_ctx and original stop words and config defined stop word match
#         if c_modelfile_nctx == num_ctx and c_modelfile_stop_list == combined_stop_words:
#             logger.info(f"Model '{crewai_model_name}' found with correct num_ctx and stop words, loading directly.")
#             return Ollama(model=crewai_model_name)
#         #<-----

#         else: #patch modelfile
#             logger.info(f"Model '{crewai_model_name}' found with unmatching num_ctx or stop words, patching model.")
#             logger.info(f"Patching model: {o_model} with num_ctx = {num_ctx} and stop words: {stop_words}")

#             if patch_stop_words and stop_words != []:
#                 for stop_word in stop_words:
#                     if stop_word not in modelfile:
#                         modelfile += f"\nPARAMETER stop {stop_word}"

#             if patch_num_ctx and num_ctx:
#                 modelfile += f"\nPARAMETER num_ctx {num_ctx}"

#         #calculate name of the patched model
#         if num_ctx:
#             crewai_model_name = f"{o_model.split(':')[0]}_crewai_{num_ctx}:{version}"
#         else:
#             crewai_model_name = f"{o_model.split(':')[0]}_crewai:{version}"

#         #create the patched model
#         logger.info(f"Creating new model '{crewai_model_name}' with updated stop parameters."\
#                     f"num_ctx : {num_ctx}, stop_words: {stop_words}")

#         for response in create(model=crewai_model_name, modelfile=modelfile, stream=True):
#             self.handle_progress_updates(response, self.progress, self.llm_task)
#         return Ollama(model=crewai_model_name)
