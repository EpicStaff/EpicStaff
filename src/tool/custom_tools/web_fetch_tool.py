import ipaddress
import socket
import time
from typing import Any, Type

import httpx
import litellm
import trafilatura
from crewai.tools import BaseTool
from loguru import logger
from markdownify import markdownify as md
from pydantic import BaseModel, Field

DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
DOWNLOAD_CAP_BYTES = 5 * 1024 * 1024
MARKDOWN_LLM_CAP_BYTES = 100 * 1024
CACHE_TTL_SECONDS = 15 * 60

_HTML_CONTENT_TYPES = ("", "text/html", "application/xhtml+xml")
_PASSTHROUGH_PREFIXES = ("text/",)
_PASSTHROUGH_CONTENT_TYPES = ("application/json", "application/xml")

# Module-level in-memory cache of the markdown stage only: url -> (markdown, monotonic_ts)
_MARKDOWN_CACHE: dict[str, tuple[str, float]] = {}


class WebFetchToolSchema(BaseModel):
    """Input for WebFetchTool."""

    url: str = Field(
        ..., description="URL to fetch. http and https only; http is upgraded to https."
    )
    prompt: str | None = Field(
        None,
        description=(
            "If given, an extraction LLM answers this prompt over the fetched "
            "markdown. If omitted, the raw markdown is returned."
        ),
    )


