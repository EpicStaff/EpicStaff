import os
from typing import Optional
import urllib.request


def read_txt_file(txt: str) -> str:
    """Load text from a file path or URL."""
    if txt.startswith("http://") or txt.startswith("https://"):
        with urllib.request.urlopen(txt) as response:
            return response.read().decode("utf-8")
    elif os.path.isfile(txt):
        with open(txt, "r", encoding="utf-8") as f:
            return f.read()
    else:
        raise FileNotFoundError(f"TXT file not found: {txt}")


def search_in_text(
    text: str, search_query: str, similarity_threshold: float = 0.7, limit: int = 5
) -> str:
    """Very simple search: returns lines containing the query. For real semantic search, replace with embedding-based search."""
    results = []
    for line in text.splitlines():
        if search_query.lower() in line.lower():
            results.append(line.strip())
        if len(results) >= limit:
            break
    return "\n".join(results)


def main(
    txt: str,
    search_query: str,
    similarity_threshold: Optional[float] = 0.7,
    limit: Optional[int] = 5,
) -> str:
    """
    Entry point for TXTSearchTool.

    Args:
        txt (str): File path or URL of a TXT file.
        search_query (str): Search query.
        similarity_threshold (float, optional): Currently unused.
        limit (int, optional): Max number of results.

    Returns:
        str: Search results.
    """
    try:
        content = read_txt_file(txt)
        results = search_in_text(
            content, search_query, similarity_threshold=similarity_threshold, limit=limit
        )
        return results if results else "No results found."
    except Exception as e:
        return f"Error: {e}"