# Salesforce OAuth Connector - Simple POC

## Overview

A minimalist **proof-of-concept** FastAPI backend that demonstrates Salesforce OAuth2 integration. This standalone connector validates the core OAuth handshake, token management, and API calling capabilities that will be integrated into the larger AutonomOS platform's AAM (Adaptive API Mesh) layer.

**Purpose:** Prove we can reliably:
- Execute correct OAuth2 handshake with Salesforce
- Store and manage access/refresh tokens
- Automatically refresh expired tokens
- Make authenticated Salesforce REST API calls

**Key Characteristic:** No frontend - all interactions through FastAPI's auto-generated Swagger UI at `/docs`. This is a developer/admin utility focused on reliability and simplicity.

## User Preferences

Preferred communication style: Simple, everyday language.

**CRITICAL DEVELOPMENT PRINCIPLE:**
**FOUNDATIONAL/FUNDAMENTAL FIXES ONLY** - When facing issues or bugs, ALWAYS choose fundamental/root-cause fixes over workarounds. No band-aids, no quick patches, no shortcuts. Fix the underlying architectural issue even if it takes longer.

**Development Approach:**
- Iterative development with small, frequent updates
- Ask for approval before major architectural changes
- Clear, concise explanations for simple concepts; detailed explanations for complex ones
- Focus on stability and ease of reasoning - the user (ilya) is not a coder and interacts via HTTP endpoints only

**Planning Guidelines:**
- NEVER reference time/duration estimates in task descriptions
- Organize by logical phases and dependencies, not timelines
- Use priority levels (P0/Critical, High, Medium, Low) instead of schedules

## System Architecture

### Technology Stack

**Core Framework:**
- **FastAPI** - Modern async Python web framework with automatic OpenAPI documentation
- **Uvicorn** - ASGI server for running FastAPI applications
- **SQLite** - Embedded database for credential storage (no external DB required)
- **httpx** - Async HTTP client for Salesforce API calls
- **Pydantic** - Data validation via type annotations

**Why These Choices:**
- **FastAPI over Flask/Django:** Built-in Swagger UI eliminates need for custom frontend, automatic request/response validation, async support for better performance with external API calls
- **SQLite over PostgreSQL:** Zero configuration, file-based storage suitable for single-tenant POC, easier debugging and portability
- **httpx over requests:** Async-native HTTP client matches FastAPI's async model, better connection pooling for token refresh scenarios

**Workflow Configuration:**
- The app runs via Replit's "Start application" workflow
- Created minimal package.json that bridges npm to uvicorn: `npm run dev` → `uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload`
- This allows the default workflow to properly start the Python/FastAPI application

### Application Structure

```
app/
├── __init__.py          # Package initialization
├── main.py              # FastAPI app definition and endpoints
├── db.py                # SQLite database operations
└── salesforce.py        # OAuth flow and API client logic
```

**Separation of Concerns:**
- `main.py` - HTTP layer: request/response handling, input validation via Pydantic models
- `db.py` - Data layer: all SQLite operations, schema management
- `salesforce.py` - Integration layer: OAuth handshake, token refresh, API calls

### Data Model

**Single-Table Design (`salesforce_credentials`):**

Purpose: Store OAuth credentials and connection state for one Salesforce org (single-row table with `id=1` for POC simplicity)

**Schema Fields:**
- `id` (INTEGER PRIMARY KEY) - Always 1 for this POC
- `environment` (TEXT) - 'production' | 'sandbox' | 'custom'
- `base_url` (TEXT) - Auth endpoint (login.salesforce.com, test.salesforce.com, or custom)
- `instance_url` (TEXT) - Org-specific URL returned by Salesforce after authentication
- `client_id` (TEXT) - Connected App consumer key
- `client_secret` (TEXT) - Connected App consumer secret
- `access_token` (TEXT) - Short-lived OAuth token for API calls
- `refresh_token` (TEXT) - Long-lived token for obtaining new access tokens
- `token_type` (TEXT) - Usually "Bearer"
- `expires_at` (TEXT) - Absolute timestamp when access token expires
- `status` (TEXT) - 'disconnected' | 'connected' | 'error'
- `error_message` (TEXT) - Last error encountered (nullable)
- `state` (TEXT) - CSRF protection token for OAuth flow
- `callback_url` (TEXT) - Redirect URI registered with Salesforce
- `updated_at` (TEXT) - Last modification timestamp

**Design Decision - Single Row:**
- **Problem:** POC needs to prove OAuth mechanics, not multi-org management
- **Solution:** Single-row constraint (always `id=1`) simplifies queries and state management
- **Alternative Considered:** Multi-row with org selection logic (rejected as scope creep)
- **Pro:** Eliminates complexity of org selection, connection routing
- **Con:** Cannot test multiple simultaneous Salesforce connections (acceptable for POC scope)

### OAuth2 Flow Architecture

**Three-Step Authentication Process:**

1. **Authorization Request (`POST /api/connectors/salesforce/start`):**
   - User provides: environment type, client credentials, optional custom domain
   - System generates: Salesforce authorization URL with CSRF state token
   - Stores: client credentials, callback URL, state token in database
   - Returns: URL for user to visit in browser

