# AAM - Adaptive API Mesh

## What AAM Does

AAM is the **self-healing integration mesh** that observes, documents, and maintains enterprise data pipes. AAM makes data pipe behavior and meaning explicit **without changing how data moves**.

### The Problem AAM Solves

Enterprises have dozens of integration points spread across:
- **iPaaS platforms** (Workato, MuleSoft, Tray.io)
- **API gateways** (Kong, Apigee, AWS API Gateway)
- **Event buses** (Kafka, EventBridge, Pulsar)
- **Data warehouses** (Snowflake, BigQuery, Redshift)

Nobody knows what pipes exist, who owns them, whether they're healthy, or when schemas change. AAM creates a **single inventory of all data pipes** with metadata, health status, and ownership - then **self-heals when things drift**.

### Core Philosophy

> "We do not change how data moves. We make its behavior and meaning explicit. We self-heal when things drift."

### AAM Does vs Does NOT

| AAM Does | AAM Does NOT |
|----------|--------------|
| Observe and document integration fabrics | Move or transform data |
| Connect to Fabric Planes (not individual apps) | Act as iPaaS replacement |
| Inventory reusable data pipes | Build per-app SaaS connectors |
| Infer metadata about pipes | Handle infrastructure operations |
| Detect schema and connectivity drift | Provision new connectors |
| Self-heal connectivity issues | Rotate secrets or deploy TEE |
| Publish clean pipe inventory to DCL | Replace existing integration platforms |

---

## System Architecture

### The Big Picture

AAM sits between AOD (discovery) and DCL (semantic layer):

```
AOD (discovers what exists) → AAM (catalogs pipes, self-heals) → DCL (unifies meaning)
```

- **AOD** discovers what systems exist and sends ConnectionCandidates to AAM
- **AAM** catalogs connections as DeclaredPipes with behavioral metadata
- **DCL** consumes DeclaredPipes to build unified business understanding


---

## Connectivity Modalities

AAM supports four connection patterns:

| Mode | Description | Use Case |
|------|-------------|----------|
| **Control-Plane Attachment** | Read-only visibility into APIs, integrations, ownership | Primary enterprise pattern |
| **Declared Interface Consumption** | MuleSoft System APIs or enterprise-approved APIs | Standardized access |
| **Passive Subscription** | Kafka topics, Event Hub, Snowflake tables/streams | Event-driven data |
| **Minimal Tee** | One additional sink added to existing flow | Explicit enablement only |

---

## Fabric Plane Integrations

> **CRITICAL:** AAM connects to Fabric Planes, NOT individual SaaS apps (except in Scrappy mode)

| Plane Type | Example Systems | Capabilities |
|------------|-----------------|--------------|
| **iPaaS** | Workato, MuleSoft, Tray.io, Celigo | Webhook signals, recipe changes |
| **API Gateway** | Kong, Apigee, AWS API Gateway | API catalogs, traffic patterns |
| **Event Bus** | Kafka, EventBridge, Pulsar | Schema registries, topic metadata |
| **Data Warehouse** | Snowflake, BigQuery, Redshift | Table schemas, freshness metadata |

### Connect to a Fabric Plane
```
POST /api/adapters/api_gateway/connect
POST /api/adapters/ipaas/connect
POST /api/adapters/event_bus/connect
POST /api/adapters/data_warehouse/connect
```

---

## Core Capabilities

### 1. Pipe Discovery

Automatic detection of existing integration endpoints:
- Protocol inference (REST, GraphQL, SOAP, gRPC)
- Ownership and responsibility mapping
- Entity scope identification

**Run discovery:**
```
POST /api/collect/adapter/run   # From connected adapters
POST /api/collect/mock/run      # Mock data for testing
```

### 2. Pipe Inference

Converts raw observations into DeclaredPipes with rich metadata:

