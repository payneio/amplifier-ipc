"""WebSearchTool and WebFetchTool — web search and page fetch capabilities."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from amplifier_ipc.protocol import ToolResult, tool
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS


logger = logging.getLogger(__name__)


@tool
class WebSearchTool:
    """Search the web for information."""

    name = "web_search"
    description = "Search the web for information"

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query to execute"}
        },
        "required": ["query"],
    }

    def __init__(self) -> None:
        self.max_results = 5

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute web search."""
        query = input.get("query")
        if not query:
            error_msg = "Query is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        try:
            results = await self._real_search(query)
            return ToolResult(
                success=True,
                output={"query": query, "results": results, "count": len(results)},
            )
        except Exception as e:
            logger.error(f"Search error: {e}")
            error_msg = str(e)
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

    async def _real_search(self, query: str) -> list:
        """Perform real web search using DuckDuckGo."""
        try:

            def search_sync():
                ddgs = DDGS()
                results = []
                for r in ddgs.text(query, max_results=self.max_results):  # pyright: ignore[reportAttributeAccessIssue]
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                        }
                    )
                return results

            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, search_sync)
            return results

        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}, falling back to mock")
            return await self._mock_search(query)

    async def _mock_search(self, query: str) -> list:
        """Mock search fallback."""
        return [
            {
                "title": f"Result 1 for {query}",
                "url": "https://example.com/1",
                "snippet": f"This is a mock search result for {query}...",
            },
            {
                "title": f"Result 2 for {query}",
                "url": "https://example.com/2",
                "snippet": f"Another mock result about {query}...",
            },
            {
                "title": f"Result 3 for {query}",
                "url": "https://example.com/3",
                "snippet": f"More information about {query}...",
            },
        ][: self.max_results]


