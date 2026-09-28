import copy
import uuid

from loguru import logger
from utils.tokenizer import Tokenizer


class ChatBuffer:
    """
    A buffer class for storing user input text and tracking the number of tokens used.
    This class helps manage how much context is accumulated before needing summarization or reset.

    TODO: REFACTOR
    Fix order in buffer. Buffer appends the quickest response, that can affect the summarization.
    Make buffer append in strict order!
    """

    def __init__(self, tokenizer: Tokenizer, max_buffer_tokens: int = 50):
        self._buffer: list[str] = []  # user input buffer
        self._order: list[uuid.UUID] = []
        self._max_buffer_tokens = max_buffer_tokens
        self._buffer_token_count: int = 0
        self._last_input: str = ""
        self.tokenizer = tokenizer

    def __len__(self) -> int:
        return self._buffer_token_count

    def check_free_buffer(self) -> bool:
        if self._buffer_token_count >= self._max_buffer_tokens:
            logger.debug(
                f"Cannot add tokens to the buffer because it is full. "
                f"{self._max_buffer_tokens} is max number tokens for the buffer. "
                f"{self._buffer_token_count} tokens are currently in the buffer"
            )
            return False

        return True

    def append(self, text: str) -> None:
        logger.debug(f"Buffer received text to append: {text}")
        self._last_input = text.lower()
        self._buffer.append(text)

        tokens: list[int] = self.tokenizer.tokenize(text)
        self._buffer_token_count += len(tokens)

    def get_buffer(self) -> list[str]:
        return copy.copy(self._buffer)

    def flush_buffer(self) -> None:
        self._buffer.clear()
        self._buffer_token_count = 0
        self._last_input: str = ""

    def get_last_input(self) -> list[str]:
        # .append() sets '_last_input'
        last_input = [word.strip("!?., ") for word in self._last_input.split()]
        logger.debug(f"get_last_input: {last_input}")
        return last_input


class ChatSummarizedBuffer(ChatBuffer):
    """
    Extended buffer that also manages a summarized chunk buffer,
    used to compress past conversation context.
    """

    def __init__(self, tokenizer: Tokenizer, max_buffer_tokens: int, max_chunks_tokens: int = 100):
        super().__init__(tokenizer, max_buffer_tokens)
        self._chunks: list[str] = []  # summarized chunks buffer
        self._max_chunks_tokens: int = max_chunks_tokens
        self._chunks_tokens_count: int = 0

    def check_free_chunks(self) -> bool:
        if self._chunks_tokens_count >= self._max_chunks_tokens:
            logger.debug("Cannot add new chunk because summarized chunks buffer is full")
            return False

        return True

    def append_chunk(self, summarized_text: str) -> None:
        if not self.check_free_chunks():
            return

        tokens: list[int] = self.tokenizer.tokenize(summarized_text)
        self._chunks.append(summarized_text)
        self._chunks_tokens_count += len(tokens)
        logger.debug(
            f"Successfully added new summarized chunk to summarized chunks buffer\n\n"
            f"Total chunks: {len(self._chunks)}"
        )

    def get_chunks(self) -> list[str]:
        return copy.copy(self._chunks)

    def get_final_buffer(self) -> str:
        """Combine the summarized chunks and the user input buffer into one final buffer string."""
        buffer_text: str = "\n".join(self._buffer)

        if self._chunks_tokens_count:
            logger.debug("Adding text from the chunks to text from buffer")
            chunks_text = "\n\n".join(self._chunks)
            buffer_text = chunks_text + "\n\n" + buffer_text

        logger.debug(f"final_buffer: {buffer_text}")
        return buffer_text

    def flush_chunks(self) -> None:
        self._chunks = []
        self._chunks_tokens_count: int = 0

    def flush(self) -> None:
        """
        Clear both the user input buffer and the summarized chunks buffer.
        """
        self.flush_buffer()
        self.flush_chunks()
