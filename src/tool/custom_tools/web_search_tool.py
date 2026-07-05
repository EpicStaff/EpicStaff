from typing import Any, Type

import httpx
from crewai.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field

SERPER_SEARCH_URL = "https://google.serper.dev/search"
DEFAULT_TIMEOUT_SECONDS = 15.0
MIN_QUERY_LENGTH = 2
MAX_RESULTS_CAP = 20
DEFAULT_MAX_RESULTS = 10
SNIPPET_MAX_CHARS = 300
SERPER_PAGE_SIZE_CAP = 100
DOMAIN_FILTER_MULTIPLIER = 3


class WebSearchToolSchema(BaseModel):
    """Input for WebSearchTool."""

    query: str = Field(
        ..., min_length=MIN_QUERY_LENGTH, description="The search query."
    )
    allowed_domains: list[str] | None = Field(
        None, description="Only return results from these domains."
    )
    blocked_domains: list[str] | None = Field(
        None, description="Never return results from these domains."
    )
    max_results: int = Field(
        DEFAULT_MAX_RESULTS,
        ge=1,
        le=MAX_RESULTS_CAP,
        description="Maximum number of results to return. 1-20, default 10.",
    )


class WebSearchTool(BaseTool):
    name: str = "Search the web"
    description: str = ""
    args_schema: Type[BaseModel] = WebSearchToolSchema

    api_key: str | None = None
    """Serper API key, injected via tool_init_configuration (config field 'api_key')."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._generate_description()

    def _run(self, **kwargs: Any) -> str:
        try:
            return self._run_impl(**kwargs)
        except Exception as e:
            logger.error("WebSearchTool failed unexpectedly: {}", e)
            return f"Error: web search failed. Unexpected exception: {e}"

    def _run_impl(self, **kwargs: Any) -> str:
        query = kwargs.get("query")
        if not query or len(query) < MIN_QUERY_LENGTH:
            return (
                f"Error: query must be at least {MIN_QUERY_LENGTH} characters long."
            )

        if not self.api_key:
            return (
                "Error: Serper API key is missing. Configure the 'api_key' field "
                "for this tool before using WebSearchTool."
            )

        allowed_domains = kwargs.get("allowed_domains") or None
        blocked_domains = kwargs.get("blocked_domains") or None

        max_results = kwargs.get("max_results") or DEFAULT_MAX_RESULTS
        if max_results < 1:
            max_results = 1
        if max_results > MAX_RESULTS_CAP:
            max_results = MAX_RESULTS_CAP

        has_domain_filter = bool(allowed_domains or blocked_domains)
        request_num = max_results
        if has_domain_filter:
            # Over-fetch so that after client-side domain filtering we still have
            # enough candidates left to satisfy max_results (Serper has no
            # server-side domain filter, so filtering happens post-hoc below).
            request_num = min(max_results * DOMAIN_FILTER_MULTIPLIER, SERPER_PAGE_SIZE_CAP)

        try:
            client = self._build_client()
            with client:
                response = client.post(
                    SERPER_SEARCH_URL,
                    json={"q": query, "num": request_num},
                    headers={
                        "X-API-KEY": self.api_key,
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError as e:
            logger.error("WebSearchTool request to Serper failed: {}", e)
            return f"Error: could not reach Serper search API: {e}"

        if response.status_code != 200:
            logger.error(
                "WebSearchTool Serper returned status {}: {}",
                response.status_code,
                response.text,
            )
            return (
                f"Error: Serper API returned status {response.status_code}: "
                f"{response.text[:300]}"
            )

        try:
            data = response.json()
        except ValueError as e:
            return f"Error: could not parse Serper API response as JSON: {e}"

        organic = data.get("organic") or []

        if has_domain_filter:
            organic = [
                item
                for item in organic
                if self._passes_domain_filter(
                    item.get("link", ""), allowed_domains, blocked_domains
                )
            ]

        total_available = len(organic)
        capped = organic[:max_results]

        if not capped:
            return f"No results found for query '{query}'."

        return self._format_results(capped, total_available, query)

    @staticmethod
    def _format_results(
        results: list[dict], total_available: int, query: str
    ) -> str:
        rendered = []
        for idx, item in enumerate(results, start=1):
            title = item.get("title") or "(no title)"
            link = item.get("link") or ""
            snippet = item.get("snippet") or ""
            if len(snippet) > SNIPPET_MAX_CHARS:
                snippet = snippet[:SNIPPET_MAX_CHARS] + "…"
            rendered.append(f"{idx}. {title}\n   {link}\n   {snippet}")

        result_text = "\n".join(rendered)

        if total_available > len(results):
            result_text += f"\n(showing {len(results)} of {total_available} results)"

        return result_text

    @staticmethod
    def _passes_domain_filter(
        url: str,
        allowed_domains: list[str] | None,
        blocked_domains: list[str] | None,
    ) -> bool:
        try:
            host = (httpx.URL(url).host or "").lower()
        except Exception:
            host = ""

        if not host:
            return False

        def _matches(domain_list: list[str]) -> bool:
            for domain in domain_list:
                domain = domain.lower().lstrip(".")
                if host == domain or host.endswith(f".{domain}"):
                    return True
            return False

        if blocked_domains and _matches(blocked_domains):
            return False

        if allowed_domains:
            return _matches(allowed_domains)

        return True

    def _build_client(self) -> httpx.Client:
        """Isolated seam so tests can inject a mocked transport."""
        return httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS)
