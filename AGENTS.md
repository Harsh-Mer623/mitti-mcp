# Mitti MCP Server — Agent Instructions

## What You Are Building
A production-grade MCP server for Mitti (the 2026 rebrand of SafetyCulture — see
https://developer.mitti.com/docs/mitti-rebrand-for-developers) using FastMCP, Pydantic v2,
and httpx.
Target deployment: Prefect Horizon.

---

## Read These First — Before Writing Any Code

```
https://gofastmcp.com/llms.txt   → FastMCP patterns, tools, resources, prompts, deployment
https://developer.mitti.com/llms.txt  → Mitti API endpoints, schemas, auth
```

Fetch both URLs at the start of every session. Do not rely on training data for either.
`developer.safetyculture.com` 302-redirects to `developer.mitti.com` — always resolve
to the Mitti URL and use that as the source of truth; do not treat the redirect as an
error.

---

## If You Hit Any Problem

Search the web for the current solution before guessing.
Use queries like:
- "FastMCP [error or concept] site:gofastmcp.com"
- "Mitti API [endpoint] example site:developer.mitti.com"
- "MCP server [issue] production solution"

Never hallucinate an API endpoint or assume an old SafetyCulture endpoint still has the
same path/shape under Mitti — several do not (see "Mitti API migration notes" below).
Always verify against `developer.mitti.com/reference`.

---

## Tech Stack

| Layer | Tool |
|---|---|
| MCP framework | FastMCP 4.x (latest) |
| HTTP client | httpx (async) |
| Validation | Pydantic v2 |
| Python | 3.12+ |
| Package manager | uv (required — FastMCP defaults to uv internally) |
| Deployment | Prefect Horizon |

---

## Environment Setup (uv — do this first)

uv is mandatory, not optional. FastMCP uses uv internally for isolated environments and `fastmcp install` requires it.

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS/Linux
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Create project
uv init mitti-mcp --python 3.12
cd mitti-mcp

# 3. Create and activate virtual environment
uv venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# 4. Add dependencies
uv add "fastmcp[apps]" httpx pydantic python-dotenv

# 5. Verify
uv pip list
```

To add new packages during development always use `uv add <package>` — never `pip install`.

---

## Project Structure

```
mitti-mcp/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── .env.example
├── src/
│   └── mitti_mcp/
│       ├── __init__.py
│       ├── server.py          # FastMCP app entry point
│       ├── client.py          # httpx Mitti API client
│       ├── tools/
│       │   ├── inspections.py
│       │   ├── actions.py
│       │   ├── templates.py
│       │   └── users.py
│       └── models/
│           └── schemas.py     # Pydantic v2 models
└── tests/
    └── test_tools.py
```

---

## Auth

Mitti uses Bearer token auth (same scheme as SafetyCulture; token format unchanged).

```python
# Always load from environment — never hardcode
import os
API_TOKEN = os.environ["MITTI_API_TOKEN"]
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}
BASE_URL = "https://api.mitti.com"  # long-term host; api.safetyculture.io still works
```

`client.py` reads `MITTI_API_TOKEN`/`MITTI_BASE_URL` first and falls back to the legacy
`SAFETYCULTURE_API_TOKEN`/`SAFETYCULTURE_BASE_URL` names — keep that fallback when
editing `client.py` so existing `.env` files don't break.

---

## Mitti API migration notes (read before touching tools/*)

The SafetyCulture → Mitti rebrand was not just a renamed host. Several endpoints have a
genuinely different shape. Confirmed as of Sep 2026 against `developer.mitti.com/reference`:

- **Inspections search** (`GET /audits/search`) only returns `audit_id`, `modified_at`,
  `template_id` via its `field` parameter — no name/owner/score/status. Full detail
  requires `GET /audits/{audit_id}` (still rich — audit_data.score, authorship, etc.).
- **Complete inspection** moved to `POST /inspections/integration/v1/inspections/{id}/complete`
  (was `/audits/v1/audits/{id}/complete`).
- **Templates search** (`GET /templates/search`) only returns `template_id`, `name`,
  `modified_at`, `created_at`. Full detail (description, owner, archived) requires
  `GET /templates/v1/templates/{id}` (unchanged path, flat response shape now).
- **Template definition** moved to `GET /templates/integration/v1/templates/{id}/definition`.
- **Actions** moved from `actions/v1` REST to `tasks/v1` with a different model:
  - Assignees are `collaborators`: `{collaborator_id, collaborator_type, assigned_role}`.
  - Priority is an org-specific `priority_id` (UUID from per-org task-type config) —
    there is no fixed 'low'/'medium'/'high' anymore.
  - Status IS still fixed for the built-in Actions type, with stable documented UUIDs
    (hardcoded in `actions.py` as `_STATUS_TO_ID`) — the friendly
    open/in_progress/completed/cant_do interface is preserved via this mapping.
  - List is `POST /tasks/v1/actions/list` (was `GET /actions/v1/actions`).
- **Users**: `GET /users/{id}` and the old email-only `POST /users/search` are both
  deprecated in favor of `POST /users/v1/users/list`, which has **no free-text search**
  (only exact filters: user_ids, usernames, field_attributes, seat_types, statuses).
  `search_users` in this codebase does client-side substring filtering as a result.
  There is **no "current user" / "me" endpoint** at all — `get_current_user` returns a
  clear failure explaining this rather than guessing at a path.

- **Response envelopes**: newer `*service_*` endpoints (actionsservice, templatesservice)
  wrap their payload in a response-message envelope that must be unwrapped before
  reading fields — e.g. `GetActionsResponse.actions[]` are `{task, custom_field_and_values,
  type}` envelopes (real fields under `task`), `GetAction` additionally wraps that under
  `{"action": ...}`, and `GetTemplateByIDResponse`/`GetTemplateDefinitionResponse` wrap
  under `{"template": ...}`. This is NOT consistent across all endpoints — the older
  `thepubservice_*` family (`/audits/search`, `/templates/search`,
  `/users/v1/users/list`) returns flat, unwrapped items. Check each endpoint's schema
  individually; do not assume a family-wide rule.
- **Enum casing**: several proto-backed fields are enums with `UPPER_SNAKE_CASE` wire
  values, not the lowercase strings the old SafetyCulture API used — e.g. user status is
  `USER_ACTIVE_STATUS_ACTIVE`/`_DEACTIVATED` (no "pending"), seat type is
  `SUBSCRIPTION_SEAT_TYPE_PREMIUM`/`_LITE`/etc., template item type is
  `ITEM_TYPE_SECTION`/`ITEM_TYPE_TEXT`/etc. Query-string filter enums (like
  `/templates/search`'s `archived=false|true|both`) are a different, plain-lowercase
  convention — verify each field's actual enum values against its schema rather than
  inferring the casing from a sibling field. This class of bug (right endpoint, wrong
  enum value) is easy to miss because requests don't error, they just silently match
  nothing.
- A field name like `owner`/`author`/`creator`/`site` being `{id, name}` in one message
  does not mean it's the same shape everywhere — Task's `creator` User object uses
  `user_id`, not `id`, unlike Template's `owner`/`author`. Check the specific sub-object
  schema, don't extrapolate from an analogous field on a different message.

If you add a new tool group, verify its exact path/request/response shape against
`developer.mitti.com/reference` directly — do not assume it matches the old
SafetyCulture docs or training data, and do not assume a REST-shaped path just because
older ones were.

---

## Tool Writing Rules

- Every `@mcp.tool` must have a clear `description=` — the AI uses this to decide which tool to call
- Use Pydantic v2 models for all input/output
- Use async httpx for all API calls
- Handle 401, 404, 429 (rate limit), and 5xx explicitly
- Return structured dicts, not raw API responses
- When an API limitation forces a design compromise (e.g. a field genuinely
  unavailable from an endpoint), say so in the tool's `description=` rather than
  silently returning `None`/fabricated data — see `inspections.py` and `users.py`
  for examples

---

## Build Order

1. `client.py` — test Mitti API auth with one raw httpx call
2. `tools/inspections.py` — list + get inspection
3. `tools/templates.py` — list templates
4. `tools/actions.py` — list + create action
5. `tools/users.py` — list users
6. `server.py` — import all tools, run `mcp.run()`
7. Test with `fastmcp inspect src/mitti_mcp/server.py`
8. Deploy via Prefect Horizon

---

## What NOT to Do

- Do not use `requests` — use `httpx` async only
- Do not hardcode API tokens
- Do not skip Pydantic models — raw dicts are not acceptable
- Do not invent endpoints — check `developer.mitti.com/reference` first
- Do not use `mcp.resource` for actions that write data — use `mcp.tool` only
- Do not assume an endpoint path/shape carried over unchanged from the old
  SafetyCulture API — verify against current Mitti docs (see migration notes above)

---

## Middleware

`server.py` registers `ErrorHandlingMiddleware`, `LoggingMiddleware`, and
`RateLimitingMiddleware` (from `fastmcp.server.middleware.*`) once at the root
`mcp` instance — they apply to every tool call across all mounted sub-servers.
Do not re-add per-sub-server middleware; add new cross-cutting concerns here.

---

## Approval Gate (Prefab UI)

`server.py` registers `fastmcp.apps.approval.Approval` via `mcp.add_provider(...)`,
which adds a `request_approval` tool (requires `fastmcp[apps]`). Every write tool
(`complete_inspection`, `create_action`, `update_action_status`, `update_action_title`)
must keep "Call request_approval first..." in its `description=` — this is how the LLM
is told to gate the write behind user confirmation. It is advisory only (the LLM must
choose to call it); it is not a substitute for the validation already in `client.py`.
When adding a new write tool, add the same instruction to its description and mention
it in the root `mcp` instructions string.

`inspections.py` also has `list_inspections_view` (`@mcp.tool(app=True)`) — returns a
`prefab_ui.components.DataTable` instead of JSON for visual browsing. It shares
`_fetch_inspections()` with `list_inspections` rather than duplicating the API call.
Follow this pattern (a private `_fetch_x` helper + a plain JSON tool + an `app=True`
DataTable/chart tool) if you add a visual view for another list endpoint.

---

## Testing Each Tool

After writing each tool, run:
```bash
fastmcp inspect src/mitti_mcp/server.py
```

This opens a browser UI where you can call any tool manually and see the real API response.

---

## Definition of Done

- [ ] All tools return Pydantic-validated responses
- [ ] Auth loads from `.env` only
- [ ] Error handling covers 401, 404, 429, 5xx
- [ ] `fastmcp inspect` passes for all tools
- [ ] README has setup + Claude Desktop config example
- [ ] Deployed and live on Prefect Horizon
