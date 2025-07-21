from typing import cast
from models.request_models import LLMData
from .base_node import *
import litellm
from litellm import Choices
from litellm.types.utils import ModelResponse


class LLMNode(BaseNode):
    TYPE = "LLM"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        llm_data: LLMData,
        input_map: dict,
        output_variable_path: str,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            input_map=input_map,
            output_variable_path=output_variable_path,
        )
        llm_config = llm_data.config
        self.params = {
            "model": f"{llm_data.provider}/{llm_data.config.model}",
            "timeout": llm_config.timeout,
            "temperature": llm_config.temperature,
            "top_p": llm_config.top_p,
            "n": llm_config.n,
            "stop": llm_config.stop,
            "max_tokens": llm_config.max_tokens,
            "presence_penalty": llm_config.presence_penalty,
            "frequency_penalty": llm_config.frequency_penalty,
            "logit_bias": llm_config.logit_bias,
            "response_format": llm_config.response_format,
            "seed": llm_config.seed,
            "logprobs": llm_config.logprobs,
            "top_logprobs": llm_config.top_logprobs,
            # "api_base": llm_config.api_base,
            "base_url": llm_config.base_url,
            "api_version": llm_config.api_version,
            "api_key": llm_config.api_key,
            "stream": False,
        }

    async def execute(
        self, state: State, writer: StreamWriter, input_: Any, execution_order: int
    ):
        message = {"role": "user", "content": input_["query"]}
        params = {**self.params, "messages": [message]}

        model_response: ModelResponse = await litellm.acompletion(**params)
        response_message: StopIteration = cast(
            Choices, cast(ModelResponse, model_response).choices
        )[0].message.content

        llm_message_data = LLMMessageData(
            response=response_message,
        )
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=execution_order,
            message_data=llm_message_data,
        )
        writer(graph_message)

        return {"response": response_message}