class WebFetchTool(BaseTool):
    name: str = "Fetch a URL and convert it to markdown"
    description: str = ""
    args_schema: Type[BaseModel] = WebFetchToolSchema

    config: dict | None = None
    """LLM configuration injected via tool_init_configuration (config field
    'llm_config'), shaped like {"llm": {"provider": ..., "config": {"model": ...}}}."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._generate_description()

    def _run(self, **kwargs: Any) -> str:
        try:
            return self._run_impl(**kwargs)
        except Exception as e:
            logger.error("WebFetchTool failed unexpectedly: {}", e)
            return f"Error: failed to fetch URL. Unexpected exception: {e}"

    def _run_impl(self, **kwargs: Any) -> str:
        url = kwargs.get("url")
        if not url:
            return "Error: url argument is mandatory and was not given to the tool."

        prompt = kwargs.get("prompt")

        try:
            parsed = httpx.URL(url)
        except Exception as e:
            return f"Error: invalid URL '{url}': {e}"

        if parsed.scheme not in ("http", "https"):
            return (
                f"Error: unsupported URL scheme '{parsed.scheme}'. Only http and "
                "https URLs are supported."
            )

        normalized_url = url
        if parsed.scheme == "http":
            normalized_url = "https://" + url.split("://", 1)[1]

        cached_markdown = self._get_cached(normalized_url)
        if cached_markdown is not None:
            logger.debug("WebFetchTool cache hit for {}", normalized_url)
            markdown = cached_markdown
        else:
            markdown, error = self._fetch_and_convert(normalized_url)
            if error:
                return error
            self._set_cache(normalized_url, markdown)

        if not prompt:
            return markdown

        llm_config = self._get_llm_config()
        if llm_config is None:
            return (
                "Error: 'llm_config' is not configured for this tool. Configure "
                "the 'llm_config' field to use the prompt argument."
            )

        return self._answer_with_llm(markdown, prompt, llm_config)

    # ------------------------------------------------------------------
    # Fetch + SSRF guard + redirect handling
    # ------------------------------------------------------------------

    def _fetch_and_convert(self, url: str) -> tuple[str | None, str | None]:
        current_url = url
        original_host = httpx.URL(url).host

        client = self._build_client()
        with client:
            for _hop in range(MAX_REDIRECTS + 1):
                ok, err = self._ssrf_guard(current_url)
                if not ok:
                    return None, err

                try:
                    with client.stream("GET", current_url) as response:
                        if 300 <= response.status_code < 400:
                            location = response.headers.get("location")
                            if not location:
                                return (
                                    None,
                                    f"Error: redirect response from {current_url} "
                                    "had no Location header.",
                                )
                            next_url = str(httpx.URL(current_url).join(location))
                            next_host = httpx.URL(next_url).host
                            if next_host != original_host:
                                return (
                                    None,
                                    f"Redirects to {next_url} — call again with that URL",
                                )
                            current_url = next_url
                            continue

                        if response.status_code >= 400:
                            return (
                                None,
                                f"Error: fetching {current_url} failed with status "
                                f"{response.status_code}.",
                            )

                        content_type = response.headers.get("content-type", "")
                        body = bytearray()
                        truncated = False
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > DOWNLOAD_CAP_BYTES:
                                truncated = True
                                break

                        return self._convert_body(
                            bytes(body), content_type, truncated, current_url
                        )
                except httpx.HTTPError as e:
                    return None, f"Error: network failure while fetching {current_url}: {e}"

            return (
                None,
                f"Error: exceeded max redirects ({MAX_REDIRECTS}) while fetching {url}.",
            )

    def _build_client(self) -> httpx.Client:
        """Isolated seam so tests can inject a mocked transport."""
        return httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=False)

    @staticmethod
    def _ssrf_guard(url: str) -> tuple[bool, str | None]:
        parsed = httpx.URL(url)
        if parsed.scheme not in ("http", "https"):
            return (
                False,
                f"Error: unsupported URL scheme '{parsed.scheme}' — only http and "
                "https are allowed.",
            )

        host = parsed.host
        if not host:
            return False, f"Error: could not determine host from URL {url}."

        try:
            addr_infos = socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            return False, f"Error: could not resolve host '{host}': {e}"

        for info in addr_infos:
            raw_ip = info[4][0]
            try:
                ip = ipaddress.ip_address(raw_ip)
            except ValueError:
                continue

            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return (
                    False,
                    f"Error: refusing to fetch {url} — host '{host}' resolves to a "
                    f"private/internal address ({raw_ip}). Blocked to prevent SSRF.",
                )

        return True, None

    # ------------------------------------------------------------------
    # Content conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_body(
        body: bytes, content_type: str, truncated: bool, url: str
    ) -> tuple[str | None, str | None]:
        content_type_main = content_type.split(";")[0].strip().lower()

        note = ""
        if truncated:
            cap_mb = DOWNLOAD_CAP_BYTES // (1024 * 1024)
            note = f"\n\n(download truncated at the {cap_mb} MB cap)"

        if content_type_main in _HTML_CONTENT_TYPES:
            text = body.decode("utf-8", errors="replace")

            markdown = None
            try:
                markdown = trafilatura.extract(
                    text,
                    output_format="markdown",
                    include_links=True,
                    include_tables=True,
                    url=url,
                )
            except Exception as e:
                logger.warning(
                    "WebFetchTool trafilatura extraction failed for {}: {}", url, e
                )
                markdown = None

            if not markdown:
                try:
                    markdown = md(text)
                except Exception as e:
                    return None, f"Error: could not convert HTML from {url} to markdown: {e}"

            return markdown + note, None

        if content_type_main.startswith(_PASSTHROUGH_PREFIXES) or (
            content_type_main in _PASSTHROUGH_CONTENT_TYPES
        ):
            text = body.decode("utf-8", errors="replace")
            return text + note, None

        return (
            None,
            f"Error: cannot convert binary content of type '{content_type_main}' "
            f"from {url} to text.",
        )

    # ------------------------------------------------------------------
    # Cache (markdown stage only, 15 min TTL)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_cached(url: str) -> str | None:
        entry = _MARKDOWN_CACHE.get(url)
        if entry is None:
            return None

        markdown, cached_at = entry
        if time.monotonic() - cached_at > CACHE_TTL_SECONDS:
            del _MARKDOWN_CACHE[url]
            return None

        return markdown

    @staticmethod
    def _set_cache(url: str, markdown: str) -> None:
        _MARKDOWN_CACHE[url] = (markdown, time.monotonic())

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    def _get_llm_config(self) -> dict | None:
        if not self.config:
            return None

        llm_section = self.config.get("llm")
        if not llm_section:
            return None

        inner = llm_section.get("config") or {}
        model = inner.get("model")
        if not model:
            return None

        return {
            "model": model,
            "api_key": inner.get("api_key"),
            "base_url": inner.get("base_url"),
            "temperature": inner.get("temperature"),
            "max_tokens": inner.get("max_tokens"),
            "timeout": inner.get("timeout"),
        }

    @staticmethod
    def _answer_with_llm(markdown: str, prompt: str, llm_config: dict) -> str:
        truncated_markdown = markdown
        if len(markdown.encode("utf-8")) > MARKDOWN_LLM_CAP_BYTES:
            truncated_markdown = (
                markdown[:MARKDOWN_LLM_CAP_BYTES]
                + "\n\n(content truncated to 100 KB before sending to the model)"
            )

        completion_kwargs = {
            k: v for k, v in llm_config.items() if v is not None and k != "model"
        }

        messages = [
            {
                "role": "system",
                "content": "You answer questions about the following web page content.",
            },
            {
                "role": "user",
                "content": f"{prompt}\n\n---\n\n{truncated_markdown}",
            },
        ]

        try:
            response = litellm.completion(
                model=llm_config["model"], messages=messages, **completion_kwargs
            )
        except Exception as e:
            logger.error("WebFetchTool litellm completion failed: {}", e)
            return f"Error: LLM extraction failed: {e}"

        try:
            return response.choices[0].message.content
        except (AttributeError, IndexError, KeyError) as e:
            return f"Error: could not parse LLM response: {e}"
