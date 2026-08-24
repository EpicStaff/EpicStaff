# Web Search Tool
#
# `api_key` is NOT a function parameter: it is declared in args_schema.json
# with "input_type": "user_input", so it is seeded as a tool CONFIG variable
# (set once when the tool is configured for an agent) rather than an
# agent-callable argument. The sandbox executor injects configured values as
# module-level globals before this function runs — see
# `globals().get("api_key")` below.

SERPER_SEARCH_URL = "https://google.serper.dev/search"
DEFAULT_TIMEOUT_SECONDS = 15.0
MIN_QUERY_LENGTH = 2
MAX_RESULTS_CAP = 20
DEFAULT_MAX_RESULTS = 10
SNIPPET_MAX_CHARS = 300
SERPER_PAGE_SIZE_CAP = 100
DOMAIN_FILTER_MULTIPLIER = 3


def _passes_domain_filter(
    url: str,
    allowed_domains,
    blocked_domains,
) -> bool:
    import httpx

    try:
        host = (httpx.URL(url).host or "").lower()
    except Exception:
        host = ""

    if not host:
        return False

    def _matches(domain_list) -> bool:
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


def _format_results(results, total_available: int) -> str:
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


def main(
    query: str,
    allowed_domains: list | None = None,
    blocked_domains: list | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    **kwargs,
) -> str:
    """
    Search the web via the Serper API. Never raises: all failures are
    returned as readable error strings.
    """
    try:
        import httpx

        if not query or len(query) < MIN_QUERY_LENGTH:
            return f"Error: query must be at least {MIN_QUERY_LENGTH} characters long."

        api_key = globals().get("api_key")
        if not api_key:
            return (
                "Error: Serper API key is missing. Configure the 'api_key' field "
                "for this tool before using the Web Search Tool."
            )

        allowed_domains = allowed_domains or None
        blocked_domains = blocked_domains or None

        max_results = max_results or DEFAULT_MAX_RESULTS
        if max_results < 1:
            max_results = 1
        if max_results > MAX_RESULTS_CAP:
            max_results = MAX_RESULTS_CAP

        has_domain_filter = bool(allowed_domains or blocked_domains)
        request_num = max_results
        if has_domain_filter:
            request_num = min(max_results * DOMAIN_FILTER_MULTIPLIER, SERPER_PAGE_SIZE_CAP)

        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                response = client.post(
                    SERPER_SEARCH_URL,
                    json={"q": query, "num": request_num},
                    headers={
                        "X-API-KEY": api_key,
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError as e:
            return f"Error: could not reach Serper search API: {e}"

        if response.status_code != 200:
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
                if _passes_domain_filter(
                    item.get("link", ""), allowed_domains, blocked_domains
                )
            ]

        total_available = len(organic)
        capped = organic[:max_results]

        if not capped:
            return f"No results found for query '{query}'."

        return _format_results(capped, total_available)
    except Exception as e:
        return f"Error: web search failed. Unexpected exception: {e}"
