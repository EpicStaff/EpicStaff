from chonkie import TokenChunker as ChonkieTokenChunker

from chunkers.base_chunker import BaseChunker, BaseChunkData


class TokenChunker(BaseChunker):
    def __init__(self, chunk_size, chunk_overlap, additional_params):
        self.text_splitter = ChonkieTokenChunker(
            tokenizer="gpt2", chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    def chunk(self, text: str) -> list[BaseChunkData]:
        chunks = self.text_splitter.chunk(text)

        overlaps = []
        for i in range(len(chunks) - 1):
            overlap = chunks[i].end_index - chunks[i + 1].start_index
            overlaps.append(overlap)

        token_chunks = []
        for i, chunk in enumerate(chunks):
            token_chunks.append(
                BaseChunkData(
                    text=chunk.text,
                    token_count=chunk.token_count,
                    overlap_start_index=overlaps[i - 1] if i > 0 else None,
                    overlap_end_index=overlaps[i] if i < len(overlaps) else None,
                )
            )
        return token_chunks
