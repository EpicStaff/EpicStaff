from __future__ import annotations
import time
import logging
import asyncio
from typing import Any, AsyncIterator, Iterator, List, Optional, Union
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import (
    agenerate_from_stream,
    generate_from_stream,
)
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.pydantic_v1 import BaseModel
from langchain_groq import ChatGroq
from langchain_groq.chat_models import (
    _convert_delta_to_message_chunk,
    _convert_dict_to_message,
)
from rich.console import Console
import tiktoken

# from tiktoken.core import Encoding
# from tiktoken.model import encoding_for_model, encoding_name_for_model
# from tiktoken.registry import get_encoding, list_encoding_names

console = Console()
logger = logging.getLogger(__name__)


class Throttle:
    def __init__(
        self, rate_limit: int = None, average_token_length: int = 5, model_name="gpt-4"
    ):
        try:
            if rate_limit is None:
                logger.debug("Rate limit for Grog is not set. Not throtelling.")
            else:
                logger.debug("Rate limit for Grog is set. Setting up throtelling.")
                self.model_name = model_name
                self.rate_limit = rate_limit
                self.enc = tiktoken.encoding_for_model(model_name)
                self.average_token_length = average_token_length
                self.last_time_called = time.time()
                self.ratelimit_remaining_tokens = self.rate_limit

                logger.debug(f"/nThrottle Rate limit: {self.rate_limit}")
                logger.debug(f"Average token length : {self.average_token_length}")
        except Exception as e:
            logger.error(f"Failed to configure Throttle: {e}")

    def calculate_tokens(self, text=None):
        """Estimate number of tokens using the specific encoding model."""
        if text is None:
            return 0
        try:
            encoded_text = self.enc.encode(text)
            token_count = len(encoded_text) * 1.1  # 10$ safety margin
            logging.debug(f"Text: {text}")
            logging.debug(f"Token count: {token_count}")
            if token_count > self.rate_limit:
                exception = Exception(
                    f"Token count exceeds rate limit: Token count:{token_count} Rate limit: {self.rate_limit} \n\
                                      Please reduce the text length or increase the rate limit."
                )
                raise exception

            return token_count
        except Exception as e:
            logging.error(f"Failed to calculate tokens: {e}")
            return 0

    # def calculate_tokens(self, text = None):
    #     """Estimate number of tokens based on text length."""       #Todo, use a better tokenization method
    #     try:
    #         if text is None:
    #             return 0
    #         else:
    #             #logger.debug(text)
    #             #logger.debug(f"Token length: {len(text) // self.average_token_length}")
    #             return len(str(text)) // self.average_token_length
    #     except Exception as e:
    #         logger.error(f"Failed to calculate tokens: {e}")
    #         return 0

    def _update_tokens(self):
        """Update tokens based on elapsed time."""
        try:
            if self.rate_limit is None:  # Don't throttle if rate limit is not set
                return

            now = time.time()
            elapsed = int(now - self.last_time_called)  # Elapsed time in seconds
            tps = self.rate_limit // 60  # Tokens per second accumulated
            self.ratelimit_remaining_tokens += (
                elapsed * tps
            )  # Accumulated tokens sine last call
            self.last_time_called = now  # Update last call time
            logger.debug(
                f"ratelimit_remaining_tokens:{self.ratelimit_remaining_tokens}"
            )
        except Exception as e:
            logger.error(f"Failed to update tokens: {e}")
            return 0

    def wait(self, tokens_needed: int):
        """Delay execution to respect the throttle limit."""
        try:
            if self.rate_limit is None:  # Don't throttle if rate limit is not set
                return

            self._update_tokens()

            if (
                self.ratelimit_remaining_tokens >= tokens_needed
            ):  # If accumulated tokens exceed the needed
                self.ratelimit_remaining_tokens -= (
                    tokens_needed  # Deduct the tokens needed
                )
                return  # No need to wait

            # Calculate sleep time to accumulate needed tokens
            tps = self.rate_limit // 60  # Tokens per second
            tokens_defecit = tokens_needed - self.ratelimit_remaining_tokens
            sleep_time = tokens_defecit // tps
            logger.debug(f"tokens_needed: {tokens_needed}")
            logger.debug(f"sleep_time: {sleep_time}")
            time.sleep(sleep_time)

            self._update_tokens()  # Update tokens after sleep
            self.ratelimit_remaining_tokens -= tokens_needed
        except Exception as e:
            logger.error(f"Failed to wait: {e}")
            return 0

    async def await_(self, tokens_needed: int):
        """Asynchronous version of the wait."""
        try:
            if self.rate_limit is None:  # Don't throttle if rate limit is not set
                return

            self._update_tokens()

            if (
                self.ratelimit_remaining_tokens >= tokens_needed
            ):  # If accumulated tokens exceed the needed
                self.ratelimit_remaining_tokens -= (
                    tokens_needed  # Deduct the tokens needed
                )
                return  # No need to wait

            # Calculate sleep time to accumulate needed tokens
            tps = self.rate_limit // 60  # Tokens per second
            tokens_defecit = tokens_needed - self.ratelimit_remaining_tokens
            sleep_time = tokens_defecit // tps
            logger.debug(f"tokens_needed: {tokens_needed}")
            logger.debug(f"sleep_time: {sleep_time}")

            await asyncio.sleep(sleep_time)

            # Update tokens after sleep and adjust for token usage
            self._update_tokens()
            self.ratelimit_remaining_tokens -= tokens_needed
        except Exception as e:
            logger.error(f"Failed to await: {e}")
            return 0


