import re
import requests
from typing import Optional

try:
    from bs4 import BeautifulSoup
except ImportError as e:
    raise ImportError(
        "beautifulsoup4 is required. Install with: pip install beautifulsoup4"
    ) from e


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/96.0.4664.110 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def main(website_url: str) -> str:
    """
    Fetch and scrape text content from a website.

    Args:
        website_url (str): Website URL to scrape.

    Returns:
        str: Scraped plain text content.
    """
    response = requests.get(
        website_url,
        timeout=15,
        headers=DEFAULT_HEADERS,
    )

    response.raise_for_status()
    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(response.text, "html.parser")

    text = "The following text is scraped website content:\n\n"
    text += soup.get_text(" ")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+\n\s+", "\n", text)

    return text