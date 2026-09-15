"""
User tools for the Mitti MCP server.

Endpoints used (verified against https://developer.mitti.com/llms.txt, Sep 2026):
  - POST /users/v1/users/list  — list/search users (replaces deprecated
    GET /users/{user_id} and POST /users/search)

IMPORTANT — API limitations found during migration:
  - The current Users API has no "current authenticated user" / "me" endpoint.
    get_current_user cannot be implemented against a real endpoint; it returns
    a clear failure explaining this instead of guessing at one.
  - /users/v1/users/list has no free-text search — only exact filters
    (user_ids, usernames, field_attributes, seat_types, statuses). search_users
    is implemented as list_all + client-side substring filtering.
  - The user object no longer has a "role" field; UserSummary.role is
    populated from seat_type as a best-effort substitute.
  - status and seat_type are proto enums with UPPER_SNAKE_CASE wire values
    (s12.common.UserActiveStatus: USER_ACTIVE_STATUS_ACTIVE/_DEACTIVATED/
    _UNSPECIFIED — no "pending" status exists; s12.common.SubscriptionSeatTypes:
    SUBSCRIPTION_SEAT_TYPE_PREMIUM/_COLLABORATOR/_LITE/_SERVICE_USER/_SUPPORT/
    _UNSPECIFIED), confirmed against the schema. _parse_user translates both to
    short lowercase labels so tool output and the status filter stay
    human-friendly instead of leaking the raw enum wire format.
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from mitti_mcp.client import MittiAPIError, api_client, handle_response
from mitti_mcp.models.schemas import OperationResult, UserList, UserSummary

mcp = FastMCP(name="users")

_STATUS_TO_ENUM = {
    "active": "USER_ACTIVE_STATUS_ACTIVE",
    "inactive": "USER_ACTIVE_STATUS_DEACTIVATED",
}
_ENUM_TO_STATUS = {v: k for k, v in _STATUS_TO_ENUM.items()}

_SEAT_TYPE_PREFIX = "SUBSCRIPTION_SEAT_TYPE_"


def _parse_user(raw: dict) -> UserSummary:
    """Map a /users/v1/users/list row to UserSummary."""
    raw_status = raw.get("status")
    raw_seat_type = raw.get("seat_type")
    return UserSummary(
        user_id=raw.get("user_id", ""),
        firstname=raw.get("first_name"),
        lastname=raw.get("last_name"),
        email=raw.get("email"),
        status=_ENUM_TO_STATUS.get(raw_status, raw_status),
        role=(
            raw_seat_type[len(_SEAT_TYPE_PREFIX) :].lower()
            if raw_seat_type and raw_seat_type.startswith(_SEAT_TYPE_PREFIX)
            else raw_seat_type
        ),
    )


async def _list_users_page(
    limit: int,
    status: Optional[str] = None,
) -> dict:
    """Call /users/v1/users/list and return the raw response dict."""
    body: dict = {"page_size": min(limit, 200)}
    if status:
        if status not in _STATUS_TO_ENUM:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_STATUS_TO_ENUM))}.")
        body["filters"] = {"statuses": [_STATUS_TO_ENUM[status]]}
    else:
        body["list_all"] = True

    try:
        async with api_client() as client:
            resp = await client.post("/users/v1/users/list", json=body)
            data = await handle_response(resp, "/users/v1/users/list")
    except MittiAPIError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to list users: {exc}") from exc

    return data


@mcp.tool(
    description=(
        "List users in the Mitti (formerly SafetyCulture) organization. "
        "Returns user ID, first name, last name, email, status ('active' or 'inactive' — "
        "there is no 'pending' status), and a best-effort role indicator. "
        "Useful for finding user IDs to assign to actions."
    )
)
async def list_users(
    limit: int = 20,
    status: Optional[str] = None,
) -> UserList:
    """
    List users in the Mitti organization.

    Args:
        limit: Maximum number of users to return (1–200, default 20).
        status: Filter by account status — 'active' or 'inactive'.

    Returns:
        UserList with matching users and their IDs.
    """
    data = await _list_users_page(limit, status)
    raw_users = data.get("users", [])
    users = [_parse_user(u) for u in raw_users]
    return UserList(users=users, total=len(users), next_page_token=data.get("next_page_token"))


@mcp.tool(
    description=(
        "Get the profile of the currently authenticated Mitti user. "
        "NOTE: Mitti's current API has no dedicated 'current user' endpoint — this always "
        "returns failure with guidance to use search_users with a known email instead."
    )
)
async def get_current_user() -> OperationResult:
    """
    Attempt to get the profile of the currently authenticated user.

    Returns:
        OperationResult(success=False, ...) — Mitti's API does not expose a way to
        resolve the API token's owner. Use search_users with a known email instead.
    """
    return OperationResult(
        success=False,
        message=(
            "Mitti's current API has no 'current user' / 'me' endpoint (removed in the "
            "SafetyCulture-to-Mitti migration). Use search_users with your email to find "
            "your own user record instead."
        ),
    )


@mcp.tool(
    description=(
        "Search for Mitti users by name or email substring. "
        "NOTE: the underlying API only supports exact-match filters, so this fetches all "
        "users and filters client-side — it is not efficient for very large organizations. "
        "Returns matching users with their IDs, names, emails, and statuses."
    )
)
async def search_users(
    query: str,
    limit: int = 10,
) -> UserList:
    """
    Search for users by name or email (client-side substring match).

    Args:
        query: Search string to match against user names and email addresses.
        limit: Maximum number of results to return (default 10, max 100).

    Returns:
        UserList with matching users.
    """
    data = await _list_users_page(limit=200)
    raw_users = data.get("users", [])
    needle = query.lower()

    def _matches(u: dict) -> bool:
        haystack = " ".join(
            str(u.get(field, "")) for field in ("first_name", "last_name", "email")
        ).lower()
        return needle in haystack

    matched = [u for u in raw_users if _matches(u)][: min(limit, 100)]
    users = [_parse_user(u) for u in matched]
    return UserList(users=users, total=len(users))