class TokenThrottledChatGroq(ChatGroq):
    def __init__(self, *args, rate_limit: Optional[int], **kwargs):
        super().__init__(
            *args, **kwargs
        )  # Call the parent class constructor with additional arguments

        # SET UP THROTTLE
        self.rate_limit = rate_limit if rate_limit else None
        self.throttle = Throttle(rate_limit=self.rate_limit)

    # OVERRIDE pydantic_v1 BaseModel
    rate_limit: Optional[int] = None
    throttle: Throttle = Throttle(rate_limit=None)
    """Throttle settings for token generation."""

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:

        # Throttle
        # for message in messages:
        #    logger.debug("Debug: Type of message.content is", type(message.content))
        #    logger.debug("Debug: message.content is", message.content)

        input_text = ""
        for message in messages:
            input_text = input_text + message.content
        input_tokens = self.throttle.calculate_tokens(
            input_text
        )  # Simplistic token count for input
        total_tokens = input_tokens + self.max_tokens  # Assume we will get max_tokens
        self.throttle.wait(total_tokens)

        if self.streaming:
            stream_iter = self._stream(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
            return generate_from_stream(stream_iter)
        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {**params, **kwargs}
        response = self.client.create(messages=message_dicts, **params)
        # logger.debug("Response: ", response)

        return self._create_chat_result(response)

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Throttle
        # for message in messages:
        #    logger.debug("Debug: Type of message.content is", type(message.content))
        #    logger.debug("Debug: message.content is", message.content)

        input_text = ""
        for message in messages:
            input_text = input_text + message.content
        input_tokens = self.throttle.calculate_tokens(
            input_text
        )  # Simplistic token count for input
        total_tokens = input_tokens + self.max_tokens
        self.throttle.await_(total_tokens)

        if self.streaming:
            stream_iter = self._astream(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
            return await agenerate_from_stream(stream_iter)

        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {
            **params,
            **kwargs,
        }
        response = await self.async_client.create(messages=message_dicts, **params)
        # logger.debug("Response: ", response)
        # logger.debug("Response type: ", type(response))
        return self._create_chat_result(response)

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        # Throttle
        # for message in messages:
        #    logger.debug("Debug: Type of message.content is", type(message.content))
        #    logger.debug("Debug: message.content is", message.content)

        input_text = ""
        for message in messages:
            input_text = input_text + message.content
        input_tokens = self.throttle.calculate_tokens(
            input_text
        )  # Simplistic token count for input
        total_tokens = input_tokens + self.max_tokens
        self.throttle.wait(total_tokens)

        message_dicts, params = self._create_message_dicts(messages, stop)

        # groq api does not support streaming with tools yet
        if "tools" in kwargs:
            response = self.client.create(
                messages=message_dicts, **{**params, **kwargs}
            )
            chat_result = self._create_chat_result(response)
            generation = chat_result.generations[0]
            message = generation.message
            tool_call_chunks = [
                {
                    "name": rtc["function"].get("name"),
                    "args": rtc["function"].get("arguments"),
                    "id": rtc.get("id"),
                    "index": rtc.get("index"),
                }
                for rtc in message.additional_kwargs["tool_calls"]
            ]
            chunk_ = ChatGenerationChunk(
                message=AIMessageChunk(
                    content=message.content,
                    additional_kwargs=message.additional_kwargs,
                    tool_call_chunks=tool_call_chunks,
                ),
                generation_info=generation.generation_info,
            )
            if run_manager:
                geninfo = chunk_.generation_info or {}
                run_manager.on_llm_new_token(
                    chunk_.text,
                    chunk=chunk_,
                    logprobs=geninfo.get("logprobs"),
                )
            yield chunk_
            return

        params = {**params, **kwargs, "stream": True}

        default_chunk_class = AIMessageChunk
        for chunk in self.client.create(messages=message_dicts, **params):
            if not isinstance(chunk, dict):
                chunk = chunk.dict()
            if len(chunk["choices"]) == 0:
                continue
            choice = chunk["choices"][0]
            chunk = _convert_delta_to_message_chunk(choice["delta"], AIMessageChunk)
            generation_info = {}
            if finish_reason := choice.get("finish_reason"):
                generation_info["finish_reason"] = finish_reason
            logprobs = choice.get("logprobs")
            if logprobs:
                generation_info["logprobs"] = logprobs
            default_chunk_class = chunk.__class__
            chunk = ChatGenerationChunk(
                message=chunk, generation_info=generation_info or None
            )

            if run_manager:
                run_manager.on_llm_new_token(chunk.text, chunk=chunk, logprobs=logprobs)
            yield chunk

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        # Throttle
        # for message in messages:
        #    logger.debug("Debug: Type of message.content is", type(message.content))
        #    logger.debug("Debug: message.content is", message.content)

        input_text = ""
        for message in messages:
            input_text = input_text + message.content
        input_tokens = self.throttle.calculate_tokens(
            input_text
        )  # Simplistic token count for input
        total_tokens = input_tokens + self.max_tokens
        self.throttle.wait(total_tokens)

        message_dicts, params = self._create_message_dicts(messages, stop)

        # groq api does not support streaming with tools yet
        if "tools" in kwargs:
            response = await self.async_client.create(
                messages=message_dicts, **{**params, **kwargs}
            )
            chat_result = self._create_chat_result(response)
            generation = chat_result.generations[0]
            message = generation.message
            tool_call_chunks = [
                {
                    "name": rtc["function"].get("name"),
                    "args": rtc["function"].get("arguments"),
                    "id": rtc.get("id"),
                    "index": rtc.get("index"),
                }
                for rtc in message.additional_kwargs["tool_calls"]
            ]
            chunk_ = ChatGenerationChunk(
                message=AIMessageChunk(
                    content=message.content,
                    additional_kwargs=message.additional_kwargs,
                    tool_call_chunks=tool_call_chunks,
                ),
                generation_info=generation.generation_info,
            )
            if run_manager:
                geninfo = chunk_.generation_info or {}
                await run_manager.on_llm_new_token(
                    chunk_.text,
                    chunk=chunk_,
                    logprobs=geninfo.get("logprobs"),
                )
            yield chunk_
            return

        params = {**params, **kwargs, "stream": True}

        default_chunk_class = AIMessageChunk
        async for chunk in await self.async_client.create(
            messages=message_dicts, **params
        ):
            if not isinstance(chunk, dict):
                chunk = chunk.dict()
            if len(chunk["choices"]) == 0:
                continue
            choice = chunk["choices"][0]
            chunk = _convert_delta_to_message_chunk(
                choice["delta"], default_chunk_class
            )
            generation_info = {}
            if finish_reason := choice.get("finish_reason"):
                generation_info["finish_reason"] = finish_reason
            logprobs = choice.get("logprobs")
            if logprobs:
                generation_info["logprobs"] = logprobs
            default_chunk_class = chunk.__class__
            chunk = ChatGenerationChunk(
                message=chunk, generation_info=generation_info or None
            )

            if run_manager:
                await run_manager.on_llm_new_token(
                    token=chunk.text, chunk=chunk, logprobs=logprobs
                )
            yield chunk

    def _create_chat_result(self, response: Union[dict, BaseModel]) -> ChatResult:
        generations = []
        if not isinstance(response, dict):
            response = response.dict()
        for res in response["choices"]:
            message = _convert_dict_to_message(res["message"])
            generation_info = dict(finish_reason=res.get("finish_reason"))
            if "logprobs" in res:
                generation_info["logprobs"] = res["logprobs"]
            gen = ChatGeneration(
                message=message,
                generation_info=generation_info,
            )
            generations.append(gen)
        token_usage = response.get("usage", {})
        llm_output = {
            "token_usage": token_usage,
            "model_name": self.model_name,
            "system_fingerprint": response.get("system_fingerprint", ""),
        }
        # logger.debug("token_usage: ", token_usage)
        self.throttle.ratelimit_remaining_tokens += (
            self.max_tokens - token_usage["total_tokens"]
        )  # Trottle: release unused tokens TODO: call function
        self.throttle._update_tokens()
        return ChatResult(generations=generations, llm_output=llm_output)
