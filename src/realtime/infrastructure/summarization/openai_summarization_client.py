from loguru import logger

from openai import AsyncOpenAI

from domain.ports.i_summarization_client import ISummarizationClient
from utils.openai_endpoints import derive_chat_http_url


class OpenaiSummarizationClient(ISummarizationClient):
    """
    A client for summarizing text using OpenAI's API.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
    ):
        self.__api_key = api_key
        self.model = model
        self.__base_url = derive_chat_http_url(base_url)

    async def _summarize(self, messages: list[dict]) -> str:
        try:
            client = AsyncOpenAI(api_key=self.__api_key, base_url=self.__base_url)
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
            )

            summarized_text = response.choices[0].message.content
            logger.debug(f"Text was successfully summarized:\n\n{summarized_text}\n")

            return summarized_text
        except Exception:
            logger.exception("Error during litellm completion request")
            return ""

    async def summarize_buffer(self, to_summarize: str) -> str:
        if not to_summarize:
            logger.error(
                "Couldn't summarize the buffer. Parameter 'to_summarize' cannot be empty"
            )
            return ""

        logger.debug(f"Received text (buffer) to summarize:\n\n{to_summarize}\n")

        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant that summarizes "
                "text clearly and concisely. Summarize the text "
                "using the same language it is written in.",
            },
            {
                "role": "user",
                "content": f"Summarize the following text in the same"
                f" language it was originally written in.:\n{to_summarize}",
            },
        ]

        return await self._summarize(messages)

    async def summarize_chunks(self, to_summarize: str):
        if not to_summarize:
            logger.error(
                "Couldn't summarize the chunks. Parameter 'to_summarize' cannot be empty"
            )
            return ""

        logger.debug(f"Received text (chunks) to summarize:\n\n{to_summarize}\n")

        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant that summarizes "
                "text clearly and concisely. Summarize the text "
                "using the same language it is written in. And make it shorter. "
                "Text written in the top must be compressed more than the text in the bottom",
            },
            {
                "role": "user",
                "content": f"Summarize the following text in the same"
                f" language it was originally written in.:\n{to_summarize}",
            },
        ]
        return await self._summarize(messages)
