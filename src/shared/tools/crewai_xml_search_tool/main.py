# XML Search Tool
import xml.etree.ElementTree as ET
import requests
from typing import Optional
from urllib.parse import urlparse

def main(
    search_query: str,
    xml: str,
    similarity_threshold: Optional[float] = None,
    limit: Optional[int] = None
) -> str:
    """
    Search for a query in the XML file content.

    Args:
        search_query (str): The query to search.
        xml (str): http(s) URL of the XML file.
        similarity_threshold (float, optional): Threshold for similarity matching (unused in this basic version).
        limit (int, optional): Maximum number of matches to return.

    Returns:
        str: Matching XML snippets or elements.
    """
    try:
        url = urlparse(xml)
        if url.scheme not in ("http", "https") or not url.netloc:
            return f"Error: '{xml}' is not an http(s) URL"
        response = requests.get(xml, timeout=10)
        response.raise_for_status()
        content = response.text

        tree = ET.ElementTree(ET.fromstring(content))
        root = tree.getroot()

        # Search recursively for elements containing the search_query
        matches = []

        def search_element(elem):
            if search_query.lower() in (elem.text or "").lower():
                matches.append(ET.tostring(elem, encoding="unicode"))
            for child in elem:
                search_element(child)

        search_element(root)

        if limit is not None:
            matches = matches[:limit]

        if not matches:
            return "No matches found."

        return "\n---\n".join(matches)

    except Exception as e:
        return f"Error: {str(e)}"