# AAM - Adaptive API Mesh

## Global Architecture Pivot (January 2026)

> **Self-Healing Mesh + Zero-Trust Vision**

| Component | Role | Boundary |
|-----------|------|----------|
| **AAM** | The Mesh | Owns Self-Healing and Repair (ACTIVE, not passive) |
| **Farm** | The Verifier | Strictly a Test Oracle (no ops) |
| **DCL** | The Brain | Metadata-Only (no raw data buffering) |
| **AOA** | The Orchestrator | Owns Execution and Infrastructure |

All refactoring must adhere to these four boundary changes.

## Overview

AAM (Adaptive API Mesh) is the self-healing integration mesh that inventories reusable data pipes, makes their behavior explicit, and owns repair operations.

**Core Philosophy:**
> "We do not change how data moves. We make its behavior and meaning explicit. We self-heal when things drift."

**AAM's Role:**
- Ingest connection intent (ConnectionCandidates)
- Attach to existing enterprise integration fabric (control planes)
- Inventory reusable data pipes via collectors
- Infer minimal semantics about those pipes
- Publish DeclaredPipes for DCL to consume
- **Own self-healing and repair operations**

**AAM Does NOT:**
- Move data
- Transform data
- Act as an iPaaS
- Act as a Kafka / streaming platform
- Build per-app SaaS connectors
- Handle infrastructure (delegated to AOA)
- Handle ops (delegated to AOA)

## User Preferences

Preferred communication style: Simple, everyday language.

**CRITICAL DEVELOPMENT PRINCIPLE:**
**FOUNDATIONAL/FUNDAMENTAL FIXES ONLY** - When facing issues or bugs, ALWAYS choose fundamental/root-cause fixes over workarounds.

**Development Approach:**
- Iterative development with small, frequent updates
- Focus on stability and ease of reasoning
- All interactions through FastAPI's Swagger UI at `/docs`

## System Architecture

### Technology Stack

- **FastAPI** - Modern async Python web framework with automatic OpenAPI documentation
- **Uvicorn** - ASGI server for running FastAPI applications
- **SQLite** - Embedded database (aam.db)
- **Pydantic** - Data validation and models
- **httpx** - Async HTTP client (for future real collectors)

### Application Structure

```
app/
├── __init__.py           # Package initialization
├── main.py               # FastAPI app and all API endpoints
├── models.py             # Pydantic models (ConnectionCandidate, DeclaredPipe, etc.)
├── db.py                 # SQLite database operations
├── inference.py          # Converts observations to DeclaredPipes
├── salesforce.py         # (Legacy) Salesforce OAuth - future collector reference
└── collectors/
    ├── __init__.py
    └── mock.py           # Mock collector for testing
samples/
├── connection_candidate.json   # Sample AOD input
└── declared_pipe.json          # Sample DCL output
```

## Data Models

### Input Contract (from AOD)

**ConnectionCandidate** - Represents intent + context for a potential connection:

| Field | Type | Description |
|-------|------|-------------|
| asset_key | string | Unique identifier for the asset |
| vendor_name | string | Vendor/provider name (e.g., "Salesforce") |
| display_name | string | Human-readable name |
| category | string | Asset category (CRM, ERP, HRIS, iPaaS) |
| governance_status | string? | Governance classification |
| findings | array | Discovery findings from AOD |
| sor_tagging | string? | System of Record tagging |
| evidence_refs | array | References to evidence |
| signals_summary | string? | Summary of discovery signals |
| known_endpoints | array | Known API endpoints |
| preferred_modality | enum? | CONTROL_PLANE, DECLARED_INTERFACE, PASSIVE_SUBSCRIPTION, MINIMAL_TEE |
| priority_score | float? | Priority score 0-100 |

### Output Contract (to DCL)

**DeclaredPipe** - AAM's only product, consumed by DCL:

