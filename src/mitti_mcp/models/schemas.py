"""
Pydantic v2 schemas for Mitti (formerly SafetyCulture) API responses.

All models use strict typing and follow the Mitti API shape.
Raw API responses are never returned directly — always via these models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inspection models
# ---------------------------------------------------------------------------


class InspectionSummary(BaseModel):
    """Condensed inspection record returned from search/list endpoints."""

    audit_id: str = Field(description="Unique inspection identifier")
    name: str = Field(description="Inspection name / title")
    template_id: Optional[str] = Field(None, description="Template used to create this inspection")
    owner_name: Optional[str] = Field(None, description="Display name of the inspection owner")
    date_started: Optional[datetime] = Field(None, description="When the inspection was started")
    date_completed: Optional[datetime] = Field(None, description="When the inspection was completed (None if in progress)")
    date_modified: Optional[datetime] = Field(None, description="Last modification timestamp")
    score: Optional[float] = Field(None, description="Inspection score percentage (0–100)")
    score_percentage: Optional[float] = Field(None, description="Score as a percentage string")
    total_score: Optional[float] = Field(None, description="Maximum possible score")
    status: Optional[str] = Field(None, description="Inspection status: 'in_progress' or 'completed'")
    site_id: Optional[str] = Field(None, description="Site this inspection belongs to")
    web_report_link: Optional[str] = Field(None, description="Publicly shareable web report URL")


class InspectionList(BaseModel):
    """Result of listing/searching inspections."""

    inspections: list[InspectionSummary] = Field(default_factory=list)
    total: int = Field(0, description="Total number of matching inspections (may exceed page size)")
    next_page_token: Optional[str] = Field(None, description="Cursor for the next page of results")


class InspectionItem(BaseModel):
    """A single question / item within an inspection."""

    item_id: str
    label: Optional[str] = None
    response_id: Optional[str] = None
    response: Optional[str] = None
    type: Optional[str] = None
    failed: Optional[bool] = None
    score: Optional[float] = None
    max_score: Optional[float] = None


class InspectionDetail(BaseModel):
    """Full inspection record with metadata and item summary."""

    audit_id: str
    name: str
    template_id: Optional[str] = None
    owner_name: Optional[str] = None
    date_started: Optional[datetime] = None
    date_completed: Optional[datetime] = None
    date_modified: Optional[datetime] = None
    score: Optional[float] = None
    total_score: Optional[float] = None
    status: Optional[str] = None
    site_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Template models
# ---------------------------------------------------------------------------


class TemplateSummary(BaseModel):
    """Condensed template record."""

    template_id: str = Field(description="Unique template identifier")
    name: str = Field(description="Template name")
    description: Optional[str] = Field(None, description="Template description")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    modified_at: Optional[datetime] = Field(None, description="Last modification timestamp")
    owner_name: Optional[str] = Field(None, description="Template owner display name")
    archived: Optional[bool] = Field(None, description="Whether this template is archived")


class TemplateList(BaseModel):
    """Result of listing templates."""

    templates: list[TemplateSummary] = Field(default_factory=list)
    total: int = Field(0)
    next_page_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Action models
# ---------------------------------------------------------------------------


class ActionSummary(BaseModel):
    """Condensed action record."""

    id: str = Field(description="Unique action identifier")
    title: str = Field(description="Action title")
    description: Optional[str] = Field(None, description="Detailed description")
    status: Optional[str] = Field(None, description="Action status: 'open', 'in_progress', 'completed', 'cant_do'")
    priority_id: Optional[str] = Field(
        None,
        description=(
            "Org-specific priority identifier (Mitti's task-type system uses UUIDs, "
            "not fixed 'low'/'medium'/'high' labels — this field is not human-readable)"
        ),
    )
    due_at: Optional[datetime] = Field(None, description="Due date/time")
    created_at: Optional[datetime] = Field(None, description="When the action was created")
    modified_at: Optional[datetime] = Field(None, description="Last modification timestamp")
    assignees: list[str] = Field(default_factory=list, description="List of assignee user IDs")
    site_id: Optional[str] = Field(None, description="Site this action belongs to")
    creator_user_id: Optional[str] = Field(None, description="User ID who created the action")


class ActionList(BaseModel):
    """Result of listing actions."""

    actions: list[ActionSummary] = Field(default_factory=list)
    total: int = Field(0)
    next_page_token: Optional[str] = None


class CreateActionInput(BaseModel):
    """Input model for creating a new action."""

    title: str = Field(description="Action title (required)")
    description: Optional[str] = Field(None, description="Detailed description of the action")
    priority_id: Optional[str] = Field(
        None,
        description=(
            "Org-specific priority ID (UUID). Omit for the system default — Mitti's "
            "task-type priorities are configured per organization, not fixed labels."
        ),
    )
    due_at: Optional[str] = Field(None, description="Due date in ISO 8601 format, e.g. '2024-12-31T17:00:00Z'")
    assignee_ids: Optional[list[str]] = Field(None, description="List of user IDs to assign to this action")
    site_id: Optional[str] = Field(None, description="Site ID to associate with this action")


class CreatedAction(BaseModel):
    """Response after successfully creating an action."""

    id: str
    title: str
    due_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# User models
# ---------------------------------------------------------------------------


class UserSummary(BaseModel):
    """Condensed user record."""

    user_id: str = Field(description="Unique user identifier")
    firstname: Optional[str] = Field(None, description="User's first name")
    lastname: Optional[str] = Field(None, description="User's last name")
    email: Optional[str] = Field(None, description="User's email address")
    status: Optional[str] = Field(
        None, description="Account status: 'active' or 'inactive' (Mitti has no 'pending' status)"
    )
    role: Optional[str] = Field(
        None,
        description=(
            "Best-effort role indicator. Mitti's Users API no longer returns a 'role' field "
            "directly — this is populated from seat_type (e.g. 'premium', 'lite', "
            "'collaborator', 'service_user', 'support') where available."
        ),
    )


class UserList(BaseModel):
    """Result of listing users."""

    users: list[UserSummary] = Field(default_factory=list)
    total: int = Field(0)
    next_page_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Generic error / status models
# ---------------------------------------------------------------------------


class OperationResult(BaseModel):
    """Generic success/failure result for write operations."""

    success: bool
    message: str
    data: Optional[dict] = None  # type: ignore[type-arg]
