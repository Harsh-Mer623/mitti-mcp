"""
Tests for Mitti MCP tools.

These tests use FastMCP's built-in in-process test client and mock httpx
to avoid requiring a real API token during CI.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, body: dict) -> MagicMock:
    """Return a mock httpx.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.content = b"non-empty"
    mock.json.return_value = body
    mock.text = json.dumps(body)
    mock.headers = {}
    return mock


# ---------------------------------------------------------------------------
# client.py unit tests
# ---------------------------------------------------------------------------


class TestHandleResponse:
    """Test the handle_response helper in client.py."""

    @pytest.mark.asyncio
    async def test_200_returns_json(self) -> None:
        from mitti_mcp.client import handle_response

        resp = _mock_response(200, {"key": "value"})
        result = await handle_response(resp)
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_401_raises(self) -> None:
        from mitti_mcp.client import MittiAPIError, handle_response

        resp = _mock_response(401, {})
        with pytest.raises(MittiAPIError) as exc_info:
            await handle_response(resp)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_404_raises(self) -> None:
        from mitti_mcp.client import MittiAPIError, handle_response

        resp = _mock_response(404, {})
        with pytest.raises(MittiAPIError) as exc_info:
            await handle_response(resp)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_429_raises(self) -> None:
        from mitti_mcp.client import MittiAPIError, handle_response

        resp = _mock_response(429, {})
        resp.headers = {"Retry-After": "60"}
        with pytest.raises(MittiAPIError) as exc_info:
            await handle_response(resp)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_500_raises(self) -> None:
        from mitti_mcp.client import MittiAPIError, handle_response

        resp = _mock_response(500, {})
        with pytest.raises(MittiAPIError) as exc_info:
            await handle_response(resp)
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_empty_204_returns_empty_dict(self) -> None:
        from mitti_mcp.client import handle_response

        resp = _mock_response(204, {})
        resp.content = b""
        result = await handle_response(resp)
        assert result == {}


# ---------------------------------------------------------------------------
# Pydantic schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    """Test Pydantic v2 schema validation."""

    def test_inspection_summary_minimal(self) -> None:
        from mitti_mcp.models.schemas import InspectionSummary

        insp = InspectionSummary(audit_id="audit_abc123", name="My Inspection")
        assert insp.audit_id == "audit_abc123"
        assert insp.name == "My Inspection"
        assert insp.status is None

    def test_action_summary_minimal(self) -> None:
        from mitti_mcp.models.schemas import ActionSummary

        action = ActionSummary(id="action_xyz", title="Fix the thing")
        assert action.id == "action_xyz"
        assert action.assignees == []

    def test_create_action_input_validation(self) -> None:
        from mitti_mcp.models.schemas import CreateActionInput

        inp = CreateActionInput(title="My Action", priority_id="priority-uuid-123")
        assert inp.title == "My Action"
        assert inp.priority_id == "priority-uuid-123"

    def test_operation_result_success(self) -> None:
        from mitti_mcp.models.schemas import OperationResult

        result = OperationResult(success=True, message="Done", data={"id": "123"})
        assert result.success is True
        assert result.data["id"] == "123"

    def test_user_summary(self) -> None:
        from mitti_mcp.models.schemas import UserSummary

        user = UserSummary(
            user_id="user_abc",
            firstname="Jane",
            lastname="Doe",
            email="jane.doe@example.com",
            status="active",
        )
        assert user.email == "jane.doe@example.com"

    def test_template_summary(self) -> None:
        from mitti_mcp.models.schemas import TemplateSummary

        tmpl = TemplateSummary(template_id="template_001", name="Safety Check")
        assert tmpl.template_id == "template_001"
        assert tmpl.archived is None


# ---------------------------------------------------------------------------
# Tool-level integration tests (mock HTTP)
# ---------------------------------------------------------------------------


FAKE_INSPECTIONS_RESPONSE = {
    # /audits/search only returns these three fields per Mitti's API — no
    # name/owner/score/status available from the list endpoint.
    "audits": [
        {
            "audit_id": "audit_test001",
            "template_id": "template_abc",
            "modified_at": "2024-06-01T10:00:00Z",
        }
    ],
    "total": 1,
}

