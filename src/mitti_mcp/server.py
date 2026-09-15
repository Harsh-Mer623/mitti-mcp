"""
Mitti MCP Server — main entry point.

Mounts all tool sub-servers (inspections, templates, actions, users)
into a single FastMCP application using server composition.

Run via:
    uv run python -m mitti_mcp.server            # stdio (Claude Desktop)
    uv run uvicorn mitti_mcp.server:http_app     # HTTP + CORS (Inspector)
    fastmcp install src/mitti_mcp/server.py      # install into Claude Desktop
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.apps.approval import Approval
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

# Load environment variables from .env file before anything else.
load_dotenv()

# Add the parent directory of this package to sys.path so that absolute imports
# like `from mitti_mcp...` work when run directly or via fastmcp CLI.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Import sub-server instances from each tool module.
# ---------------------------------------------------------------------------
from mitti_mcp.tools.actions import mcp as actions_mcp
from mitti_mcp.tools.inspections import mcp as inspections_mcp
from mitti_mcp.tools.templates import mcp as templates_mcp
from mitti_mcp.tools.users import mcp as users_mcp

# ---------------------------------------------------------------------------
# Create the root MCP application.
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="Mitti MCP",
    instructions=(
        "You are connected to a Mitti (formerly SafetyCulture) MCP server that exposes "
        "tools for managing inspections, templates, actions, and users in a Mitti organization. "
        "\n\n"
        "Available tool groups:\n"
        "  • Inspections — list, get, complete inspections; get web report links\n"
        "  • Templates   — list templates, get template definitions\n"
        "  • Actions     — list, get, create, update status/title of actions\n"
        "  • Users       — list, search users; get_current_user is unsupported (see its description)\n"
        "\n"
        "All tools require MITTI_API_TOKEN to be set in the environment.\n"
        "\n"
        "Known API limitations (see each tool's description for detail): list_inspections "
        "only returns audit_id/template_id/date_modified (use get_inspection for full detail); "
        "action priority is an org-specific ID, not a fixed label; there is no 'current user' "
        "endpoint.\n"
        "\n"
        "Write operations — complete_inspection, create_action, update_action_status, "
        "update_action_title — modify live Mitti data. Before calling any of "
        "them, call request_approval with a summary of the change and wait for the "
        "user's 'I selected: Approve' or 'I selected: Reject' response. Only proceed "
        "with the write tool after an Approve; on Reject, acknowledge and stop."
    ),
)

# ---------------------------------------------------------------------------
# Human-in-the-loop approval gate for write operations. Registers a
# `request_approval` tool that renders an Approve/Reject card in the client;
# the LLM is instructed (above) to call it before any write tool. This is an
# advisory gate, not an enforcement mechanism — server-side validation still
# lives in each tool/client.py.
# ---------------------------------------------------------------------------
mcp.add_provider(Approval(title="Confirm Mitti Change"))

# ---------------------------------------------------------------------------
# Middleware — cross-cutting error handling, request logging, and rate
# limiting applied to every tool call across all mounted sub-servers.
# Order matters: first added is outermost, so errors raised by logging or
# rate limiting are still caught and logged consistently.
# ---------------------------------------------------------------------------
mcp.add_middleware(ErrorHandlingMiddleware(include_traceback=False))
mcp.add_middleware(LoggingMiddleware(include_payload_length=True))
mcp.add_middleware(
    RateLimitingMiddleware(
        max_requests_per_second=float(os.environ.get("MITTI_MCP_RATE_LIMIT_RPS", "10")),
        global_limit=True,
    )
)

# ---------------------------------------------------------------------------
# Mount tool sub-servers with prefix/namespace based on FastMCP version.
# Compatible with both FastMCP 2.x (prefix) and FastMCP 3.x (namespace).
# ---------------------------------------------------------------------------
import inspect

_mount_sig = inspect.signature(mcp.mount)
if "namespace" in _mount_sig.parameters:
    mcp.mount(inspections_mcp, namespace="inspections")
    mcp.mount(templates_mcp, namespace="templates")
    mcp.mount(actions_mcp, namespace="actions")
    mcp.mount(users_mcp, namespace="users")
else:
    mcp.mount(inspections_mcp, prefix="inspections")
    mcp.mount(templates_mcp, prefix="templates")
    mcp.mount(actions_mcp, prefix="actions")
    mcp.mount(users_mcp, prefix="users")

# ---------------------------------------------------------------------------
# HTTP app with CORS — used by the MCP Inspector browser UI.
# The Inspector sends OPTIONS preflight requests; without CORS the browser
# blocks all cross-origin requests (localhost:6274 → localhost:8000).
# ---------------------------------------------------------------------------
try:
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    _cors_middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "mcp-protocol-version",
                "mcp-session-id",
                "Authorization",
                "Content-Type",
            ],
            expose_headers=["mcp-session-id"],
        )
    ]
    # http_app is the ASGI application used when running with HTTP transport.
    # Export it at module level so uvicorn / gunicorn can reference it directly:
    #   uvicorn mitti_mcp.server:http_app --port 8000
    http_app = mcp.http_app(middleware=_cors_middleware)
except ImportError:
    # starlette not available — CORS disabled (fine for stdio-only deployments)
    http_app = None  # type: ignore[assignment]()


def main() -> None:
    """Entry point for the `mitti-mcp` CLI script."""
    # Verify the token is available before starting.
    token = os.environ.get("MITTI_API_TOKEN") or os.environ.get("SAFETYCULTURE_API_TOKEN")
    if not token:
        print(
            "ERROR: MITTI_API_TOKEN environment variable is not set.\n"
            "  1. Copy .env.example to .env\n"
            "  2. Set MITTI_API_TOKEN=your_token_here\n"
            "  3. Re-run the server."
        )
        raise SystemExit(1)

    mcp.run()


if __name__ == "__main__":
    main()
