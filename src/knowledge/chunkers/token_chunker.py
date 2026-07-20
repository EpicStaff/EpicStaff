from typing import List, Union

import tiktoken

from chunkers.base_chunker import BaseChunker, BaseChunkData


class TokenChunker(BaseChunker):
    """Token-window chunker backed by tiktoken's ``gpt2`` encoding.

    Reimplements the exact windowing algorithm previously provided by
    ``chonkie.TokenChunker(tokenizer="gpt2", ...)`` so that behavior (chunk
    boundaries, token counts, and overlap accounting) is preserved bit for
    bit.
    """

    _ENCODING_NAME = "gpt2"

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: Union[int, float],
        additional_params,
    ):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if isinstance(chunk_overlap, int) and chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = (
            chunk_overlap
            if isinstance(chunk_overlap, int)
            else int(chunk_overlap * chunk_size)
        )
        self._encoding = tiktoken.get_encoding(self._ENCODING_NAME)

    def _token_groups(self, tokens: List[int]) -> List[List[int]]:
        """Slide a `chunk_size` window over `tokens` with `chunk_overlap` stride."""
        step = self.chunk_size - self.chunk_overlap
        groups = []
        for start in range(0, len(tokens), step):
            end = min(start + self.chunk_size, len(tokens))
            groups.append(tokens[start:end])
            if end == len(tokens):
                break
        return groups

    def chunk(self, text: str) -> list[BaseChunkData]:
        if not text.strip():
            return []

        text_tokens = self._encoding.encode(text)
        token_groups = self._token_groups(text_tokens)
        token_counts = [len(group) for group in token_groups]
        chunk_texts = [self._encoding.decode(group) for group in token_groups]

        if self.chunk_overlap > 0:
            overlap_texts = [
                self._encoding.decode(
                    group[-self.chunk_overlap :]
                    if len(group) > self.chunk_overlap
                    else group
                )
                for group in token_groups
            ]
            overlap_lengths = [len(overlap_text) for overlap_text in overlap_texts]
        else:
            overlap_lengths = [0] * len(token_groups)

        chunks = []
        current_index = 0
        for chunk_text, overlap_length, token_count in zip(
            chunk_texts, overlap_lengths, token_counts
        ):
            start_index = current_index
            end_index = start_index + len(chunk_text)
            chunks.append(
                {
                    "text": chunk_text,
                    "start_index": start_index,
                    "end_index": end_index,
                    "token_count": token_count,
                }
            )
            current_index = end_index - overlap_length

        overlaps = []
        for i in range(len(chunks) - 1):
            overlap = chunks[i]["end_index"] - chunks[i + 1]["start_index"]
            overlaps.append(overlap)

        token_chunks = []
        for i, chunk in enumerate(chunks):
            token_chunks.append(
                BaseChunkData(
                    text=chunk["text"],
                    token_count=chunk["token_count"],
                    overlap_start_index=overlaps[i - 1] if i > 0 else None,
                    overlap_end_index=overlaps[i] if i < len(overlaps) else None,
                )
            )
        return token_chunks
