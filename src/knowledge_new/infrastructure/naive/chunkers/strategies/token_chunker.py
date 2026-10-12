import settings
from application.ports import AbstractChunker
from chonkie import TokenChunker as ChonkieTokenChunker
from domain.models import PreviewChunk
from infrastructure.processing_run import run_in_process
from tokie import Tokenizer


def _load_tokenizer() -> Tokenizer | str:
    # tokie resolves a tokenizer name through $HOME/.cache and downloads from
    # huggingface.co when it is cold, ignoring HF_HOME and HF_HUB_OFFLINE. Loading
    # the file the image bakes bypasses that cache entirely.
    if settings.TOKENIZER_PATH:
        return Tokenizer.from_file(settings.TOKENIZER_PATH)
    return "gpt2"


class TokenChunker(AbstractChunker):
    @run_in_process
    def _chunk(self, text: str) -> list[PreviewChunk]:
        text_splitter = ChonkieTokenChunker(
            tokenizer=_load_tokenizer(),
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )
        chunks = text_splitter.chunk(text)

        overlaps = []
        for i in range(len(chunks) - 1):
            overlap = chunks[i].end_index - chunks[i + 1].start_index
            overlaps.append(overlap)

        token_chunks = []
        for i, chunk in enumerate(chunks):
            if chunk.text.strip():
                token_chunks.append(
                    PreviewChunk(
                        text=chunk.text,
                        token_count=chunk.token_count,
                        overlap_start=overlaps[i - 1] if i > 0 else None,
                        overlap_end=overlaps[i] if i < len(overlaps) else None,
                    )
                )
        return token_chunks
