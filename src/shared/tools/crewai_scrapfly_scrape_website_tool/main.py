# Scrapfly Scrape Website Tool
#
# `api_key` is NOT a function parameter: args_schema.json declares it with
# "input_type": "user_input", so it is set in the tool configuration and the
# sandbox injects it as a module-level global -- the agent never sees it.
import logging
from typing import Any, Dict, Optional

from epicstaff_common import require_setting, safe_error_message

logger = logging.getLogger(__file__)

def main(
    url: str,
    scrape_format: str = "markdown",
    scrape_config: Optional[Dict[str, Any]] = None,
    ignore_scrape_failures: bool = False,
    **kwargs,
) -> Optional[str]:
    """
    Scrape a webpage using Scrapfly API.

    Args:
        url (str): Webpage URL.
        scrape_format (str, optional): Output format ("raw", "markdown", "text"). Defaults to "markdown".
        scrape_config (dict, optional): Scrapfly request configuration. Defaults to None.
        ignore_scrape_failures (bool, optional): Return None instead of an error message if scraping fails. Defaults to False.

    Returns:
        str | None: Scraped content, or an error message.
    """
    try:
        from scrapfly import ScrapflyClient, ScrapeConfig
    except ImportError:
        raise ImportError("`scrapfly-sdk` package is required. Install with `pip install scrapfly-sdk`")

    try:
        api_key = require_setting(globals(), "api_key")
    except RuntimeError as error:
        return f"Error: {safe_error_message(error)}"

    scrapfly = ScrapflyClient(key=api_key)
    scrape_config = scrape_config if scrape_config is not None else {}

    try:
        response = scrapfly.scrape(ScrapeConfig(url, format=scrape_format, **scrape_config))
        return response.scrape_result.get("content")
    except Exception as error:
        # Scrapfly passes the key as a query parameter, so its errors may carry it.
        message = f"Error scraping {url}: {safe_error_message(error)}"
        if ignore_scrape_failures:
            logger.error(message)
            return None
        return message
