"""
Async httpx client for the Mitti API (formerly SafetyCulture — the company
rebranded in 2026; see https://developer.mitti.com/docs/mitti-rebrand-for-developers).

Key design decisions:
- A single AsyncClient is reused per request context via a context manager helper.
- All HTTP errors are raised as descriptive Python exceptions with status codes.
- api.mitti.com is the long-term host; api.safetyculture.io still works with no
  announced shutoff date, so MITTI_BASE_URL takes precedence but
  SAFETYCULTURE_BASE_URL is honored for backward compatibility.
- Auth token resolution (per call, in order):
    1. An `x-mitti-token` header on the incoming MCP request (HTTP transport only —
       lets one shared deployment serve multiple callers/orgs, each supplying their
       own token, e.g. a Render-hosted server with no server-wide token configured).
    2. The MITTI_API_TOKEN / SAFETYCULTURE_API_TOKEN environment variable (stdio
       transport, or an HTTP deployment with one server-wide token).
  A plain `Authorization` header is deliberately NOT used for this, since FastMCP's
  get_http_headers() strips Authorization by default (it's reserved for MCP-level
  auth, not for this application-level pass-through).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import httpx
from dotenv import load_dotenv
from fastmcp.server.dependencies import get_http_headers

# Load .env on import so the module works in both dev and production.
load_dotenv()

BASE_URL = os.environ.get(
    "MITTI_BASE_URL",
    os.environ.get("SAFETYCULTURE_BASE_URL", "https://api.mitti.com"),
)

# Timeouts: connect 10s, read 30s, write 10s, pool 5s
_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class MittiAPIError(Exception):
    """Raised when the Mitti API returns an unexpected status."""

    def __init__(self, status_code: int, message: str, endpoint: str = "") -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(f"Mitti API error {status_code} on {endpoint}: {message}")


def _get_token() -> str:
    """Return the API token, preferring a per-request header over the server env var.

    get_http_headers() never raises — it returns {} outside an HTTP request (e.g.
    stdio transport, or a background task), so this is safe to call unconditionally.
    """
    header_token = get_http_headers().get("x-mitti-token")
    token = header_token or os.environ.get("MITTI_API_TOKEN") or os.environ.get("SAFETYCULTURE_API_TOKEN")
    if not token:
        raise EnvironmentError(
            "No Mitti API token found. Either send an 'x-mitti-token' header with your "
            "MCP request, or set MITTI_API_TOKEN in the server's environment / .env file."
        )
    return token


def _build_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@asynccontextmanager
async def api_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Async context manager that yields a configured httpx.AsyncClient.

    Usage::

        async with api_client() as client:
            resp = await client.get("/audits/search")
    """
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        headers=_build_headers(),
        timeout=_DEFAULT_TIMEOUT,
        follow_redirects=True,
    ) as client:
        yield client


async def handle_response(resp: httpx.Response, endpoint: str = "") -> dict[str, Any]:
    """
    Parse a response and raise a descriptive error for non-2xx statuses.

    Returns the parsed JSON body as a dict on success.
    """
    if resp.status_code == 401:
        raise MittiAPIError(
            401,
            "Unauthorized — check that your Mitti API token (x-mitti-token header or "
            "MITTI_API_TOKEN env var) is valid and not expired.",
            endpoint,
        )
    if resp.status_code == 403:
        raise MittiAPIError(
            403,
            "Forbidden — your API token does not have permission for this operation.",
            endpoint,
        )
    if resp.status_code == 404:
        raise MittiAPIError(
            404,
            "Not found — the requested resource does not exist.",
            endpoint,
        )
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "unknown")
        raise MittiAPIError(
            429,
            f"Rate limited — retry after {retry_after} seconds.",
            endpoint,
        )
    if resp.status_code >= 500:
        raise MittiAPIError(
            resp.status_code,
            f"Mitti server error: {resp.text[:200]}",
            endpoint,
        )

    resp.raise_for_status()

    # Some endpoints return 204 No Content — return empty dict.
    if not resp.content:
        return {}

    return resp.json()
