"""
Inspection tools for the Mitti MCP server.

Endpoints used (verified against https://developer.mitti.com/llms.txt, Sep 2026):
  - GET  /audits/search                                          — search inspections
  - GET  /audits/{audit_id}                                      — get inspection detail (legacy but current)
  - POST /inspections/integration/v1/inspections/{id}/complete   — complete an inspection
  - GET  /audits/{audit_id}/web_report_link                      — get web report link

IMPORTANT — API limitation: the search endpoint's `field` query parameter only
accepts `audit_id`, `modified_at`, and `template_id`. Name, owner, score, and
status are NOT returned by search under the current API — only get_inspection
returns them. list_inspections therefore returns a lightweight summary; call
get_inspection for full detail on a specific audit_id.
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP
from prefab_ui.components import DataTable, DataTableColumn

from mitti_mcp.client import MittiAPIError, api_client, handle_response
from mitti_mcp.models.schemas import (
    InspectionDetail,
    InspectionList,
    InspectionSummary,
    OperationResult,
)

mcp = FastMCP(name="inspections")

_SEARCH_FIELDS = ["audit_id", "modified_at", "template_id"]


def _parse_inspection_search_result(raw: dict) -> InspectionSummary:
    """Map a /audits/search row (audit_id, modified_at, template_id only) to InspectionSummary."""
    audit_id = raw.get("audit_id", "")
    return InspectionSummary(
        audit_id=audit_id,
        name=f"Inspection {audit_id}",
        template_id=raw.get("template_id"),
        date_modified=raw.get("modified_at"),
    )


def _parse_inspection_detail(raw: dict) -> InspectionDetail:
    """Map a /audits/{audit_id} response to InspectionDetail."""
    audit_data = raw.get("audit_data", {})
    return InspectionDetail(
        audit_id=raw.get("audit_id", ""),
        name=audit_data.get("name", "Unnamed"),
        template_id=raw.get("template_id"),
        owner_name=audit_data.get("authorship", {}).get("owner"),
        date_started=audit_data.get("date_started"),
        date_completed=audit_data.get("date_completed"),
        date_modified=raw.get("modified_at"),
        score=audit_data.get("score"),
        total_score=audit_data.get("total_score"),
        status="completed" if audit_data.get("date_completed") else "in_progress",
        # The current API exposes only audit_data.site.name, not a site ID —
        # left unset rather than conflating a display name with an identifier.
        site_id=None,
    )


async def _fetch_inspections(
    limit: int = 20,
    modified_after: Optional[str] = None,
    template_id: Optional[str] = None,
) -> InspectionList:
    """Shared fetch logic for list_inspections and list_inspections_view."""
    params: dict = {"limit": min(limit, 100), "field": _SEARCH_FIELDS}
    if modified_after:
        params["modified_after"] = modified_after
    if template_id:
        params["template"] = template_id

    try:
        async with api_client() as client:
            resp = await client.get("/audits/search", params=params)
            data = await handle_response(resp, "/audits/search")
    except MittiAPIError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to list inspections: {exc}") from exc

    raw_audits = data.get("audits", [])
    inspections = [_parse_inspection_search_result(a) for a in raw_audits]
    return InspectionList(
        inspections=inspections,
        total=data.get("total", len(inspections)),
        next_page_token=data.get("next_page_token"),
    )


@mcp.tool(
    description=(
        "List inspections from the Mitti (formerly SafetyCulture) account. "
        "Supports filtering by modification date and limiting the number of results. "
        "Returns only audit_id, template_id, and modification date per inspection — "
        "the search API does not return name, owner, score, or status. "
        "Call get_inspection with a specific audit_id for full details."
    )
)
async def list_inspections(
    limit: int = 20,
    modified_after: Optional[str] = None,
    template_id: Optional[str] = None,
) -> InspectionList:
    """
    Search and list inspections.

    Args:
        limit: Maximum number of inspections to return (1–100, default 20).
        modified_after: ISO 8601 timestamp — only return inspections modified after this time.
                        Example: '2024-01-01T00:00:00.000Z'
        template_id: Filter by a specific template ID.

    Returns:
        InspectionList with matching inspections (audit_id, template_id, date_modified only)
        and a pagination token.
    """
    return await _fetch_inspections(limit, modified_after, template_id)


@mcp.tool(
    app=True,
    description=(
        "Show inspections from the Mitti account as an interactive, sortable, searchable "
        "table rendered directly in the conversation. Use this instead of list_inspections "
        "when the user wants to browse inspections visually. Only shows audit_id, "
        "template_id, and modification date — the same limitation as list_inspections."
    ),
)
async def list_inspections_view(
    limit: int = 20,
    modified_after: Optional[str] = None,
    template_id: Optional[str] = None,
) -> DataTable:
    """
    Search and list inspections, rendered as an interactive DataTable.

    Args:
        limit: Maximum number of inspections to return (1–100, default 20).
        modified_after: ISO 8601 timestamp — only return inspections modified after this time.
        template_id: Filter by a specific template ID.

    Returns:
        A DataTable component listing matching inspections.
    """
    result = await _fetch_inspections(limit, modified_after, template_id)

    rows = [
        {
            "audit_id": insp.audit_id,
            "template_id": insp.template_id,
            "date_modified": insp.date_modified.isoformat() if insp.date_modified else None,
        }
        for insp in result.inspections
    ]

    return DataTable(
        columns=[
            DataTableColumn(key="audit_id", header="Audit ID", sortable=True),
            DataTableColumn(key="template_id", header="Template ID", sortable=True),
            DataTableColumn(key="date_modified", header="Modified", sortable=True, format="date"),
        ],
        rows=rows,
        search=True,
        paginated=True,
    )


@mcp.tool(
    description=(
        "Get full details of a single Mitti inspection by its audit ID. "
        "Returns name, template, owner, dates, score, and status."
    )
)
async def get_inspection(audit_id: str) -> InspectionDetail:
    """
    Retrieve a specific inspection by its ID.

    Args:
        audit_id: The unique audit/inspection ID (starts with 'audit_').

    Returns:
        InspectionDetail with full inspection metadata.
    """
    endpoint = f"/audits/{audit_id}"
    try:
        async with api_client() as client:
            resp = await client.get(endpoint)
            data = await handle_response(resp, endpoint)
    except MittiAPIError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to get inspection {audit_id}: {exc}") from exc

    return _parse_inspection_detail(data)


@mcp.tool(
    description=(
        "Mark a Mitti inspection as complete. "
        "This is a write operation — the inspection must be in 'in_progress' status. "
        "Call request_approval first and wait for the user's decision before calling this tool. "
        "Returns success or an error message."
    )
)
async def complete_inspection(audit_id: str) -> OperationResult:
    """
    Complete (close) an inspection.

    Args:
        audit_id: The unique audit/inspection ID to complete.

    Returns:
        OperationResult indicating success or failure.
    """
    endpoint = f"/inspections/integration/v1/inspections/{audit_id}/complete"
    try:
        async with api_client() as client:
            resp = await client.post(endpoint, json={})
            await handle_response(resp, endpoint)
        return OperationResult(success=True, message=f"Inspection {audit_id} marked as complete.")
    except MittiAPIError as exc:
        return OperationResult(success=False, message=str(exc))
    except Exception as exc:
        return OperationResult(success=False, message=f"Unexpected error: {exc}")


@mcp.tool(
    description=(
        "Get a shareable web report link for a Mitti inspection. "
        "Returns a permanent URL that can be shared with others to view the inspection report."
    )
)
async def get_inspection_web_report_link(audit_id: str) -> OperationResult:
    """
    Generate or retrieve the web report link for an inspection.

    Args:
        audit_id: The unique audit/inspection ID.

    Returns:
        OperationResult with the web report URL in the data field.
    """
    endpoint = f"/audits/{audit_id}/web_report_link"
    try:
        async with api_client() as client:
            resp = await client.get(endpoint)
            data = await handle_response(resp, endpoint)
        return OperationResult(
            success=True,
            message="Web report link retrieved.",
            data={"url": data.get("url", ""), "audit_id": audit_id},
        )
    except MittiAPIError as exc:
        return OperationResult(success=False, message=str(exc))
    except Exception as exc:
        return OperationResult(success=False, message=f"Unexpected error: {exc}")
