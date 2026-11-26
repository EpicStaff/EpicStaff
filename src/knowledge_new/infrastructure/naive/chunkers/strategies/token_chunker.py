import functools
from itertools import pairwise

import tiktoken
from application.ports import AbstractChunker
from domain.models import PreviewChunk
from infrastructure.processing_run import run_in_process

TOKEN_ENCODING = "o200k_base"


@functools.cache
def load_token_encoding() -> tiktoken.Encoding:
    """Load the token chunker's encoding once per process.

    tiktoken reads the encoding from TIKTOKEN_CACHE_DIR, which the Dockerfile bakes,
    so an offline container never reaches the download URL. Process-pool workers
    inherit it only when the pool forks after startup; with spawn each worker loads
    it once itself.
    """
    return tiktoken.get_encoding(TOKEN_ENCODING)


def _byte_offsets(
    encoding: tiktoken.Encoding, tokens: list[int], positions: set[int]
) -> dict[int, int]:
    # Map each token position to the UTF-8 byte offset where that token starts.
    # Decoding only the stretches between window bounds keeps this in tiktoken's native
    # code; decoding every token to its own bytes object is ten times slower on a large
    # document.
    offsets: dict[int, int] = {}
    previous_position = 0
    total = 0
    for position in sorted(positions):
        total += len(encoding.decode_bytes(tokens[previous_position:position]))
        offsets[position] = total
        previous_position = position
    return offsets


class TokenChunker(AbstractChunker):
    """Split text into equal token windows with an exact token overlap.

    Every chunk is a slice of the original text: a window boundary that lands inside
    a multi-byte character is moved back to that character's first byte, so no
    character is split, lost or replaced.
    """

    @run_in_process
    def _chunk(self, text: str) -> list[PreviewChunk]:
        chunk_size = self.config.chunk_size
        chunk_overlap = self.config.chunk_overlap
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be smaller than chunk_size ({chunk_size})"
            )

        encoding = load_token_encoding()
        data = text.encode("utf-8")
        # encode_ordinary, not encode: special-token strings such as <|endoftext|> in a
        # document are plain text here, and encode would raise on them.
        tokens = encoding.encode_ordinary(text)

        windows: list[tuple[int, int]] = []
        for first in range(0, len(tokens), chunk_size - chunk_overlap):
            last = min(first + chunk_size, len(tokens))
            windows.append((first, last))
            if last == len(tokens):
                break
        byte_offsets = _byte_offsets(
            encoding, tokens, {bound for window in windows for bound in window}
        )

        def to_character_start(position: int) -> int:
            # 0b10xxxxxx is a UTF-8 continuation byte, never the first byte of a character.
            while 0 < position < len(data) and data[position] & 0xC0 == 0x80:
                position -= 1
            return position

        spans: list[tuple[int, int]] = []
        for first, last in windows:
            start = to_character_start(byte_offsets[first])
            end = to_character_start(byte_offsets[last])
            # With a one-token step, two window ends can fall inside the same multi-byte
            # character and move back to the same place. Such a span repeats or sits
            # inside the previous one, so only a span whose end moves forward is kept.
            if end > (spans[-1][1] if spans else start):
                spans.append((start, end))

        kept = [
            (start, end, chunk_text)
            for start, end in spans
            if (chunk_text := data[start:end].decode("utf-8")).strip()
        ]

        overlaps = [
            len(data[next_start:previous_end].decode("utf-8")) if previous_end > next_start else 0
            for (_, previous_end, _), (next_start, _, _) in pairwise(kept)
        ]

        chunk_texts = [chunk_text for _, _, chunk_text in kept]
        # A cut moved back to a character start changes how the chunk's edges tokenize,
        # so the count is taken from the chunk text, not from its window. The batch call
        # encodes on tiktoken's thread pool and about halves the time of a large preview.
        token_counts = [
            len(chunk_tokens) for chunk_tokens in encoding.encode_ordinary_batch(chunk_texts)
        ]
        return [
            PreviewChunk(
                text=chunk_text,
                token_count=token_count,
                overlap_start=overlaps[index - 1] if index > 0 else None,
                overlap_end=overlaps[index] if index < len(overlaps) else None,
            )
            for index, (chunk_text, token_count) in enumerate(
                zip(chunk_texts, token_counts, strict=True)
            )
        ]