FAKE_TEMPLATES_RESPONSE = {
    "templates": [
        {
            "template_id": "template_abc",
            "name": "Weekly Safety Template",
            "created_at": "2023-01-15T12:00:00Z",
            "modified_at": "2024-01-01T00:00:00Z",
        }
    ],
    "total": 1,
}

# Each item in ActionsResponse.actions is an s12.tasks.v1.Action envelope —
# the real fields live under "task", per the verified OpenAPI schema.
FAKE_ACTION_ENVELOPE = {
    "task": {
        "task_id": "action_test001",
        "title": "Replace fire extinguisher",
        "description": "Must be done before inspection",
        "status": {"status_id": "17e793a1-26a3-4ecd-99ca-f38ecc6eaa2e", "key": "to_do"},
        "priority_id": "priority-uuid-high",
        "due_at": "2024-07-01T17:00:00Z",
        "created_at": "2024-06-01T08:00:00Z",
        "collaborators": [
            {
                "collaborator_id": "user_xyz",
                "collaborator_type": "USER",
                "assigned_role": "ASSIGNEE",
            }
        ],
        "site": {"id": "site_001", "name": "Main Warehouse"},
        "creator": {"user_id": "user_creator", "firstname": "Bob"},
    }
}

FAKE_ACTIONS_RESPONSE = {
    "actions": [FAKE_ACTION_ENVELOPE],
    "next_page_token": None,
}

# GetAction's ActionResponse wraps the same envelope under "action".
FAKE_GET_ACTION_RESPONSE = {
    "action": FAKE_ACTION_ENVELOPE,
    "read_only": False,
}

# GetTemplateByIDResponse wraps the Template under "template".
FAKE_GET_TEMPLATE_RESPONSE = {
    "template": {
        "id": "template_abc",
        "name": "Weekly Safety Template",
        "description": "Used for weekly checks",
        "archived": False,
        "owner": {"id": "user_bob", "name": "Bob"},
        "created_at": "2023-01-15T12:00:00Z",
        "modified_at": "2024-01-01T00:00:00Z",
    }
}

FAKE_USERS_RESPONSE = {
    # status/seat_type use the real UPPER_SNAKE_CASE proto enum wire values
    # (s12.common.UserActiveStatus / SubscriptionSeatTypes), not the friendly
    # lowercase strings the old SafetyCulture API used.
    "users": [
        {
            "user_id": "user_abc",
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@example.com",
            "status": "USER_ACTIVE_STATUS_ACTIVE",
            "seat_type": "SUBSCRIPTION_SEAT_TYPE_PREMIUM",
        }
    ],
}


