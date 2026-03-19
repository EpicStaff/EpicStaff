import requests
from bs4 import BeautifulSoup


HEADERS = {
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


def main(website_url: str, css_element: str) -> str:
    """
    Fetch a website and extract text content from elements
    matching the given CSS selector.

    Args:
        website_url (str): Website URL to scrape
        css_element (str): CSS selector for elements to extract

    Returns:
        str: Extracted text joined by newlines
    """
    response = requests.get(website_url, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, "html.parser")
    elements = soup.select(css_element)

    return "\n".join(element.get_text(strip=True) for element in elements)