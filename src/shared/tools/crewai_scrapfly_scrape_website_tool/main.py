import os
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__file__)

def main(
    url: str,
    api_key: str,
    scrape_format: str = "markdown",
    scrape_config: Optional[Dict[str, Any]] = None,
    ignore_scrape_failures: bool = False,
) -> Optional[str]:
    """
    Scrape a webpage using Scrapfly API.

    Args:
        url (str): Webpage URL.
        api_key (str): Scrapfly API key.
        scrape_format (str, optional): Output format ("raw", "markdown", "text"). Defaults to "markdown".
        scrape_config (dict, optional): Scrapfly request configuration. Defaults to None.
        ignore_scrape_failures (bool, optional): Ignore errors and return None if scraping fails. Defaults to False.

    Returns:
        str | None: Scraped content.
    """
    try:
        from scrapfly import ScrapflyClient, ScrapeConfig
    except ImportError:
        raise ImportError("`scrapfly-sdk` package is required. Install with `pip install scrapfly-sdk`")

    scrapfly = ScrapflyClient(key=api_key)
    scrape_config = scrape_config if scrape_config is not None else {}

    try:
        response = scrapfly.scrape(ScrapeConfig(url, format=scrape_format, **scrape_config))
        return response.scrape_result.get("content")
    except Exception as e:
        if ignore_scrape_failures:
            logger.error(f"Error scraping {url}: {e}")
            return None
        else:
            raise e