| Field | Type | Description |
|-------|------|-------------|
| pipe_id | uuid | Unique pipe identifier |
| display_name | string | Human-readable name |
| fabric_plane | enum | IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE |
| modality | enum | CONTROL_PLANE, DECLARED_INTERFACE, PASSIVE_SUBSCRIPTION, MINIMAL_TEE |
| source_system | string | Source system identifier |
| transport_kind | enum | API, EVENT_STREAM, TABLE, FILE, WEBHOOK |
| endpoint_ref | dict | Opaque reference to endpoint |
| entity_scope | array | Entities covered by this pipe |
| identity_keys | array | Keys that identify records |
| change_semantics | enum | SNAPSHOT, APPEND_ONLY, CDC_UPSERT, UNKNOWN |
| provenance | object | Origin and lineage information |
| owner_signals | array | Ownership signals |
| trust_labels | array | Trust and quality labels |
| schema_info | object? | Schema hash, ref, version |
| freshness | string? | Data freshness indicator |
| access | object? | Access information (NO SECRETS) |

## Operator UI (v1 Practical Interface)

**The only 3 operator jobs AAM supports:**
1. See what pipes exist (inventory + metadata + trust state)
2. See what's wrong (drift/health/coverage gaps, with evidence)
3. Take a bounded action (re-run collectors, approve/track tee requests, set owner tags, export to DCL)

### UI Screens

| Route | Screen | Purpose |
|-------|--------|---------|
| `/ui/pipes` | Pipes Inventory | View all pipes, run collectors, export to DCL |
| `/ui/pipes/{id}` | Pipe Detail | View pipe details, provenance, drift timeline |
| `/ui/candidates` | Candidates | View AOD candidates, match/defer, create tee requests |
| `/ui/drift` | Drift & Health | View drift events, acknowledge/suppress |

### UI Controls (Real Actions Only)

**Allowed v1 actions:**
- Run collectors (with run tracking)
- Rerun inference
- Tag/override owner metadata
- Create/track tee request artifacts
- Suppress/ack drift alerts
- Export declared pipes snapshot
- Match candidate to pipe
- Defer candidate with reason

**Not allowed (not implemented):**
- "Fix drift automatically"
- "Connect now"
- "Provision connector"
- "Rotate secrets"
- "Deploy tee"

## API Endpoints

### Candidate Intake (from AOD)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/aam/candidates` | Create connection candidate |
| GET | `/api/aam/candidates` | List candidates (optional status filter) |
| GET | `/api/aam/candidates/{id}` | Get single candidate |
| PATCH | `/api/aam/candidates/{id}/status` | Update candidate status |
| POST | `/api/candidates/{id}/match` | Match candidate to pipe |
| POST | `/api/candidates/{id}/defer` | Defer candidate with reason |

**Candidate Statuses:** `new`, `triaged`, `connected`, `deferred`

### Collectors

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/aam/collectors` | List all collectors |
| POST | `/api/collect/{collector}/run` | Run collector (with tracking) |
| GET | `/api/collect/runs` | List collector runs |
| GET | `/api/collect/runs/{run_id}` | Get specific run details |
| POST | `/api/aam/infer` | Process observations into pipes |

### Pipe Registry (for DCL)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pipes` | List all declared pipes |
| GET | `/api/pipes/{id}` | Get single pipe |
| GET | `/api/pipes/{id}/versions` | Get pipe version history |
| GET | `/api/pipes/{id}/drift` | Get drift events for pipe |

### Export for DCL

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/export/dcl/declared-pipes` | Export all pipes in DCL format |

### Drift Detection

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/drift` | List all drift events |
| POST | `/api/drift/{drift_id}/ack` | Acknowledge drift event |
| POST | `/api/drift/{drift_id}/suppress` | Suppress drift event |

### Tee Requests

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/tee/requests` | Create tee request |
| GET | `/api/tee/requests` | List tee requests |
| POST | `/api/tee/requests/{id}/status` | Update tee request status |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |

### Presets & Seed Data

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/presets` | List available enterprise maturity presets |
| GET | `/api/presets/{id}` | Get preset details |
| POST | `/api/presets/{id}/load` | Load preset into database (replaces existing data) |
| GET | `/api/stats` | Get pipe statistics by fabric_plane/modality |
| DELETE | `/api/data` | Clear all data (admin)

## Database Schema

**Tables:**

1. **connection_candidates** - Input from AOD
2. **collectors** - Registered collectors (mock, future iPaaS, API Gateway)
3. **observations** - Raw data from collectors
4. **declared_pipes** - Current pipe registry
5. **pipe_versions** - Version history for pipes
6. **drift_events** - Schema/freshness/contract drift events
7. **tee_requests** - Minimal tee request artifacts