| Field | What It Describes |
|-------|-------------------|
| **Fabric Plane** | WHERE the pipe lives (iPaaS, API Gateway, Event Bus, Data Warehouse) |
| **Modality** | HOW the pipe is accessed (Control Plane, Declared Interface, etc.) |
| **Transport Kind** | Data movement type (API, Event Stream, Table, File, Webhook) |
| **Entity Scope** | Business entities that flow through (Account, Contact, Order) |
| **Identity Keys** | How records are identified (id, uuid, account_id) |
| **Change Semantics** | How data changes (Snapshot, Append-Only, CDC Upsert) |
| **Trust Labels** | Quality signals (verified_owner, schema_stable, high_traffic) |

**Run inference:**
```
POST /api/aam/infer
```

### 3. Schema Drift Detection

- Fingerprinting for change detection
- Automatic alerting on breaking changes
- Historical tracking of schema evolution

**View drift:**
```
GET /api/drift
```

### 4. Self-Healing

AAM actively monitors and repairs connectivity issues:

| Drift Type | What It Detects | Self-Heal Action |
|------------|-----------------|------------------|
| **Connection Drift** | Lost connectivity to Fabric Plane | Reconnect adapter |
| **Consumer Lag** | Event Bus consumers falling behind | Restart consumers |
| **Warehouse Suspend** | Warehouse compute suspended | Wake warehouse |
| **Schema Drift** | Field changes in pipe schemas | Log version, alert operators |

**Trigger self-heal:**
```
POST /api/adapters/{plane_type}/self-heal
```

**View fabric drift:**
```
GET /api/fabric-drift
GET /api/fabric-drift/heal-history
```

### 5. Enterprise Maturity Presets

Four configurations for different enterprise integration patterns:

| Preset | Description | Primary Plane |
|--------|-------------|---------------|
| **Scrappy** | Direct point-to-point API calls | API Gateway |
| **iPaaS-Centric** | Workato/MuleSoft as control plane | iPaaS |
| **Platform-Oriented** | Kafka/EventBridge backbone | Event Bus |
| **Warehouse-Centric** | Snowflake/BigQuery as source of truth | Data Warehouse |

**Activate a preset:**
```
POST /api/preset-config/{preset_name}/activate
```

### 6. Governance Enforcement

Policies applied during all discovery and collection:

| Policy | What It Does |
|--------|--------------|
| **PII Redaction** | Removes personal data from observations |
| **Rate Limiting** | Prevents overloading Fabric Planes |
| **Auth Enforcement** | Validates credentials before operations |
| **Block Direct Access** | Prevents direct app connections (non-Scrappy) |

### 7. Candidate Workflow

Incoming connection requests from AOD:

| Status | Meaning | Operator Action |
|--------|---------|-----------------|
| **new** | Just received | Triage |
| **triaged** | Reviewed | Match to pipe or defer |
| **connected** | Matched | Complete |
| **deferred** | Not connecting | Provide reason |

---

## Operator Interface

### The Three Operator Jobs

1. **See what pipes exist** - Inventory, metadata, trust state
2. **See what's wrong** - Drift, health gaps, coverage issues
3. **Take bounded actions** - Run collectors, acknowledge drift, export

### UI Screens

| Screen | URL | Purpose |
|--------|-----|---------|
| **Topology** | `/ui/topology` | Visual graph of Fabric Planes, pipes, and relationships |
| **Pipes** | `/ui/pipes` | List all pipes, run collectors, export |
| **Pipe Detail** | `/ui/pipes/{id}` | Deep dive on single pipe |
| **Candidates** | `/ui/candidates` | Review candidates, match or defer |
| **Drift & Health** | `/ui/drift` | Active drift events, acknowledge/suppress |
| **Guide** | `/ui/guide` | In-app documentation |

### Allowed Actions

- Run collectors (adapter or mock)
- View and filter pipe inventory
- Match candidates to pipes
- Defer candidates with reasons
- Acknowledge or suppress drift
- Export pipes to DCL format
- Switch enterprise presets

### NOT Allowed (by design)

- Automatically fix schema drift
- Provision new connectors
- Rotate secrets
- Deploy TEE infrastructure

