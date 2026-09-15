# Mitti MCP Server

A production-grade [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for [Mitti](https://mitti.com) (the 2026 rebrand of SafetyCulture — see [the rebrand FAQ](https://developer.mitti.com/docs/mitti-rebrand-for-developers)), built with [FastMCP](https://gofastmcp.com), Pydantic v2, and async httpx.

Expose your Mitti inspections, templates, actions, and users as MCP tools for any LLM client (Claude Desktop, Claude Code, Cursor, Gemini CLI, and more).

> **Migrated from SafetyCulture to Mitti.** `api.safetyculture.io` still works with no
> announced shutoff date, but `api.mitti.com` is the long-term host and is now the
> default. Legacy `SAFETYCULTURE_API_TOKEN`/`SAFETYCULTURE_BASE_URL` env vars still work
> as a fallback. See **API limitations** below — several endpoints changed shape, not
> just host, in the rebrand.

---

## Features

| Domain | Tools Available |
|---|---|
| **Inspections** | List (lightweight), get (full detail), complete, web report link, visual table view |
| **Templates** | List (lightweight), get (full detail), get definition |
| **Actions** | List, get, create, update status, update title |
| **Users** | List, search (client-side filtered) |

---

## API limitations (read this before relying on a field)

The Mitti API is not a drop-in rename of the old SafetyCulture API — verified against
[developer.mitti.com/reference](https://developer.mitti.com/reference):

- **`list_inspections`** only returns `audit_id`, `template_id`, and `date_modified` —
  the search endpoint's `field` parameter doesn't support name/owner/score/status.
  Call **`get_inspection`** with a specific `audit_id` for full detail.
- **`list_templates`** similarly only returns `template_id`, `name`, and dates. Call
  **`get_template`** for description/owner/archived status.
- **Action priority** is now an org-specific `priority_id` (UUID from your org's
  task-type configuration), not a fixed `low`/`medium`/`high` string. `create_action`
  accepts an optional `priority_id` — omit it for the system default.
- **Action status** IS still a fixed, documented set for the built-in Actions type, so
  `update_action_status` and `list_actions`'s `status` filter keep the friendly
  `open`/`in_progress`/`completed`/`cant_do` interface — translated under the hood to
  Mitti's stable status UUIDs. `list_actions` filters status and `priority_id`
  server-side (via the API's `task_filters`), not by fetching everything and filtering
  in Python.
- **`get_current_user` is unsupported.** Mitti's current API has no "current
  authenticated user" / "me" endpoint at all. The tool returns a clear failure
  explaining this — use `search_users` with a known email instead.
- **User status and role** are proto enums on the wire (e.g.
  `USER_ACTIVE_STATUS_ACTIVE`, `SUBSCRIPTION_SEAT_TYPE_PREMIUM`) — `list_users`'s
  `status` filter accepts the friendly `active`/`inactive` (there is no `pending`
  status), and `UserSummary.status`/`.role` are translated back to short lowercase
  labels rather than leaking the raw wire values.
- **`search_users`** does client-side substring filtering, because the replacement for
  the deprecated email-only search endpoint (`/users/v1/users/list`) only supports
  exact-match filters, not free text.

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- A Mitti API token (see the [Mitti Developer Portal](https://developer.mitti.com))

---

## Setup

### 1. Clone & install

```bash
git clone <your-repo>
cd mitti-mcp

uv venv --python 3.12
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

uv add "fastmcp[apps]" httpx pydantic python-dotenv
```

### 2. Configure your API token

```bash
cp .env.example .env
# Edit .env and set MITTI_API_TOKEN=your_token_here
```

To generate a Mitti API token:
1. Log into Mitti → **Account Settings** → **API Tokens**
2. Click **Generate Token** and copy the value.

### 3. Run and test the server locally

#### Option A: Interactive Inspector UI (Development Mode)
FastMCP includes a browser-based developer inspector interface. Run the command:
```bash
fastmcp dev inspector src/mitti_mcp/server.py
```
This starts your server and prints a link containing an authentication token (e.g., `http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=...`). Open this link in your browser to test each tool.

Alternatively, you can run the inspector without authentication:
```bash
# Windows PowerShell
$env:DANGEROUSLY_OMIT_AUTH="true"; fastmcp dev inspector src/mitti_mcp/server.py

# macOS/Linux/Git Bash
DANGEROUSLY_OMIT_AUTH=true fastmcp dev inspector src/mitti_mcp/server.py
```

#### Option B: Inspect definitions via CLI
Check the tool schemas and registered components directly on the command line:
```bash
fastmcp inspect src/mitti_mcp/server.py
```

#### Option C: Call tools from the CLI
You can query and execute specific tools directly from the terminal:
```bash
# List all tools and parameters
fastmcp list src/mitti_mcp/server.py

# Execute a tool with parameters
fastmcp call src/mitti_mcp/server.py list_users limit=5
```

#### Option D: Run directly via Python
To run the server directly (using stdio transport):
```bash
uv run python -m mitti_mcp.server
```

---

## Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "mitti": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/mitti-mcp",
        "run",
        "python",
        "-m",
        "mitti_mcp.server"
      ],
      "env": {
        "MITTI_API_TOKEN": "your_token_here"
      }
    }
  }
}
```

---

## Deployment (Prefect Horizon)

To deploy your server live to the cloud:
1. Push your repository to GitHub (public or private).
2. Sign in to [horizon.prefect.io](https://horizon.prefect.io).
3. Connect your GitHub account and select your repository.
4. Configure your deployment:
   - **Server name**: A unique name for your server (this determines your server's endpoint URL).
   - **Entrypoint**: `src/mitti_mcp/server.py:mcp`
   - **Authentication**: Enable to secure your server endpoints with OAuth.
5. Click **Deploy Server** to build and launch your live production endpoint.

---

## Deployment (Render)

A [Render Blueprint](https://render.com/docs/blueprint-spec) is included (`render.yaml`)
that runs the server over streamable-HTTP instead of stdio:

1. Push this repo to GitHub.
2. On [render.com](https://render.com), click **New +** → **Blueprint** and select this repo.
3. Render reads `render.yaml` automatically. When prompted, set the `MITTI_API_TOKEN`
   environment variable (it's intentionally left blank in the blueprint — never commit
   a real token).
4. Deploy. The MCP endpoint is served at `https://<your-service>.onrender.com/mcp`
   (not `/`) — point streamable-HTTP MCP clients at that path.

Not yet verified against a live Render deploy: Render's default health check hits `/`,
which this server doesn't serve (only `/mcp`). If the service is marked unhealthy
despite running fine, set `healthCheckPath: /mcp` in `render.yaml` or add a trivial
health route.

---

## Project Structure

```
mitti-mcp/
├── AGENTS.md                    # Agent instructions
├── README.md
├── pyproject.toml
├── .env.example
├── src/
│   └── mitti_mcp/
│       ├── __init__.py
│       ├── server.py            # FastMCP app entry point
│       ├── client.py            # httpx Mitti API client
│       ├── tools/
│       │   ├── inspections.py   # Inspection tools
│       │   ├── actions.py       # Action tools
│       │   ├── templates.py     # Template tools
│       │   └── users.py         # User tools
│       └── models/
│           └── schemas.py       # Pydantic v2 models
└── tests/
    └── test_tools.py
```

---

## Tech Stack

| Layer | Tool |
|---|---|
| MCP framework | [FastMCP](https://gofastmcp.com) 4.x |
| HTTP client | httpx (async) |
| Validation | Pydantic v2 |
| Python | 3.12+ |
| Package manager | uv |

---

## Middleware

The server applies cross-cutting middleware (`src/mitti_mcp/server.py`) to every
tool call across all mounted sub-servers, in this order:

1. **`ErrorHandlingMiddleware`** — catches and logs unhandled exceptions consistently.
2. **`LoggingMiddleware`** — logs every request/response with duration and payload size.
3. **`RateLimitingMiddleware`** — global token-bucket limit (default 10 req/s, override
   with `MITTI_MCP_RATE_LIMIT_RPS`) to protect the Mitti API from bursts.

---

## Human-in-the-Loop Approval (Prefab UI)

Requires `fastmcp[apps]` (already in `pyproject.toml`). The server registers FastMCP's
`Approval` provider, which exposes a `request_approval` tool. The server instructions
and the descriptions of all write tools (`complete_inspection`, `create_action`,
`update_action_status`, `update_action_title`) tell the LLM to call `request_approval`
and wait for the user's decision before performing the write.

The user sees an Approve/Reject card rendered inline in the conversation (an MCP Apps
UI component, not plain text). Clicking a button sends `"<summary>" — I selected:
Approve/Reject` back into the conversation as if the user typed it.

**This is an advisory gate, not server-side enforcement** — it relies on the LLM
following the instructions. It does not replace the input validation and error
handling already in `client.py` and the tool modules.

Try it: `fastmcp call src/mitti_mcp/server.py request_approval summary="..."`

### Visual inspection browsing

`list_inspections_view` (`app=True`) returns the same data as `list_inspections` but as
an interactive, sortable, searchable `DataTable` rendered inline in the conversation
instead of raw JSON. The LLM picks this tool over `list_inspections` when the user
wants to browse/sort/search visually.

---

## License

MIT