**Drift Detection:**
- Schema hash computed from normalized schema payload
- New version + drift event created when hash changes
- Supports schema, freshness, and contract drift types

## Inference Engine

The inference engine converts observations into DeclaredPipes by inferring:

1. **Fabric Plane** - WHERE pipes live (IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE)
2. **Modality** - HOW pipes are accessed (CONTROL_PLANE, DECLARED_INTERFACE, etc.)
3. **Transport Kind** - From URL patterns (API, EVENT_STREAM, TABLE, FILE, WEBHOOK)
4. **Entity Scope** - From entity hints and URL path segments
5. **Identity Keys** - From schema field patterns (id, uuid, *_id)
6. **Change Semantics** - From URL patterns and schema timestamps
7. **Provenance** - Collector info, discovery time, lineage hints
8. **Trust Labels** - Weak signals become labels, not blockers

### Fabric Plane Inference
- **IPAAS** - Workato, MuleSoft, Boomi, Tray.io, Zapier vendors
- **EVENT_BUS** - Kafka/EventBridge URLs, EVENT_STREAM transport
- **DATA_WAREHOUSE** - Snowflake/BigQuery/Redshift vendors, TABLE/FILE transport
- **API_GATEWAY** - Default for direct API access

## Enterprise Maturity Presets

AAM includes 4 realistic preset datasets representing different enterprise integration patterns:

| Preset | Description | Pipes | Pattern |
|--------|-------------|-------|---------|
| early_scrappy | Point-to-point, direct API calls | 6 | API_GATEWAY heavy |
| ipaas_centric | Workato/MuleSoft control plane | 8 | IPAAS + CONTROL_PLANE |
| platform_oriented | Kafka/EventBridge backbone | 9 | EVENT_BUS + mixed modalities |
| warehouse_centric | Snowflake/BigQuery as truth | 11 | DATA_WAREHOUSE + reverse ETL |

Load via UI (Pipes Inventory → preset cards) or API (`POST /api/presets/{id}/load`)

## Usage Flow

### Quick Start

1. **Create a candidate** (simulates AOD sending intent):
```bash
POST /api/aam/candidates
{
  "asset_key": "sf-001",
  "vendor_name": "Salesforce",
  "display_name": "Salesforce CRM",
  "category": "CRM",
  "known_endpoints": ["/services/data/v58.0/sobjects/Account"]
}
```

2. **Run mock collector** (generates observations):
```bash
POST /api/aam/collectors/mock/run
```

3. **Run inference** (creates pipes from observations):
```bash
POST /api/aam/infer
```

4. **View declared pipes** (ready for DCL):
```bash
GET /api/pipes
```

5. **Export for DCL**:
```bash
GET /api/export/dcl/declared-pipes
```

## MVP Roadmap

### MVP-0 (Complete)
- ✅ Candidate intake API
- ✅ Mock collector
- ✅ DeclaredPipe inference
- ✅ Pipe registry APIs
- ✅ Schema hash + drift detection

### MVP-1 (Current - Practical Interface)
- ✅ 4 operator UI screens (Pipes, Pipe Detail, Candidates, Drift & Health)
- ✅ Collector run tracking
- ✅ Candidate match/defer workflows
- ✅ Drift acknowledge/suppress
- ✅ Tee request management

### MVP-2 (Next)
- One real collector (Salesforce API inventory)
- Freshness drift detection
- Ownership inference improvements

## Documentation

- **User Guide**: `docs/USER_GUIDE.md` - Plain-English guide explaining each screen, element, and workflow
- **API Documentation**: `/docs` (Swagger UI) - Complete API endpoint documentation
- **Sample Data**: `samples/` directory contains example JSON for candidates and pipes

## Deployment

**Port Configuration:**
- Listens on `0.0.0.0:5000`
- Accessible at root domain via Replit's reverse proxy

**Startup:**
- Runs via `npm run dev` → `uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload`
- Database initializes automatically on startup

**API Documentation:**
- Swagger UI: `/docs`
- ReDoc: `/redoc`