---

## API Reference

### Fabric Plane Adapters

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/adapters` | List all adapters with status |
| POST | `/api/adapters/{plane}/connect` | Connect to Fabric Plane |
| POST | `/api/adapters/{plane}/disconnect` | Disconnect from Fabric Plane |
| GET | `/api/adapters/{plane}/health` | Check adapter health |
| POST | `/api/adapters/{plane}/discover` | Discover pipes from plane |
| POST | `/api/adapters/{plane}/self-heal` | Execute self-heal |

### Preset Configuration

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/preset-config` | Get current preset |
| GET | `/api/preset-config/all` | List all presets |
| POST | `/api/preset-config/{name}/activate` | Switch preset |
| POST | `/api/preset-config/validate-routing` | Validate routing decision |

### Fabric Drift

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/fabric-drift` | List fabric drift events |
| GET | `/api/fabric-drift/stats` | Get drift statistics |
| GET | `/api/fabric-drift/heal-history` | Get self-heal history |
| POST | `/api/fabric-drift/{id}/ack` | Acknowledge drift |
| POST | `/api/fabric-drift/{id}/suppress` | Suppress drift |

### Collectors

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/aam/collectors` | List collectors |
| POST | `/api/collect/mock/run` | Run mock collector |
| POST | `/api/collect/adapter/run` | Run adapter collector |
| GET | `/api/collect/runs` | List collector runs |
| POST | `/api/aam/infer` | Process observations to pipes |

### Pipes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pipes` | List declared pipes |
| GET | `/api/pipes/{id}` | Get pipe details |
| GET | `/api/pipes/{id}/versions` | Get version history |
| GET | `/api/pipes/{id}/drift` | Get drift for pipe |
| GET | `/api/export/dcl/declared-pipes` | Export for DCL |

### Candidates

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/aam/candidates` | Create candidate |
| GET | `/api/aam/candidates` | List candidates |
| GET | `/api/aam/candidates/{id}` | Get candidate |
| PATCH | `/api/aam/candidates/{id}/status` | Update status |
| POST | `/api/candidates/{id}/match` | Match to pipe |
| POST | `/api/candidates/{id}/defer` | Defer candidate |

### Schema Drift & Tee

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/drift` | List schema drift events |
| POST | `/api/drift/{id}/ack` | Acknowledge drift |
| POST | `/api/drift/{id}/suppress` | Suppress drift |
| POST | `/api/tee/requests` | Create tee request |
| GET | `/api/tee/requests` | List tee requests |

### Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/presets` | List database presets |
| POST | `/api/presets/{id}/load` | Load preset data |
| GET | `/api/stats` | Get pipe statistics |
| DELETE | `/api/data` | Clear all data |
| GET | `/health` | Health check |

---

## Quick Start

### Option 1: Load a Preset (Fastest)
```bash
POST /api/preset-config/ipaas_centric/activate
POST /api/presets/ipaas_centric/load
GET /api/pipes
```

### Option 2: Full Discovery Flow
```bash
POST /api/adapters/api_gateway/connect
POST /api/collect/adapter/run
POST /api/aam/infer
GET /api/pipes
```

### Option 3: Mock Data (Testing)
```bash
POST /api/collect/mock/run
POST /api/aam/infer
GET /api/pipes
```

---

## Technology Stack

- **FastAPI** - Async Python web framework
- **SQLite** - Embedded database (aam.db)
- **Pydantic** - Data validation
- **Uvicorn** - ASGI server

## Deployment

- **Port**: 5000 (bound to 0.0.0.0)
- **Startup**: `npm run dev`
- **Database**: Auto-initializes on startup
- **API Docs**: `/docs` (Swagger), `/redoc`

---

## User Preferences

- **Communication**: Simple, everyday language
- **Development**: Foundational fixes only (no workarounds)
- **Approach**: Iterative, small frequent updates
- **Interaction**: UI or Swagger (`/docs`)
