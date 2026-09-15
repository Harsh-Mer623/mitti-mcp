"""
Action tools for the Mitti MCP server.

Endpoints used (verified against https://developer.mitti.com/llms.txt, Sep 2026):
  - POST /tasks/v1/actions/list        — list actions
  - GET  /tasks/v1/actions/{id}        — get single action
  - POST /tasks/v1/actions             — create action
  - PUT  /tasks/v1/actions/{id}/status — update action status
  - PUT  /tasks/v1/actions/{id}/title  — update action title

IMPORTANT — this is a substantially different API shape than the old
SafetyCulture actions/v1 REST API, not just a renamed host:
  - Assignees are now "collaborators": {collaborator_id, collaborator_type,
    assigned_role}. assignee_ids in this module's tool inputs are translated
    to collaborators of type USER with role ASSIGNEE.
  - Priority is now an org-specific `priority_id` (UUID from a per-org
    task-type configuration), not a fixed 'low'/'medium'/'high' string. This
    module no longer validates or maps priority strings — pass a priority_id
    if you know your org's configured IDs, or omit it for the system default.
  - Status IS still a fixed set for the built-in Actions task type, with
    documented stable IDs (used below) — so the friendly
    open/in_progress/completed/cant_do interface is preserved.
  - list_actions filters status/priority_id server-side via `task_filters`:
    [{"status_id" | "priority_id": {"operator": "FILTER_OPERATOR_IN", "value": [...]}}]
    (confirmed against the s12.tasks.v1.TaskFilter schema — multiple values
    within one filter are OR'd, multiple filters in the array are AND'd).
  - Both list and get responses wrap each action in an s12.tasks.v1.Action
    envelope ({task, custom_field_and_values, type}) — the real fields live
    under "task", not at the top level. GetAction additionally wraps that
    envelope under an "action" key. See _parse_action / get_action.
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from mitti_mcp.client import MittiAPIError, api_client, handle_response
from mitti_mcp.models.schemas import (
    ActionList,
    ActionSummary,
    CreateActionInput,
    CreatedAction,
    OperationResult,
)

mcp = FastMCP(name="actions")

# Stable, documented status IDs for the built-in Actions task type
# (https://developer.mitti.com/reference/actionsservice_updatestatus).
_STATUS_TO_ID = {
    "open": "17e793a1-26a3-4ecd-99ca-f38ecc6eaa2e",  # "To do"
    "in_progress": "20ce0cb1-387a-47d4-8c34-bc6fd3be0e27",  # "In progress"
    "completed": "7223d809-553e-4714-a038-62dc98f3fbf3",  # "Complete"
    "cant_do": "06308884-41c2-4ee0-9da7-5676647d3d75",  # "Can't do"
}
_ID_TO_STATUS = {v: k for k, v in _STATUS_TO_ID.items()}


def _parse_action(raw: dict) -> ActionSummary:
    """Map an Action envelope ({task, custom_field_and_values, type}) to ActionSummary.

    Per the s12.tasks.v1.Action schema, the real fields live under "task" —
    both /tasks/v1/actions/list items and the unwrapped body of
    GET /tasks/v1/actions/{id} (see get_action) use this same envelope shape.
    """
    task = raw.get("task", raw)  # tolerate an already-flat dict defensively
    status_obj = task.get("status") or {}
    status_id = status_obj.get("status_id")
    assignees = [
        c.get("collaborator_id")
        for c in task.get("collaborators", [])
        if c.get("assigned_role") == "ASSIGNEE"
    ]

    return ActionSummary(
        id=task.get("task_id", ""),
        title=task.get("title", "Untitled"),
        description=task.get("description"),
        status=_ID_TO_STATUS.get(status_id, status_obj.get("key")),
        priority_id=task.get("priority_id"),
        due_at=task.get("due_at"),
        created_at=task.get("created_at"),
        modified_at=task.get("modified_at"),
        assignees=assignees,
        site_id=(task.get("site") or {}).get("id"),
        # Task's creator User object uses "user_id", unlike Site's "id".
        creator_user_id=(task.get("creator") or {}).get("user_id"),
    )


@mcp.tool(
    description=(
        "List actions from the Mitti (formerly SafetyCulture) account. "
        "Supports server-side filtering by status (open, in_progress, completed, cant_do) "
        "and by an org-specific priority_id (UUID). "
        "Returns action ID, title, description, status, priority_id, due date, and assignees."
    )
)
async def list_actions(
    limit: int = 20,
    status: Optional[str] = None,
    priority_id: Optional[str] = None,
) -> ActionList:
    """
    List actions in the Mitti organization.

    Args:
        limit: Maximum number of actions to return (1–100, default 20).
        status: Filter by status. One of: 'open', 'in_progress', 'completed', 'cant_do'.
        priority_id: Filter by a specific org-specific priority ID (UUID).

    Returns:
        ActionList with matching actions.
    """
    body: dict = {"page_size": min(limit, 100)}

    task_filters = []
    if status:
        if status not in _STATUS_TO_ID:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_STATUS_TO_ID))}.")
        task_filters.append(
            {"status_id": {"operator": "FILTER_OPERATOR_IN", "value": [_STATUS_TO_ID[status]]}}
        )
    if priority_id:
        task_filters.append(
            {"priority_id": {"operator": "FILTER_OPERATOR_IN", "value": [priority_id]}}
        )
    if task_filters:
        body["task_filters"] = task_filters

    try:
        async with api_client() as client:
            resp = await client.post("/tasks/v1/actions/list", json=body)
            data = await handle_response(resp, "/tasks/v1/actions/list")
    except MittiAPIError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to list actions: {exc}") from exc

    raw_actions = data.get("actions", [])
    actions = [_parse_action(a) for a in raw_actions]

    return ActionList(
        actions=actions,
        total=len(actions),
        next_page_token=data.get("next_page_token"),
    )


@mcp.tool(
    description=(
        "Get full details of a specific Mitti action by its ID. "
        "Returns title, description, status, priority_id, due date, assignees, and site."
    )
)
async def get_action(action_id: str) -> ActionSummary:
    """
    Get a specific action by its ID.

    Args:
        action_id: The unique action ID.

    Returns:
        ActionSummary with full action details.
    """
    endpoint = f"/tasks/v1/actions/{action_id}"
    try:
        async with api_client() as client:
            resp = await client.get(endpoint)
            data = await handle_response(resp, endpoint)
    except MittiAPIError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to get action {action_id}: {exc}") from exc

    # ActionResponse wraps the Action envelope under "action" (plus a
    # "read_only" flag) — unwrap it before handing off to _parse_action.
    return _parse_action(data.get("action", data))


@mcp.tool(
    description=(
        "Create a new action in Mitti. "
        "Requires at minimum a title. Optionally set description, due date (ISO 8601), "
        "assignee user IDs, and site ID. priority_id is an org-specific UUID — omit it for "
        "the system default priority. "
        "Call request_approval first and wait for the user's decision before calling this tool. "
        "Returns the created action's ID."
    )
)
async def create_action(
    title: str,
    description: Optional[str] = None,
    priority_id: Optional[str] = None,
    due_at: Optional[str] = None,
    assignee_ids: Optional[list[str]] = None,
    site_id: Optional[str] = None,
) -> CreatedAction:
    """
    Create a new action.

    Args:
        title: Action title (required).
        description: Detailed description of what needs to be done.
        priority_id: Org-specific priority ID (UUID). Omit for the system default.
        due_at: Due date/time in ISO 8601 format, e.g. '2024-12-31T17:00:00.000Z'.
        assignee_ids: List of user IDs to assign this action to.
        site_id: Site ID to associate with this action.

    Returns:
        CreatedAction with the new action's ID.
    """
    # Validate input via Pydantic model
    payload_model = CreateActionInput(
        title=title,
        description=description,
        priority_id=priority_id,
        due_at=due_at,
        assignee_ids=assignee_ids,
        site_id=site_id,
    )

    payload: dict = {"title": payload_model.title}
    if payload_model.description:
        payload["description"] = payload_model.description
    if payload_model.priority_id:
        payload["priority_id"] = payload_model.priority_id
    if payload_model.due_at:
        payload["due_at"] = payload_model.due_at
    if payload_model.site_id:
        payload["site_id"] = payload_model.site_id
    if payload_model.assignee_ids:
        payload["collaborators"] = [
            {"collaborator_id": uid, "collaborator_type": "USER", "assigned_role": "ASSIGNEE"}
            for uid in payload_model.assignee_ids
        ]

    try:
        async with api_client() as client:
            resp = await client.post("/tasks/v1/actions", json=payload)
            data = await handle_response(resp, "/tasks/v1/actions")
    except MittiAPIError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to create action: {exc}") from exc

    return CreatedAction(
        id=data.get("action_id", ""),
        title=title,
        due_at=due_at,
    )


@mcp.tool(
    description=(
        "Update the status of a Mitti action. "
        "Valid statuses are: 'open', 'in_progress', 'completed', 'cant_do'. "
        "Call request_approval first and wait for the user's decision before calling this tool. "
        "Returns success or an error message."
    )
)
async def update_action_status(
    action_id: str,
    status: str,
) -> OperationResult:
    """
    Update the status of an existing action.

    Args:
        action_id: The unique action ID to update.
        status: New status — one of: 'open', 'in_progress', 'completed', 'cant_do'.

    Returns:
        OperationResult indicating success or failure.
    """
    if status not in _STATUS_TO_ID:
        return OperationResult(
            success=False,
            message=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_STATUS_TO_ID))}.",
        )

    endpoint = f"/tasks/v1/actions/{action_id}/status"
    try:
        async with api_client() as client:
            resp = await client.put(endpoint, json={"status_id": _STATUS_TO_ID[status]})
            await handle_response(resp, endpoint)
        return OperationResult(
            success=True,
            message=f"Action {action_id} status updated to '{status}'.",
            data={"action_id": action_id, "new_status": status},
        )
    except MittiAPIError as exc:
        return OperationResult(success=False, message=str(exc))
    except Exception as exc:
        return OperationResult(success=False, message=f"Unexpected error: {exc}")


@mcp.tool(
    description=(
        "Update the title of a Mitti action. "
        "Call request_approval first and wait for the user's decision before calling this tool. "
        "Returns success or an error message."
    )
)
async def update_action_title(action_id: str, title: str) -> OperationResult:
    """
    Update the title of an existing action.

    Args:
        action_id: The unique action ID to update.
        title: New title for the action (max 255 characters).

    Returns:
        OperationResult indicating success or failure.
    """
    endpoint = f"/tasks/v1/actions/{action_id}/title"
    try:
        async with api_client() as client:
            resp = await client.put(endpoint, json={"title": title})
            await handle_response(resp, endpoint)
        return OperationResult(
            success=True,
            message=f"Action {action_id} title updated.",
            data={"action_id": action_id, "new_title": title},
        )
    except MittiAPIError as exc:
        return OperationResult(success=False, message=str(exc))
    except Exception as exc:
        return OperationResult(success=False, message=f"Unexpected error: {exc}")
