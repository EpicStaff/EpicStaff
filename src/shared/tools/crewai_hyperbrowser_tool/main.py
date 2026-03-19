import os
from typing import Any, Dict, Optional, Literal, Union

def main(
    url: str,
    operation: Literal['scrape', 'crawl'] = 'scrape',
    params: Optional[Dict] = None,
    api_key: Optional[str] = None
) -> str:
    """
    Hyperbrowser web load tool.

    Args:
        url (str): Website URL
        operation (Literal['scrape','crawl']): Operation to perform
        params (Optional[Dict]): Additional parameters
        api_key (Optional[str]): Hyperbrowser API key, can also use HYPERBROWSER_API_KEY env var

    Returns:
        str: Scraped or crawled content

    Raises:
        RuntimeError: If API key not provided or Hyperbrowser package missing
    """
    api_key = api_key or os.getenv("HYPERBROWSER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "API key required. Provide it via 'api_key' argument or set HYPERBROWSER_API_KEY environment variable."
        )

    try:
        from hyperbrowser import Hyperbrowser
        from hyperbrowser.models.scrape import StartScrapeJobParams
        from hyperbrowser.models.crawl import StartCrawlJobParams
        from hyperbrowser.models.session import CreateSessionParams
        from hyperbrowser.models.scrape import ScrapeOptions
    except ImportError:
        raise RuntimeError(
            "`hyperbrowser` package not found. Install with `pip install hyperbrowser`"
        )

    hb = Hyperbrowser(api_key=api_key)
    params = params or {}

    # Prepare session and scrape options
    if "session_options" in params:
        params["session_options"] = CreateSessionParams(**params["session_options"])
    if "scrape_options" in params:
        params["scrape_options"] = ScrapeOptions(**params["scrape_options"])
        # validate formats
        formats = params["scrape_options"].formats if hasattr(params["scrape_options"], "formats") else []
        if not all(f in ["markdown", "html"] for f in formats):
            raise ValueError("formats can only contain 'markdown' or 'html'")

    def _extract_content(data: Union[Any, None]) -> str:
        if not data:
            return ""
        return getattr(data, "markdown", None) or getattr(data, "html", None) or ""

    # Run operation
    if operation == 'scrape':
        scrape_params = StartScrapeJobParams(url=url, **params)
        resp = hb.scrape.start_and_wait(scrape_params)
        return _extract_content(resp.data)
    elif operation == 'crawl':
        crawl_params = StartCrawlJobParams(url=url, **params)
        resp = hb.crawl.start_and_wait(crawl_params)
        content = ""
        if resp.data:
            for page in resp.data:
                page_content = _extract_content(page)
                if page_content:
                    content += f"\n{'-'*50}\nUrl: {page.url}\nContent:\n{page_content}\n"
        return content
    else:
        raise ValueError("Invalid operation. Must be 'scrape' or 'crawl'.")