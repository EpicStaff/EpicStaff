# Jina Website Reader Tool
import requests

def main(website_url: str, api_key: str) -> str:
    """
    Read website content using Jina.ai and return markdown content.

    Args:
        website_url (str): The URL of the website to read.
        api_key (str): Your Jina.ai API key.

    Returns:
        str: Content from Jina.ai or error message.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.get(f"https://r.jina.ai/{website_url}", headers=headers, timeout=15)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        return f"Error: {e}"