@pytest.mark.asyncio
class TestInspectionTools:
    async def test_list_inspections_returns_list(self) -> None:
        from mitti_mcp.tools.inspections import list_inspections

        mock_resp = _mock_response(200, FAKE_INSPECTIONS_RESPONSE)

        with (
            patch("mitti_mcp.client.os.environ.get", return_value="fake_token"),
            patch("mitti_mcp.client.httpx.AsyncClient") as mock_client_class,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await list_inspections(limit=5)

        assert len(result.inspections) == 1
        assert result.inspections[0].audit_id == "audit_test001"
        assert result.inspections[0].template_id == "template_abc"


@pytest.mark.asyncio
class TestActionTools:
    async def test_list_actions_returns_list(self) -> None:
        from mitti_mcp.tools.actions import list_actions

        mock_resp = _mock_response(200, FAKE_ACTIONS_RESPONSE)

        with (
            patch("mitti_mcp.client.os.environ.get", return_value="fake_token"),
            patch("mitti_mcp.client.httpx.AsyncClient") as mock_client_class,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await list_actions(limit=5)

        assert len(result.actions) == 1
        assert result.actions[0].id == "action_test001"
        assert result.actions[0].priority_id == "priority-uuid-high"
        assert result.actions[0].status == "open"
        assert result.actions[0].assignees == ["user_xyz"]
        assert result.actions[0].site_id == "site_001"
        assert result.actions[0].creator_user_id == "user_creator"

    async def test_list_actions_sends_status_filter(self) -> None:
        """status is translated to a server-side task_filters entry using the
        confirmed TaskFilter shape, not applied client-side."""
        from mitti_mcp.tools.actions import _STATUS_TO_ID, list_actions

        mock_resp = _mock_response(200, FAKE_ACTIONS_RESPONSE)

        with (
            patch("mitti_mcp.client.os.environ.get", return_value="fake_token"),
            patch("mitti_mcp.client.httpx.AsyncClient") as mock_client_class,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await list_actions(limit=5, status="completed")

        sent_body = mock_client.post.call_args.kwargs["json"]
        assert sent_body["task_filters"] == [
            {
                "status_id": {
                    "operator": "FILTER_OPERATOR_IN",
                    "value": [_STATUS_TO_ID["completed"]],
                }
            }
        ]

    async def test_list_actions_invalid_status_raises(self) -> None:
        from mitti_mcp.tools.actions import list_actions

        with pytest.raises(ValueError, match="Invalid status"):
            await list_actions(status="not_a_real_status")

    async def test_get_action_unwraps_envelope(self) -> None:
        """GetAction's ActionResponse wraps the Action under "action" — regression
        test for a bug where this wrapper (and the inner "task" wrapper) was not
        being unwrapped, silently returning empty/default fields for every action.
        """
        from mitti_mcp.tools.actions import get_action

        mock_resp = _mock_response(200, FAKE_GET_ACTION_RESPONSE)

        with (
            patch("mitti_mcp.client.os.environ.get", return_value="fake_token"),
            patch("mitti_mcp.client.httpx.AsyncClient") as mock_client_class,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await get_action("action_test001")

        assert result.id == "action_test001"
        assert result.title == "Replace fire extinguisher"
        assert result.status == "open"
        assert result.assignees == ["user_xyz"]

    async def test_update_action_status_invalid(self) -> None:
        from mitti_mcp.tools.actions import update_action_status

        result = await update_action_status("action_123", "invalid_status")
        assert result.success is False
        assert "Invalid status" in result.message


@pytest.mark.asyncio
class TestTemplateTools:
    async def test_get_template_unwraps_envelope(self) -> None:
        """GetTemplateByIDResponse wraps the Template under "template" — regression
        test for a bug where this wrapper was not being unwrapped, silently
        returning empty/default fields.
        """
        from mitti_mcp.tools.templates import get_template

        mock_resp = _mock_response(200, FAKE_GET_TEMPLATE_RESPONSE)

        with (
            patch("mitti_mcp.client.os.environ.get", return_value="fake_token"),
            patch("mitti_mcp.client.httpx.AsyncClient") as mock_client_class,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await get_template("template_abc")

        assert result.template_id == "template_abc"
        assert result.name == "Weekly Safety Template"
        assert result.description == "Used for weekly checks"
        assert result.owner_name == "Bob"
        assert result.archived is False


@pytest.mark.asyncio
class TestUserTools:
    async def test_list_users_translates_enum_values(self) -> None:
        """status/seat_type come back from the API as UPPER_SNAKE_CASE proto
        enum wire values — regression test for a bug where the friendly
        'active'/'inactive' filter values were sent as-is (which the enum
        never matches) and raw enum strings leaked into UserSummary.status/role.
        """
        from mitti_mcp.tools.users import list_users

        mock_resp = _mock_response(200, FAKE_USERS_RESPONSE)

        with (
            patch("mitti_mcp.client.os.environ.get", return_value="fake_token"),
            patch("mitti_mcp.client.httpx.AsyncClient") as mock_client_class,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await list_users(limit=5, status="active")

        sent_body = mock_client.post.call_args.kwargs["json"]
        assert sent_body["filters"] == {"statuses": ["USER_ACTIVE_STATUS_ACTIVE"]}

        assert len(result.users) == 1
        assert result.users[0].status == "active"
        assert result.users[0].role == "premium"

    async def test_list_users_invalid_status_raises(self) -> None:
        from mitti_mcp.tools.users import list_users

        with pytest.raises(ValueError, match="Invalid status"):
            await list_users(status="pending")
