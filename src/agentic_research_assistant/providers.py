"""Search adapters with bounded requests and no third-party runtime dependencies."""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ProviderError(RuntimeError):
    """A sanitized, user-facing provider failure."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JsonClient:
    def __init__(self, timeout: float = 30, retries: int = 2) -> None:
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("Timeout must be between 0 and 120 seconds.")
        self.timeout = timeout
        self.retries = retries

    def post(self, url: str, api_key: str, payload: dict, *, headers: dict | None = None) -> dict:
        auth = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        request = Request(url, data=json.dumps(payload).encode(), headers={
            **auth, **(headers or {}), "Content-Type": "application/json",
            "User-Agent": "AgenticResearchAssistant/1.0",
        })
        for attempt in range(self.retries + 1):
            try:
                with build_opener(NoRedirects()).open(request, timeout=self.timeout) as response:
                    body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise ProviderError("Provider response exceeded the 8 MB limit.")
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ProviderError("Provider returned an invalid response object.")
                return result
            except HTTPError as exc:
                exc.close()
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(0.5 * 2 ** attempt)
                    continue
                raise ProviderError(f"Provider request failed (HTTP {exc.code}). Check credentials, quota, and model access.") from None
            except (URLError, TimeoutError, OSError):
                if attempt < self.retries:
                    time.sleep(0.5 * 2 ** attempt)
                    continue
                raise ProviderError("Provider connection failed or timed out.") from None
            except (ValueError, UnicodeError):
                raise ProviderError("Provider returned invalid JSON.") from None
        raise ProviderError("Provider request failed.")


def canonical_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
            return ""
        if any(c.isspace() or c in '<>"' for c in value):
            return ""
        port = parts.port
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        if port and (parts.scheme, port) not in (("https", 443), ("http", 80)):
            host += f":{port}"
        query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}))
        return urlunsplit((parts.scheme, host, parts.path or "/", query, ""))
    except ValueError:
        return ""


STOP_WORDS = set("a an the and or for to of in on is are how what with from this that should can do does related".split())


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", text.casefold()) if len(word) > 2 and word not in STOP_WORDS}


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    content: str
    score: float = 0.0
    content_kind: str = "full_text"
    published_at: str = ""


class SearchProvider(Protocol):
    def search(self, query: str, limit: int) -> list[SearchResult]: ...


class LocalSearchProvider:
    """Rank an explicitly imported JSON corpus by lexical query overlap."""
    def __init__(self, documents: list[dict]) -> None:
        if not isinstance(documents, list) or not 1 <= len(documents) <= 100:
            raise ValueError("Documents must be an array containing 1–100 objects.")
        self.documents: list[SearchResult] = []
        for index, document in enumerate(documents, 1):
            if not isinstance(document, dict):
                raise ValueError(f"Document {index} must be an object.")
            title, content = document.get("title"), document.get("content")
            url = document.get("url", "")
            if not isinstance(title, str) or not title.strip() or not isinstance(content, str) or not content.strip():
                raise ValueError(f"Document {index} requires a nonempty title and content.")
            if len(content) > 100_000 or len(title) > 500:
                raise ValueError(f"Document {index} exceeds the title or content size limit.")
            if not isinstance(url, str) or (url and not canonical_url(url)):
                raise ValueError(f"Document {index} has an invalid HTTP(S) URL.")
            self.documents.append(SearchResult(title.strip(), canonical_url(url), content.strip(), content_kind="imported"))

    def search(self, query: str, limit: int) -> list[SearchResult]:
        query_tokens = tokens(query)
        ranked = []
        for doc in self.documents:
            overlap = len(query_tokens & tokens(doc.title + " " + doc.content))
            if overlap:
                ranked.append(SearchResult(doc.title, doc.url, doc.content,
                                           overlap / max(1, len(query_tokens)), doc.content_kind))
        return sorted(ranked, key=lambda result: result.score, reverse=True)[:limit]


class TavilySearchProvider:
    def __init__(self, api_key: str, client: JsonClient | None = None) -> None:
        if not api_key.strip():
            raise ValueError("Set TAVILY_API_KEY to enable web search.")
        self.api_key = api_key
        self.client = client or JsonClient()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        payload = self.client.post("https://api.tavily.com/search", self.api_key, {
            "query": query, "max_results": limit, "search_depth": "basic",
            "include_raw_content": "text", "include_answer": False,
        })
        results = payload.get("results")
        if not isinstance(results, list):
            raise ProviderError("Search provider returned no results array.")
        normalized = []
        for item in results[:limit]:
            if not isinstance(item, dict):
                continue
            url = canonical_url(item.get("url", "")) if isinstance(item.get("url"), str) else ""
            title = item.get("title")
            raw, snippet = item.get("raw_content"), item.get("content")
            content = raw if isinstance(raw, str) and raw.strip() else snippet
            if not url or not isinstance(title, str) or not isinstance(content, str) or not content.strip():
                continue
            score = item.get("score", 0)
            score = float(score) if isinstance(score, (int, float)) and math.isfinite(score) else 0.0
            normalized.append(SearchResult(title[:500], url, content[:100_000], min(1, max(0, score)),
                                           "full_text" if content is raw else "snippet",
                                           str(item.get("published_date") or "")))
        return sorted(normalized, key=lambda result: result.score, reverse=True)
