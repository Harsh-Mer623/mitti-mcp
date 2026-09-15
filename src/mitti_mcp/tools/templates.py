"""
Template tools for the Mitti MCP server.

Endpoints used (verified against https://developer.mitti.com/llms.txt, Sep 2026):
  - GET /templates/search                                       — search/list templates
  - GET /templates/v1/templates/{template_id}                   — get template summary
  - GET /templates/integration/v1/templates/{template_id}/definition — get full definition

IMPORTANT — API limitation: /templates/search's `field` parameter only returns
template_id, name, modified_at, created_at. Description, owner, and archived
status are NOT available from the list — call get_template for those.

Both get_template and get_template_definition wrap their payload in a response
envelope (confirmed against the schema): GetTemplateByIDResponse.template and
GetTemplateDefinitionResponse.template respectively — neither returns the
Template/TemplateDefinition fields at the top level.
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from mitti_mcp.client import MittiAPIError, api_client, handle_response
from mitti_mcp.models.schemas import OperationResult, TemplateList, TemplateSummary

mcp = FastMCP(name="templates")

_SEARCH_FIELDS = ["template_id", "name", "modified_at", "created_at"]


def _parse_template_search_result(raw: dict) -> TemplateSummary:
    """Map a /templates/search row (id, name, dates only) to TemplateSummary."""
    return TemplateSummary(
        template_id=raw.get("template_id", ""),
        name=raw.get("name", "Unnamed"),
        created_at=raw.get("created_at"),
        modified_at=raw.get("modified_at"),
    )


def _parse_template_detail(raw: dict) -> TemplateSummary:
    """Map a /templates/v1/templates/{id} response (flat, with nested owner/author) to TemplateSummary."""
    return TemplateSummary(
        template_id=raw.get("id", raw.get("template_id", "")),
        name=raw.get("name", "Unnamed"),
        description=raw.get("description"),
        created_at=raw.get("created_at"),
        modified_at=raw.get("modified_at"),
        owner_name=(raw.get("owner") or {}).get("name"),
        archived=raw.get("archived"),
    )


@mcp.tool(
    description=(
        "List templates available in the Mitti (formerly SafetyCulture) account. "
        "Returns template ID, name, and dates only — description, owner, and archived "
        "status require get_template. Use the returned template_id to get the full "
        "template definition."
    )
)
async def list_templates(
    limit: int = 20,
    archived: bool = False,
) -> TemplateList:
    """
    List templates in the Mitti organization.

    Args:
        limit: Maximum number of templates to return (1–100, default 20).
        archived: If True, include archived templates. Default is False (active only).

    Returns:
        TemplateList with matching templates (template_id, name, dates only).
    """
    params: dict = {
        "limit": min(limit, 100),
        "field": _SEARCH_FIELDS,
        "archived": "both" if archived else "false",
    }

    try:
        async with api_client() as client:
            resp = await client.get("/templates/search", params=params)
            data = await handle_response(resp, "/templates/search")
    except MittiAPIError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to list templates: {exc}") from exc

    raw_templates = data.get("templates", [])
    templates = [_parse_template_search_result(t) for t in raw_templates]
    return TemplateList(
        templates=templates,
        total=data.get("total", len(templates)),
        next_page_token=data.get("next_page_token"),
    )


@mcp.tool(
    description=(
        "Get summary metadata for a specific Mitti template by its ID. "
        "Returns name, description, owner, archived status, and dates."
    )
)
async def get_template(template_id: str) -> TemplateSummary:
    """
    Get summary information for a specific template.

    Args:
        template_id: The unique template ID (starts with 'template_').

    Returns:
        TemplateSummary with template metadata.
    """
    endpoint = f"/templates/v1/templates/{template_id}"
    try:
        async with api_client() as client:
            resp = await client.get(endpoint)
            data = await handle_response(resp, endpoint)
    except MittiAPIError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to get template {template_id}: {exc}") from exc

    # GetTemplateByIDResponse wraps the Template under a "template" key.
    return _parse_template_detail(data.get("template", data))


@mcp.tool(
    description=(
        "Get the full definition of a Mitti template including all questions, "
        "sections, and scoring rules. Returns a structured summary of the template definition."
    )
)
async def get_template_definition(template_id: str) -> OperationResult:
    """
    Get the full template definition with all questions and sections.

    Args:
        template_id: The unique template ID (starts with 'template_').

    Returns:
        OperationResult with the template definition summary in data.
    """
    endpoint = f"/templates/integration/v1/templates/{template_id}/definition"
    try:
        async with api_client() as client:
            resp = await client.get(endpoint)
            data = await handle_response(resp, endpoint)

        # GetTemplateDefinitionResponse always wraps the TemplateDefinition under
        # "template" — confirmed against the schema (items/response_sets/
        # template_identity live inside it, never at the top level).
        items = data.get("template", {}).get("items", [])
        # Item type is an ItemType proto enum with UPPER_SNAKE_CASE wire values
        # (ITEM_TYPE_SECTION, ITEM_TYPE_TEXT, ITEM_TYPE_CHECKBOX, ITEM_TYPE_SIGNATURE,
        # ITEM_TYPE_MEDIA, ITEM_TYPE_QUESTION for multi-choice/select), confirmed
        # against the schema — not the lowercase strings used by the old SafetyCulture API.
        _KEY_ITEM_TYPES = {
            "ITEM_TYPE_SECTION",
            "ITEM_TYPE_TEXT",
            "ITEM_TYPE_CHECKBOX",
            "ITEM_TYPE_QUESTION",
            "ITEM_TYPE_SIGNATURE",
            "ITEM_TYPE_MEDIA",
        }
        sections = [
            {
                "item_id": item.get("item_id"),
                "label": item.get("label"),
                "type": item.get("type"),
            }
            for item in items
            if item.get("type") in _KEY_ITEM_TYPES
        ]
        return OperationResult(
            success=True,
            message=f"Template definition retrieved — {len(items)} total items, {len(sections)} key items shown.",
            data={
                "template_id": template_id,
                "item_count": len(items),
                "key_items": sections[:50],  # cap to avoid token bloat
            },
        )
    except MittiAPIError as exc:
        return OperationResult(success=False, message=str(exc))
    except Exception as exc:
        return OperationResult(success=False, message=f"Unexpected error: {exc}")