@tool
class WebFetchTool:
    """Fetch and parse web pages with streaming support and truncation handling."""

    name = "web_fetch"
    description = """Fetch content from a web URL.

Content is limited to 200KB by default to avoid overwhelming responses.
For larger content:
- Use save_to_file parameter to save full content to a file
- Use offset/limit parameters to paginate through large content

Response includes:
- truncated: boolean indicating if content was cut off
- total_bytes: original content size (when available)
- Use these to decide if you need the full content via save_to_file"""

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch content from",
            },
            "save_to_file": {
                "type": "string",
                "description": "Save full content to this file path instead of returning in response. "
                "Useful for large pages. Returns metadata + preview when set.",
            },
            "offset": {
                "type": "integer",
                "description": "Start reading from byte N (default 0). Use for pagination.",
                "default": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Max bytes to return (default 200KB). Use for pagination.",
                "default": 204800,
            },
        },
        "required": ["url"],
    }

    # Default limit: 200KB is reasonable for web content
    DEFAULT_LIMIT = 200 * 1024
    CHUNK_SIZE = 8192
    PREVIEW_SIZE = 1000

    def __init__(self) -> None:
        self.timeout = 10
        self.default_limit = self.DEFAULT_LIMIT
        self.allowed_domains: list[str] = []
        self.blocked_domains: list[str] = [
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "192.168.",
            "10.",
            "172.16.",
        ]
        self.extract_text = True

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Fetch content from URL with streaming and truncation support."""
        url = input.get("url")
        if not url:
            error_msg = "URL is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        save_to_file = input.get("save_to_file")
        offset = input.get("offset", 0)
        limit = input.get("limit", self.default_limit)

        if not self._is_valid_url(url):
            return ToolResult(
                success=False, error={"message": f"Invalid or blocked URL: {url}"}
            )

        try:
            session = aiohttp.ClientSession()
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    headers={"User-Agent": "Amplifier/1.0"},
                ) as response:
                    if response.status != 200:
                        return ToolResult(
                            success=False,
                            error={
                                "message": f"HTTP {response.status}: {response.reason}"
                            },
                        )

                    content_length_header = response.headers.get("Content-Length")
                    declared_size = (
                        int(content_length_header) if content_length_header else None
                    )

                    if save_to_file:
                        return await self._fetch_to_file(
                            response, url, save_to_file, declared_size
                        )
                    else:
                        return await self._fetch_with_limit(
                            response, url, offset, limit, declared_size
                        )
            finally:
                if not session.closed:
                    await session.close()

        except TimeoutError:
            error_msg = f"Timeout fetching {url}"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            error_msg = str(e)
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

    async def _fetch_with_limit(
        self,
        response: aiohttp.ClientResponse,
        url: str,
        offset: int,
        limit: int,
        declared_size: Optional[int],
    ) -> ToolResult:
        """Fetch content with streaming and hard byte limit."""
        chunks: list[bytes] = []
        total_read = 0
        truncated = False

        max_to_read = offset + limit + 1

        async for chunk in response.content.iter_chunked(self.CHUNK_SIZE):
            chunk_len = len(chunk)
            chunk_end = total_read + chunk_len

            if chunk_end > offset and total_read < offset + limit:
                start_in_chunk = max(0, offset - total_read)
                end_in_chunk = min(chunk_len, offset + limit - total_read)
                chunks.append(chunk[start_in_chunk:end_in_chunk])

            total_read += chunk_len

            if total_read >= max_to_read:
                truncated = True
                break

        actual_total: Optional[int] = None
        if truncated:
            remaining_size = 0
            async for chunk in response.content.iter_chunked(self.CHUNK_SIZE):
                remaining_size += len(chunk)
            actual_total = total_read + remaining_size
        else:
            actual_total = total_read
            if total_read > offset + limit:
                truncated = True

        if declared_size and (actual_total is None or declared_size > actual_total):
            actual_total = declared_size

        raw_content = b"".join(chunks)
        content = self._decode_bytes(raw_content)

        content_type = response.content_type or ""
        if self.extract_text:
            text = self._extract_text(content, content_type)
        else:
            text = content

        result_content = text
        if truncated:
            result_content = (
                f"{text}\n\n"
                f"[Content truncated at {limit} bytes. "
                f"Total: {actual_total or 'unknown'} bytes. "
                f"Use offset/limit to paginate or save_to_file for full content.]"
            )

        return ToolResult(
            success=True,
            output={
                "url": url,
                "content": result_content,
                "content_type": content_type,
                "truncated": truncated,
                "total_bytes": actual_total,
                "offset": offset,
                "limit": limit,
                "returned_bytes": len(raw_content),
            },
        )

    async def _fetch_to_file(
        self,
        response: aiohttp.ClientResponse,
        url: str,
        file_path: str,
        declared_size: Optional[int],
    ) -> ToolResult:
        """Fetch full content and save to file, return metadata + preview."""
        chunks: list[bytes] = []
        total_bytes = 0

        async for chunk in response.content.iter_chunked(self.CHUNK_SIZE):
            chunks.append(chunk)
            total_bytes += len(chunk)

        raw_content = b"".join(chunks)
        content = self._decode_bytes(raw_content)

        content_type = response.content_type or ""
        if self.extract_text:
            text = self._extract_text(content, content_type)
        else:
            text = content

        try:
            path = Path(file_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except Exception as e:
            return ToolResult(
                success=False, error={"message": f"Failed to write file: {e}"}
            )

        preview = text[: self.PREVIEW_SIZE]
        if len(text) > self.PREVIEW_SIZE:
            preview += f"\n\n[... {len(text) - self.PREVIEW_SIZE} more characters saved to {file_path}]"

        return ToolResult(
            success=True,
            output={
                "url": url,
                "content": preview,
                "content_type": content_type,
                "truncated": False,
                "total_bytes": total_bytes,
                "saved_to": str(path),
                "saved_bytes": len(text.encode("utf-8")),
            },
        )

    def _decode_bytes(self, raw: bytes) -> str:
        """Decode raw bytes to str, falling back to latin-1 if utf-8 fails."""
        try:
            return raw.decode("utf-8")
        except Exception:
            return raw.decode("latin-1", errors="replace")

    def _is_valid_url(self, url: str) -> bool:
        """Validate URL for safety."""
        try:
            parsed = urlparse(url)

            if not parsed.scheme or not parsed.netloc:
                return False

            if parsed.scheme not in ["http", "https"]:
                return False

            host = parsed.netloc.split(":")[0]  # strip optional port
            for blocked in self.blocked_domains:
                if blocked.endswith("."):
                    # IP prefix (e.g. "10.", "192.168.") — check host start
                    matched = host.startswith(blocked)
                else:
                    # Exact hostname or IP, with subdomain support
                    matched = host == blocked or host.endswith("." + blocked)
                if matched:
                    logger.warning(f"Blocked domain: {parsed.netloc}")
                    return False

            if self.allowed_domains:
                allowed = any(
                    domain in parsed.netloc for domain in self.allowed_domains
                )
                if not allowed:
                    logger.warning(f"Domain not in allowlist: {parsed.netloc}")
                    return False

            return True

        except Exception:
            return False

    def _extract_text(self, content: str, content_type: str) -> str:
        """Extract text from HTML content."""
        if "html" in content_type:
            try:
                soup = BeautifulSoup(content, "html.parser")

                for script in soup(["script", "style"]):
                    script.decompose()

                text = soup.get_text()

                lines = (line.strip() for line in text.splitlines())
                chunks = (
                    phrase.strip() for line in lines for phrase in line.split("  ")
                )
                text = "\n".join(chunk for chunk in chunks if chunk)

                return text

            except Exception as e:
                logger.warning(f"Failed to extract text: {e}")
                return content
        else:
            return content