2. **Callback Handling (`GET /oauth/callback/salesforce`):**
   - Salesforce redirects back with: authorization code, state token
   - System validates: state token matches (CSRF protection)
   - Exchanges: authorization code for access_token + refresh_token
   - Stores: tokens with calculated expiry time
   - Updates: status to 'connected'
   - Returns: HTML success page with token details

3. **Automatic Token Refresh (within `call_salesforce()`):**
   - Before every API call: checks if access_token is expired
   - If expired: uses refresh_token to obtain new access_token
   - Updates: database with new token and expiry
   - Continues: with API call using fresh token

**CSRF Protection via State Parameter:**
- Random 32-byte URL-safe token generated using `secrets.token_urlsafe(32)`
- Stored in database before redirect to Salesforce
- Validated on callback to prevent authorization code injection attacks

### API Endpoint Design

**Health Check:**
- `GET /health` - Returns `{"status": "ok"}` to verify server is running

**OAuth Flow:**
- `POST /api/connectors/salesforce/start` - Initiates OAuth, returns authorization URL
- `GET /oauth/callback/salesforce` - Handles Salesforce redirect, exchanges code for tokens

**Connection Management:**
- `GET /api/connectors/salesforce/status` - Returns current connection state
- `POST /api/connectors/salesforce/disconnect` - Revokes tokens and resets state

**API Testing:**
- `GET /api/connectors/salesforce/test` - Calls Salesforce REST API to validate credentials

**Design Principle - Swagger-First:**
All endpoints are documented via FastAPI's automatic OpenAPI generation. Users interact exclusively through the `/docs` interface, eliminating need for custom frontend development.

### Error Handling Strategy

**Custom Exception Class:**
```python
class SalesforceError(Exception):
    """Custom exception for Salesforce API errors"""
```

**Error Propagation:**
- Salesforce API errors → `SalesforceError` with detailed message
- HTTP errors from httpx → Wrapped in `HTTPException` with appropriate status code
- Database errors → Logged and returned as 500 Internal Server Error

**User-Facing Errors:**
- Store `error_message` in database for persistent error state
- Return error details in endpoint responses for immediate feedback
- Update `status` to 'error' to prevent further operations until resolved

### Token Refresh Mechanism

**Automatic Refresh Logic (in `salesforce.py`):**

```
Before every API call:
1. Load current credentials from database
2. Parse expires_at timestamp
3. If expired or expires within 60 seconds:
   a. Call Salesforce token endpoint with refresh_token
   b. Receive new access_token and updated expiry
   c. Update database with new token
   d. Proceed with API call
4. Else:
   Use existing access_token
```

**Design Decision - Proactive Refresh:**
- **Problem:** Access tokens expire, causing API call failures mid-operation
- **Solution:** Check expiry before every call, refresh preemptively with 60-second buffer
- **Alternative Considered:** Reactive refresh (retry on 401 error) - rejected due to added complexity
- **Pro:** Eliminates API call failures due to race conditions near expiry
- **Con:** Slightly more database reads (acceptable for POC scale)

## External Dependencies

### Salesforce Connected App Setup

**Required Configuration in Salesforce:**
1. Create Connected App in Salesforce Setup
2. Enable OAuth Settings
3. Set Callback URL to match application deployment (e.g., `https://yourproject.username.repl.co/oauth/callback/salesforce`)
4. Select OAuth Scopes: `api`, `refresh_token`, `offline_access`
5. Save to obtain Client ID and Client Secret

**Environment Variables Required:**
- `SALESFORCE_CALLBACK_URL` - Full callback URL registered with Salesforce Connected App

**Salesforce API Endpoints:**
- **Production:** `https://login.salesforce.com`
- **Sandbox:** `https://test.salesforce.com`
- **Custom:** User-provided domain for My Domain orgs

### Python Package Dependencies

**Core Requirements:**
- `fastapi` - Web framework
- `uvicorn[standard]` - ASGI server with WebSocket support
- `httpx` - Async HTTP client for Salesforce API
- `pydantic` - Data validation (included with FastAPI)
- `python-dotenv` - Environment variable management

**Why httpx over requests:**
- Async/await support matches FastAPI's async model
- Better connection pooling for repeated token refresh operations
- Modern API design with timeout handling built-in

### Database

**SQLite - Embedded Database:**
- File location: `salesforce.db` in project root
- No external service required
- Schema created automatically via `init_db()` on application startup

**Schema Initialization:**
- Executes `CREATE TABLE IF NOT EXISTS` on first run
- Safe to run multiple times (idempotent)
- No migration framework needed for POC scope

### Deployment Considerations

**Replit-Specific:**
- Uses Replit Secrets for `SALESFORCE_CALLBACK_URL` environment variable
- Public URL format: `https://yourproject.username.repl.co`
- Auto-runs via `.replit` configuration or manual `./start.sh`

**Port Configuration:**
- Listens on `0.0.0.0:5000` for Replit's reverse proxy
- Accessible at root domain (Replit handles port mapping)

**Startup Scripts:**
- `start.sh` - Recommended launcher with proper uvicorn flags
- `run.sh` - Alternative startup method
- Direct uvicorn command for debugging

**Critical Setup Step:**
User MUST configure `SALESFORCE_CALLBACK_URL` in Replit Secrets to match their deployment URL before OAuth will function. This is the #1 setup error.