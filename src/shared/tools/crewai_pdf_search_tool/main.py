# PDF Semantic Search Tool using OpenAI embeddings
import os
from typing import Optional
import json

from pydantic import BaseModel

from PyPDF2 import PdfReader
from openai import OpenAI
import numpy as np

class PDFSearchToolSchema(BaseModel):
    query: str
    pdf: str
    openai_api_key: Optional[str] = None
    similarity_threshold: Optional[float] = 0.7
    limit: Optional[int] = 5


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF file"""
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text


def compute_embeddings(texts, client):
    """Compute OpenAI embeddings for a list of texts"""
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts
    )
    return [np.array(e.embedding) for e in response.data]

def dynamic_chunking(text: str, query: str, min_words: int = 50, max_words: int = 1000, multiplier: int = 50):
    """
    Split text into chunks based on query length.

    - Single-word queries → small chunks (min_words)
    - Multi-word queries → chunk size = num_words_in_query * multiplier
    - Caps applied: min_words <= chunk_size <= max_words
    """
    query_word_count = len(query.split())
    if query_word_count == 1:
        chunk_size = min_words  # small chunk for single word
    else:
        chunk_size = query_word_count * multiplier
        chunk_size = max(min_words, min(chunk_size, max_words))  # enforce min/max bounds

    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[i:i+chunk_size]))
    return chunks

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def main(
    query: str,
    pdf: str,
    openai_api_key: Optional[str] = None,
    similarity_threshold: Optional[float] = 0.7,
    limit: Optional[int] = 5
) -> str:
    """
    Perform semantic search on PDF content using OpenAI embeddings.
    """
    if openai_api_key is None:
        openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OpenAI API key not provided. Pass 'openai_api_key' or set OPENAI_API_KEY env var.")

    client = OpenAI(api_key=openai_api_key)

    text = extract_text_from_pdf(pdf)
    if not text.strip():
        return "No text extracted from PDF."

    # Split text into chunks
    chunks = dynamic_chunking(text, query)
    print("Chunks", chunks)
    # Compute embeddings
    embeddings = compute_embeddings(chunks, client)
    query_embedding = compute_embeddings([query], client)[0]

    # Compute similarities
    similarities = [cosine_similarity(query_embedding, emb) for emb in embeddings]
    print("Similarities", similarities)
    # Filter by threshold
    results = [(chunks[i], similarities[i]) for i in range(len(chunks)) if similarities[i] >= similarity_threshold]
    print(results)
    # Sort and limit
    results = sorted(results, key=lambda x: x[1], reverse=True)[:limit]

    # Format output
    output = "\n\n".join([f"[{sim:.3f}] {text}" for text, sim in results])
    return output or "No matching content found."