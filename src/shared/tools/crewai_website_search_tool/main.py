# Website Search Tool
import requests
from bs4 import BeautifulSoup
from typing import Optional


def main(
    search_query: str,
    website: str,
    similarity_threshold: Optional[float] = None,
    limit: Optional[int] = None
) -> str:
    """
    Perform a basic search for a query in the text content of a website.

    Args:
        search_query (str): The search query to look for.
        website (str): URL of the website to search in.
        similarity_threshold (float, optional): Placeholder, not implemented in this standalone version.
        limit (int, optional): Maximum number of results to return.

    Returns:
        str: Search results with matched text snippets.
    """
    try:
        response = requests.get(website, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return f"Error fetching website {website}: {e}"

    soup = BeautifulSoup(response.text, "html.parser")
    text_content = soup.get_text(separator="\n")

    # Simple search implementation (case-insensitive)
    matches = [line for line in text_content.splitlines() if search_query.lower() in line.lower()]
    
    if limit is not None:
        matches = matches[:limit]

    if not matches:
        return f"No matches found for '{search_query}' on {website}."
    
    return "\n".join(matches)