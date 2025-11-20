# AutonomOS - Multi-Tenant AI Orchestration Platform

**Last Updated:** November 19, 2025

A production-ready **full-stack SaaS platform** for AI-driven data orchestration with real-time monitoring, multi-tenant isolation, and intelligent schema management. Built with React, TypeScript, Python, FastAPI, PostgreSQL, and Redis.

![Platform](https://img.shields.io/badge/Platform-Full--Stack-blue) ![Frontend](https://img.shields.io/badge/Frontend-React%20%2B%20TypeScript-61dafb) ![Backend](https://img.shields.io/badge/Backend-Python%20%2B%20FastAPI-009688) ![Status](https://img.shields.io/badge/Status-Production--Ready-success)

---

## 🎯 Overview

**AutonomOS** is an enterprise-grade platform that combines advanced AI-powered data orchestration with real-time monitoring and self-healing capabilities. The platform consists of three core components:

- 🔍 **AOD (Autonomous Object Discovery)** - Hybrid AI/ML asset cataloging and Shadow IT detection
- 🔄 **AAM (Adaptive API Mesh)** - Self-healing data connectivity with drift detection
- 📊 **DCL (Data Connection Layer)** - AI-driven intelligence, mapping, and graph generation

**Platform Features:**
- 🎨 **Modern Web Interface** - React/TypeScript dashboard with real-time updates
- 🏢 **Multi-Tenant Architecture** - Complete data isolation between organizations
- 🔐 **Enterprise Security** - JWT authentication with Argon2 password hashing
- ⚡ **Real-Time Monitoring** - Live dashboard with auto-refresh and health metrics
- 📡 **Live Flow Telemetry** - Real-time data flow visualization across AOD → AAM → DCL → Agent pipeline

### Key Capabilities

**For Data Engineers:**
- Connect multiple data sources with 4 production-ready connectors (Salesforce, FileSource CSV, Supabase PostgreSQL, MongoDB)
- Canonical event normalization with Pydantic validation
- Automated drift detection and self-healing repair
- Unified data views across heterogeneous sources

**For Platform Teams:**
- Real-time AAM monitoring dashboard
- Connection health tracking
- Sync job history and metrics
- Service health status
- **Live Flow Monitor** - Real-time event streaming dashboard (`/flow-monitor`)
  - Three-column view: AAM → DCL → Agent pipeline
  - WebSocket streaming with <1s latency
  - Click-through event inspection with full metadata
  - Tenant-scoped event filtering

**For Developers:**
- RESTful API with OpenAPI documentation
- Async task orchestration with Python RQ
- WebSocket support for real-time updates
- Complete audit trail and logging

---

## 🏗️ Architecture

### Full-Stack Platform

```
┌─────────────────────────────────────────────────────────────────┐
│                        AUTONOMOS PLATFORM                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              FRONTEND (React + TypeScript)                 │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │ │
│  │  │ AAM Monitor  │  │  DCL Graph   │  │  Ontology View │   │ │
│  │  │  Dashboard   │  │ Visualization│  │   & Mappings   │   │ │
│  │  └──────────────┘  └──────────────┘  └────────────────┘   │ │
│  │  • Vite build system                                       │ │
│  │  • Real-time WebSocket updates                             │ │
│  │  • Responsive design with Quicksand typography             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                               │                                  │
│                               ▼                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              BACKEND (Python + FastAPI)                    │ │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐   │ │
│  │  │    API     │  │    DCL     │  │   AAM Monitor      │   │ │
│  │  │  Endpoints │  │   Engine   │  │    Endpoints       │   │ │
│  │  └────────────┘  └────────────┘  └────────────────────┘   │ │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐   │ │
│  │  │   Worker   │  │   Redis    │  │    PostgreSQL      │   │ │
│  │  │  (RQ Jobs) │  │   Queue    │  │   + DuckDB (DCL)   │   │ │
│  │  └────────────┘  └────────────┘  └────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                               │                                  │
│  ┌────────────────────────────▼──────────────────────────────┐ │
│  │       AAM HYBRID (4 Production Connectors)                │ │
│  │  • Salesforce (OAuth2), FileSource (CSV), Supabase (PG)   │ │
│  │  • MongoDB (NoSQL), Drift Detection, Auto-Repair          │ │
│  │  • Canonical Event Normalization (Accounts, Opps)         │ │
│  │  • Schema Fingerprinting, YAML Mappings, Testing Suite    │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Technology Stack

**Frontend:**
- React 18 + TypeScript
- Vite (build system)
- D3.js (for Sankey diagrams)
- WebSocket (real-time updates)

**Backend:**
- FastAPI (Python web framework)
- SQLAlchemy 2.0 (async ORM)
- Alembic (database migrations)
- Python RQ + Redis (task queue)
- DuckDB (embedded analytics for DCL)
- Pydantic (validation)

**Database & Storage:**
- PostgreSQL (primary database with Alembic migrations)
- Redis (queue + caching)
- DuckDB (DCL data processing)

**AI/ML:**
- Gemini API (Google Generative AI)
- OpenAI API
- RAG with sentence-transformers (multilingual-e5-large)
- Pinecone (vector database for embeddings)

**Deployment:**
- Uvicorn (ASGI server)
- Docker support
- Replit-optimized workflows

---

## 📚 Platform Guide (Architecture Documentation)

**🔗 Access:** First tab "Platform Guide" or `/architecture` route

The interactive Platform Guide is the first tab of the application and provides comprehensive visual documentation:

**Key Sections:**
- 📊 **System Overview** - Production state, validated capabilities, component status
- 📋 **Accountability Matrix** - Clear ownership boundaries (AAM/DCL/AOD) by functional category
- 🔄 **AAM Architecture** - Connection runtime, drift detection, canonical events (4 connectors)
- 🧠 **DCL Architecture** - Intelligence layer, graph generation, agent orchestration
- 🌊 **Data Flow Diagrams** - Mermaid visualizations of system pipelines
- 📡 **Live Telemetry** - Phase 4 flow monitoring architecture
- ⚡ **Performance Metrics** - Validated benchmarks and throughput data
- 🛠️ **Technology Stack** - Complete platform dependencies

**Features:**
- Dark theme with GitHub-style aesthetics
- Interactive Mermaid diagrams
- Quick navigation sidebar
- Mobile-responsive design
- Simplified accountability matrix (3 functional groups: Data Ingestion, Intelligence & Transformation, Orchestration)

---

## ✨ Features

### 1. AAM Monitoring Dashboard (November 2025)

**✅ Real-time visibility into your fully operational Adaptive API Mesh:**

- **Service Health Status** - Monitor all AAM background services (SchemaObserver, RAG Engine, DriftRepairAgent running as integrated tasks)
- **Key Metrics Cards:**
  - Total active connections (4 production connectors)
  - Drift detections (24h)
  - Successful auto-repairs (24h)
  - Manual reviews required
  - Average confidence score
  - Average repair time
- **Connection Health Table** - See all data source connections with status badges
- **Recent Events Log** - Live feed of canonical events, drift detections, and repairs
- **Auto-refresh** - Polls every 10 seconds for latest data
- **Production Data** - Shows real database metrics when AAM services are running

**Current Status:** AAM services running as background tasks in main app. Dashboard shows live data from `canonical_streams`, `drift_events`, and `connections` tables.

**Access:** Click "**AAM Monitor**" in the navigation bar

---

### 2. DCL Graph Visualization

**Interactive data mapping visualization:**

- **Sankey Diagram** - Visual flow from data sources → ontology → unified views
- **Color-Coded Nodes:**
  - 🟢 Green: Data sources (Salesforce, Supabase, MongoDB, FileSource)
  - 🔵 Blue: Ontology entities (accounts, opportunities)
  - 🟣 Purple: Agent actions
- **Smart Label Positioning** - Collision detection prevents overlaps
- **Responsive Design** - Adapts to mobile, tablet, and desktop
- **Real-Time Updates** - WebSocket-driven state changes

**How to Use:**
1. Open the app homepage
2. Click "**Connect Sources**" to trigger DCL mapping
3. Watch the graph populate in real-time

---

### 3. Production-Ready Connector Suite

**4 Connectors with Full Drift Detection:**

**Salesforce:**
- CRM data connector with OAuth2 authentication
- Account, Opportunity, Contact entities
- Full CRUD operations and canonical event emission

**FileSource (CSV/Excel):**
- Local file ingestion with schema detection
- Supports accounts and opportunities from CSV files
- Idempotent uploads and data validation

**Supabase (PostgreSQL):**
- Cloud PostgreSQL connector
- Schema mutation testing endpoints
- Drift detection with SHA-256 fingerprinting
- Auto-repair capabilities with confidence scoring

**MongoDB (NoSQL):**
- Document database connector with BSON handling
- Collections: accounts, opportunities
- Schema drift detection and repair workflow
- Canonical event normalization

---

### 4. Multi-Tenant Architecture

**Complete organizational isolation:**

- Each tenant has dedicated data space
- All tasks, logs, and connections scoped to tenant_id
- JWT-based authentication with 30-minute expiration
- Argon2 password hashing (OWASP recommended)
- Database-level tenant filtering

**Security Model:**
```
User → JWT Token → API Request → Tenant Validation → Data Access
                                     ↓
                            (Only tenant's data visible)
```

---

### 5. Async Task Orchestration

**Background job processing with RQ:**

- **Task Lifecycle:** `queued` → `in_progress` → `success`/`failed`
- **Automatic Retries** - Exponential backoff (10s, 30s, 60s)
- **Timeouts** - Prevent infinite execution
- **Callbacks** - Webhook notifications on completion
- **Task Chaining** - Multi-step workflows
- **Audit Logging** - Full execution trail

**Use Cases:**
- DCL source connections
- AOA orchestration operations
- Slack notifications
- Data sync triggers

---

### 6. Adaptive API Mesh (AAM)

**✅ FULLY OPERATIONAL - Self-healing data connectivity layer with 4 production-ready connectors:**

**Status:** AAM Hybrid orchestration services are running as integrated background tasks within the main FastAPI application. All capabilities are active and processing real data.

**Core Capabilities:**
- **Drift Detection** - SHA-256 schema fingerprinting detects changes across all connectors
- **Auto-Repair** - Autonomous schema updates with confidence scoring (threshold: 85%)
- **Canonical Events** - Unified event stream for Accounts, Opportunities, Contacts, AWS Resources, Cost Reports
- **Background Services** - SchemaObserver, RAG Engine, DriftRepairAgent running continuously
- **Event-Driven Architecture** - Redis Pub/Sub event bus for real-time orchestration

**Production Connectors (All Operational):**
- **Salesforce** - OAuth2 CRM connector with full CRUD and canonical transformation
- **FileSource** - CSV/Excel ingestion with canonical event emission (147 events processed)
- **Supabase** - PostgreSQL cloud connector with schema mutations
- **MongoDB** - NoSQL document connector with BSON handling

**Canonical Transformation Pipeline:**
- ✅ **147 events successfully transformed** (105 opportunities, 15 accounts, 12 contacts, 10 aws_resources, 5 cost_reports)
- ✅ **Zero validation errors** - All mapping files corrected (Salesforce, Dynamics, Pipedrive, Zendesk, Hubspot, FileSource)
- ✅ **Multi-tenant isolation** - tenant_id scoping with string-based identifiers
- ✅ **Production-ready** - No-RAG fast path for <10s processing in Production mode

**Drift Detection Workflow:**
1. SchemaObserver monitors connector schemas via fingerprinting (background task)
2. Drift tickets created in `drift_events` table with confidence scores
3. RAG Engine proposes repairs using vector similarity (Redis Pub/Sub)
4. Auto-repair executes if confidence ≥85%, otherwise requires manual approval
5. Canonical event stream updated with normalized data

**Testing Scripts:**
- `scripts/aam/ingest_seed.py` - Seed Supabase and MongoDB with demo data
- `scripts/aam/drift_supabase.py` - Test Supabase drift detection workflow
- `scripts/aam/drift_mongo.py` - Test MongoDB drift detection workflow

---

## 🚀 Quick Start

### Prerequisites

- **Node.js 18+** (for frontend build)
- **Python 3.11+**
- **PostgreSQL** (Replit built-in or external)
- **Redis** (installed as system dependency)

### Running on Replit (Recommended)

1. **Open Project** - Fork or import into Replit
2. **Install Dependencies** - Auto-installed on first run
3. **Configure Secrets** - Add required API keys:
   - `GEMINI_API_KEY` or `OPENAI_API_KEY` (for LLM features)
   - `PINECONE_API_KEY` (for RAG embeddings)
   - `SLACK_WEBHOOK_URL` (optional, for notifications)
4. **Click Run** - The AutonomOS API workflow starts automatically
5. **Access Web Interface** - Opens in Replit webview at port 5000

The platform will be available at: `https://<your-repl>.replit.dev`

### Local Development

```bash
# 1. Clone repository
git clone <your-repo-url>
cd autonomos

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set up environment variables
cp .env.example .env
# Edit .env with your credentials

# 4. Start PostgreSQL and Redis
# (Ensure both are running locally)

# 5. Run database migrations (automatic on startup)
# Migrations run automatically via start.sh
# Or manually: alembic upgrade head

# 6. Start backend server
./start.sh
# Or manually:
# python -m app.worker &  # Start RQ worker
# uvicorn app.main:app --host 0.0.0.0 --port 5000

# 7. Access the app
open http://localhost:5000
```

---

## 📂 Project Structure

```
/
├── app/                          # Backend application
│   ├── main.py                   # FastAPI app entry point
│   ├── worker.py                 # RQ worker for async tasks
│   ├── models.py                 # SQLAlchemy database models
│   ├── schemas.py                # Pydantic request/response schemas
│   ├── crud.py                   # Database operations
│   ├── database.py               # DB session management
│   ├── config.py                 # Configuration settings
│   └── api/
│       └── v1/
│           ├── auth.py           # Authentication endpoints
│           ├── tasks.py          # Task management
│           ├── aoa.py            # AOA orchestration
│           ├── aam_monitoring.py # AAM dashboard API
│           └── dcl.py            # DCL engine endpoints
├── alembic/                      # Database migrations
│   ├── versions/                 # Migration scripts
│   │   └── 5a9d6371e18c_*.py    # Baseline migration
│   ├── env.py                    # Alembic environment config
│   └── script.py.mako            # Migration template
├── dcl/                          # Data Connection Layer
│   ├── engine.py                 # Main DCL orchestration
│   ├── llm_service.py            # LLM abstraction layer
│   ├── rag_engine.py             # RAG embeddings & retrieval
│   └── mock_data.py              # Sample data sources
├── frontend/                     # React/TypeScript UI
│   ├── src/
│   │   ├── components/
│   │   │   ├── AAMDashboard.tsx  # AAM monitoring UI
│   │   │   ├── DCLGraph.tsx      # Sankey visualization
│   │   │   ├── TopBar.tsx        # Navigation
│   │   │   └── FAQ.tsx           # Help section
│   │   ├── App.tsx               # Main app component
│   │   └── main.tsx              # Entry point
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── static/                       # Compiled frontend assets
│   ├── index.html
│   ├── assets/                   # Built JS/CSS
│   └── *.png                     # Images
├── aam-hybrid/                   # AAM microservices
│   ├── services/
│   │   ├── orchestrator/
│   │   ├── auth_broker/
│   │   ├── drift_repair_agent/
│   │   ├── schema_observer/
│   │   └── rag_engine/
│   ├── shared/
│   │   ├── airbyte_client.py
│   │   ├── database.py
│   │   ├── models.py
│   │   └── config.py
│   └── README.md                 # AAM-specific docs
├── scripts/                      # Utility scripts
│   └── stamp_baseline.sh         # Production migration baseline
├── alembic.ini                   # Alembic configuration
├── requirements.txt              # Python dependencies
├── start.sh                      # Startup script (auto-runs migrations)
├── replit.md                     # Project memory/notes
└── README.md                     # This file
```

---

## 🎨 Using the Web Interface

### Homepage

**Hero Section:**
- Overview of AutonomOS capabilities
- "Connect Sources" button to trigger DCL mapping

**Agent Layer:**
- Visual representation of AI agents (Schema Mapper, Drift Detector, etc.)

**DCL Graph:**
- Interactive Sankey diagram showing data flows
- Real-time updates via WebSocket

**Architecture Flow:**
- System diagram with directional arrows
- Responsive layout for mobile/desktop

**FAQ Section:**
- Common questions about features and technology

### AAM Monitor Dashboard

**Navigation:**
1. Click "**AAM Monitor**" in the top navigation bar
2. Dashboard loads with four sections:

**Service Health Panel:**
- Shows status of all AAM microservices
- Green (running) or Red (stopped) indicators
- Note: Services integrated as background tasks show "stopped" (expected)

**Metrics Cards:**
- Total connections, drift detections, repairs, reviews
- Average confidence score and repair time
- Auto-refreshes every 10 seconds

**Connection Health Table:**
| Connection Name | Source Type | Status | Created At |
|----------------|-------------|--------|------------|
| Salesforce Production | Salesforce | 🟢 ACTIVE | Oct 16, 2025 |

**Recent Events Log:**
- Live feed of sync jobs, drift detections, repairs
- Timestamps and event details
- Scrollable list of recent activity

---

## 🗄️ Database Migrations

**Production-ready schema versioning with Alembic:**

AutonomOS uses **Alembic** for database migrations, providing safe, trackable schema changes with zero downtime.

### Key Features

- **Automatic migrations on startup** - Every server start runs `alembic upgrade head`
- **Multi-Base architecture** - Tracks both `app.models` and `aam_hybrid.shared.models` in one migration history
- **Baseline migration** - Safe production deployment with existing data (no DROP TABLE warnings)
- **Version controlled** - All migrations committed to git with code changes

### Creating New Migrations

When you change models in `app/models.py` or `aam_hybrid/shared/models.py`:

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Add user preferences table"

# Review the generated migration in alembic/versions/
# Test locally, then commit to git
```

### Managing Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Rollback last migration
alembic downgrade -1

# Check current migration version
alembic current

# View migration history
alembic history
```

### First-Time Production Setup

**IMPORTANT:** Before deploying Alembic to an existing production database:

```bash
# Run ONCE to align migration history with existing schema
./scripts/stamp_baseline.sh
```

This marks the current production schema as baseline, preventing destructive DROP TABLE operations.

### Migration Workflow

1. **Development:**
   - Modify SQLAlchemy models
   - Run `alembic revision --autogenerate -m "description"`
   - Review generated migration
   - Test locally with `alembic upgrade head`

2. **Staging:**
   - Commit migration to git
   - Deploy to staging
   - Migrations auto-run on startup via `start.sh`

3. **Production:**
   - First deploy: Run `./scripts/stamp_baseline.sh`
   - Subsequent deploys: Migrations auto-apply on startup

### Notes

- **Never manually edit production schema** - Always use Alembic migrations
- **Test migrations locally first** - Use development database before production
- **Migrations are atomic** - Each migration runs in a transaction
- **Multi-tenant safe** - All migrations respect tenant isolation

---

## 📋 RACI Matrix - Component Responsibilities

**Critical Finding:** Clear separation of responsibilities between AAM (Adaptive API Mesh) and DCL (Data Connection Layer) is essential for architectural integrity.

### Component Responsibility Matrix (RACI)

| Capability | AOD | AAM | DCL | Notes |
|------------|-----|-----|-----|-------|
| **Discovery & Cataloging** |||||
| Asset discovery (find data sources) | **A/R** | C | I | AOD owns discovery |
| Schema introspection | I | **A/R** | C | AAM owns runtime schema scanning |
| Source catalog management | **A/R** | I | C | AOD owns catalog |
| **Connection Runtime** |||||
| API authentication/OAuth | I | **A/R** | I | AAM owns credential management |
| Data fetching/sync | I | **A/R** | I | AAM owns data retrieval |
| Pagination handling | I | **A/R** | I | AAM owns API pagination |
| Rate limiting/throttling | I | **A/R** | I | AAM owns API limits |
| Connection health monitoring | C | **A/R** | I | AAM owns monitoring |
| **Intelligence & Mapping** |||||
| LLM-powered mapping proposals | - | I | **A/R** | DCL owns LLM decisions |
| RAG mapping lookup | - | I | **A/R** | DCL owns RAG system |
| Mapping registry storage | - | C | **A/R** | DCL owns registry database |
| Mapping approval workflow | - | I | **A/R** | DCL owns approvals |
| Confidence scoring | - | I | **A/R** | DCL owns scoring logic |
| **Transformation** |||||
| Canonical transformation | - | R | **A** | DCL decides, AAM executes |
| Schema drift detection | - | **A/R** | C | AAM detects and owns |
| Drift repair proposals | - | I | **A/R** | DCL owns repair logic |
| **Graph & Ontology** |||||
| Ontology management | - | - | **A/R** | DCL fully owns |
| Graph generation | - | I | **A/R** | DCL owns graph building |
| Entity resolution | - | I | **A/R** | DCL owns resolution |
| **Agent Orchestration** |||||
| Agent execution | - | - | **A/R** | DCL owns execution |
| Agent context management | - | - | **A/R** | DCL owns context |
| Multi-agent coordination | - | - | **A/R** | DCL owns coordination |

**RACI Legend:**
- **A** = Accountable (single owner, ultimately answerable)
- **R** = Responsible (does the work, can be multiple)
- **C** = Consulted (provides input, two-way communication)
- **I** = Informed (kept updated, one-way communication)

**Key Rule:** Each capability has exactly ONE Accountable owner (marked as A or A/R when same component is both)

### Orchestration Boundaries (DCL vs AOA)

**DCL Scope:**
- Owns agent context/data and low-level actions within data domain
- Entity mapping, graph generation, single-agent execution
- Data transformation decisions and confidence scoring

**AOA/xAO Scope (Out of Document Scope):**
- Higher-level workflow orchestration
- Cross-domain playbooks (e.g., data + compute + network)
- Multi-agent coordination across different domains
- Business process automation spanning multiple systems

---

## 🔌 API Documentation

### Interactive Docs

Once the server is running, visit:
- **Swagger UI**: `http://localhost:5000/docs`
- **ReDoc**: `http://localhost:5000/redoc`

### Core API Endpoints

#### Authentication

**Register New User**
```bash
POST /api/v1/auth/register
Content-Type: application/json

{
  "name": "Acme Corp",
  "email": "alice@acmecorp.com",
  "password": "SecurePass123!"
}
```

**Login**
```bash
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "alice@acmecorp.com",
  "password": "SecurePass123!"
}

Response:
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Get Current User**
```bash
GET /api/v1/auth/me
Authorization: Bearer <token>
```

#### DCL Operations

**Get DCL State**
```bash
GET /dcl/state
Authorization: Bearer <token>

Response:
{
  "sources_connected": true,
  "agents": [...],
  "source_schemas": {...},
  "rag_mappings": [...],
  "dev_mode": false
}
```

**Connect Data Sources (Async)**
```bash
POST /dcl/connect
Authorization: Bearer <token>

Returns: Task object (status: "queued")
```

**Reset DCL State**
```bash
POST /dcl/reset
Authorization: Bearer <token>

Returns: Task object (status: "queued")
```

**WebSocket Updates**
```javascript
const ws = new WebSocket('wss://your-domain.com/dcl/ws');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('DCL Event:', data.type, data);
};
```

#### AAM Monitoring

**Get Metrics**
```bash
GET /api/v1/aam/metrics
Authorization: Bearer <token>

Response:
{
  "total_connections": 8,
  "active_drift_detections_24h": 3,
  "successful_repairs_24h": 12,
  "manual_reviews_required_24h": 1,
  "average_confidence_score": 0.94,
  "average_repair_time_seconds": 45.2,
  "timestamp": "2025-10-31T12:00:00Z",
  "data_source": "database"
}
```

**Get Connections**
```bash
GET /api/v1/aam/connections
Authorization: Bearer <token>

Response:
{
  "connections": [
    {
      "id": "uuid",
      "name": "Salesforce Production",
      "source_type": "Salesforce",
      "status": "ACTIVE",
      "created_at": "2025-10-16T12:00:00Z",
      "updated_at": "2025-10-31T12:00:00Z"
    }
  ],
  "total": 1,
  "data_source": "database"
}
```

**Get Recent Events**
```bash
GET /api/v1/aam/events?limit=50
Authorization: Bearer <token>

Response:
{
  "events": [
    {
      "id": "uuid",
      "connection_id": "uuid",
      "connection_name": "Salesforce Production",
      "event_type": "sync_succeeded",
      "timestamp": "2025-10-31T10:00:00Z",
      "metadata": {...}
    }
  ],
  "total": 50,
  "data_source": "database"
}
```

**Service Health**
```bash
GET /api/v1/aam/health
Authorization: Bearer <token>

Response:
{
  "services": [
    {"name": "Orchestrator", "port": 8001, "status": "running"},
    {"name": "Auth Broker", "port": 8002, "status": "running"},
    {"name": "Drift Repair Agent", "port": 8003, "status": "running"},
    {"name": "Schema Observer", "port": 8004, "status": "stopped"},
    {"name": "RAG Engine", "port": 8005, "status": "stopped"}
  ]
}
```

#### Task Management

**Create Task**
```bash
POST /api/v1/tasks
Authorization: Bearer <token>
Content-Type: application/json

{
  "payload": {
    "action": "post_to_slack",
    "channel": "#general",
    "message": "Hello from AutonomOS!"
  },
  "max_retries": 3,
  "timeout_seconds": 300,
  "callback_url": "https://example.com/webhook"
}

Response: Task object with status "queued"
```

**Get Task Status**
```bash
GET /api/v1/tasks/{task_id}
Authorization: Bearer <token>
```

**Cancel Task**
```bash
DELETE /api/v1/tasks/{task_id}
Authorization: Bearer <token>
```

#### AOA Orchestration

**Get AOA State (Sync)**
```bash
GET /api/v1/aoa/state
Authorization: Bearer <token>
```

**Run AOA Connection (Async)**
```bash
POST /api/v1/aoa/run
Authorization: Bearer <token>

Returns: Task object
```

**Reset AOA (Async)**
```bash
POST /api/v1/aoa/reset
Authorization: Bearer <token>

Returns: Task object
```

**Toggle Production Mode**
```bash
POST /api/v1/aoa/prod-mode
Authorization: Bearer <token>
Content-Type: application/json

{
  "enabled": true
}

Returns: Task object
```

#### Health Checks

**API Health**
```bash
GET /health/api
Response: {"status": "ok"}
```

**Worker Health**
```bash
GET /health/worker
Response: {"status": "ok", "redis": "connected"}
```

---

## 🔧 Configuration

### Environment Variables

**Required:**
- `DATABASE_URL` - PostgreSQL connection string (auto-set on Replit)
- `REDIS_URL` - Redis connection string (auto-set on Replit)
- `SECRET_KEY` - JWT signing secret (auto-generated)

**LLM Providers (at least one required for DCL AI features):**
- `GEMINI_API_KEY` - Google Gemini API key
- `OPENAI_API_KEY` - OpenAI API key

**RAG Features:**
- `PINECONE_API_KEY` - Pinecone vector database
- `PINECONE_ENVIRONMENT` - Pinecone environment (e.g., "us-west1-gcp")
- `PINECONE_INDEX` - Index name (default: "schema-mappings-e5")

**Optional:**
- `SLACK_WEBHOOK_URL` - Slack incoming webhook for notifications
- `LEGACY_DCL_BASE_URL` - Legacy DCL backend (if using AOA proxy)
- `ALLOWED_WEB_ORIGIN` - CORS origin for external frontends
- `JWT_EXPIRE_MINUTES` - Token expiration (default: 30)

**AAM/Airbyte (for AAM Hybrid features):**
- `AIRBYTE_API_URL` - Airbyte API endpoint
- `AIRBYTE_CLIENT_ID` - OAuth client ID
- `AIRBYTE_CLIENT_SECRET` - OAuth client secret
- `AIRBYTE_WORKSPACE_ID` - Airbyte workspace ID
- `AIRBYTE_DESTINATION_ID` - Target destination ID
- `SALESFORCE_CLIENT_ID` - Salesforce OAuth client ID
- `SALESFORCE_CLIENT_SECRET` - Salesforce OAuth secret
- `SALESFORCE_REFRESH_TOKEN` - Salesforce refresh token

### Adding Secrets on Replit

1. Click the lock icon (🔒) in the sidebar
2. Click "**+ New Secret**"
3. Enter key and value
4. Click "**Add Secret**"
5. Restart the workflow

---

## 📊 Database Schema

### Core Tables

**tenants**
- `id` (UUID, PK)
- `name` (String, unique)
- `created_at` (DateTime)

**users**
- `id` (UUID, PK)
- `tenant_id` (UUID, FK → tenants)
- `email` (String, unique)
- `hashed_password` (String, Argon2)
- `created_at` (DateTime)

**tasks**
- `id` (UUID, PK)
- `tenant_id` (UUID, FK → tenants)
- `status` (Enum: queued/in_progress/success/failed/canceled)
- `payload` (JSON)
- `result` (JSON)
- `callback_url` (String, nullable)
- `retry_count` (Integer)
- `max_retries` (Integer)
- `on_success_next_task` (JSON, nullable)
- `next_task_id` (UUID, nullable)
- `created_at`, `updated_at` (DateTime)

**task_logs**
- `id` (UUID, PK)
- `task_id` (UUID, FK → tasks)
- `tenant_id` (UUID, FK → tenants)
- `timestamp` (DateTime)
- `message` (String)

### AAM Tables

**connections**
- `id` (UUID, PK)
- `name` (String)
- `source_type` (String)
- `airbyte_source_id` (UUID, nullable)
- `airbyte_connection_id` (UUID, nullable)
- `status` (Enum: PENDING/ACTIVE/FAILED/HEALING/INACTIVE)
- `created_at`, `updated_at` (DateTime)

**sync_catalog_versions**
- `id` (UUID, PK)
- `connection_id` (UUID, FK → connections)
- `sync_catalog` (JSONB)
- `version_number` (Integer)
- `created_at` (DateTime)

**job_history**
- `id` (UUID, PK)
- `connection_id` (UUID, FK → connections)
- `airbyte_job_id` (String, nullable)
- `status` (Enum: pending/running/succeeded/failed/cancelled)
- `started_at`, `completed_at` (DateTime)
- `error_message` (Text, nullable)

---

## 🧪 Testing

### Manual Testing

**Test DCL Connection:**
1. Open homepage
2. Click "**Connect Sources**"
3. Watch Sankey graph populate
4. Check browser console for WebSocket events

**Test AAM Dashboard:**
1. Click "**AAM Monitor**" in nav bar
2. Verify metrics cards display
3. Check connection health table
4. Observe auto-refresh (10s intervals)

**Test API:**
```bash
# Health check
curl http://localhost:5000/health/api

# Get DCL state (requires auth)
export TOKEN="<your-jwt-token>"
curl http://localhost:5000/dcl/state -H "Authorization: Bearer $TOKEN"
```

### Automated Testing

**Run Python Tests:**
```bash
pytest tests/ -v
```

**Frontend Tests:**
```bash
cd frontend
npm test
```

---

## 🚢 Deployment

> **📖 IMPORTANT:** Before deploying, read the [Deployment Policy](./DEPLOYMENT_POLICY.md) for database migration safety guidelines and pre-publish checks.

### Replit Deployment (Recommended)

1. Click "**Deploy**" in Replit
2. Configure deployment settings:
   - **Deployment Type**: Autoscale (for web apps)
   - **Build Command**: `npm run build` (if needed)
   - **Run Command**: `bash start.sh`
3. Set production environment variables
4. Click "**Deploy**" to publish

Your app will be available at: `https://<your-repl>.replit.app`

### Docker Deployment

**Build Image:**
```bash
docker build -t autonomos:latest .
```

**Run Container:**
```bash
docker run -d \
  -p 5000:5000 \
  -e DATABASE_URL="postgresql://..." \
  -e REDIS_URL="redis://..." \
  -e GEMINI_API_KEY="..." \
  autonomos:latest
```

**Docker Compose:**
```bash
docker-compose up -d
```

---

## 📚 Documentation

- **AAM Hybrid Guide**: See `aam-hybrid/README.md`
- **AAM Full Context**: See `aam-hybrid/AAM_FULL_CONTEXT.md`
- **AAM Dashboard Guide**: See `AAM_DASHBOARD_GUIDE.md`
- **Airbyte Setup**: See `aam-hybrid/AIRBYTE_SETUP.md`
- **Project Notes**: See `replit.md`

---

## 🤝 Contributing

We welcome contributions! Please follow these guidelines:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### Code Standards

- **Python**: Follow PEP 8, use type hints
- **TypeScript**: Use strict mode, avoid `any`
- **Commits**: Use conventional commit messages
- **Tests**: Add tests for new features

---

## 📝 License

This project is licensed under the **MIT License** - see LICENSE file for details.

---

## 🙏 Acknowledgments

- **Airbyte** - Open-source data integration platform
- **FastAPI** - Modern Python web framework
- **React** - UI library
- **D3.js** - Data visualization
- **Pinecone** - Vector database
- **Google Gemini** - AI language model
- **Replit** - Cloud development platform

---

## 📞 Support

**Issues:** [GitHub Issues](https://github.com/your-org/autonomos/issues)  
**Discussions:** [GitHub Discussions](https://github.com/your-org/autonomos/discussions)  
**Email:** support@autonomos.dev  

---

## 🗺️ Roadmap

For a comprehensive, module-by-module roadmap, visit the **Platform Guide** at `/architecture.html`.

### Production Ready Modules
- ✅ **AOD (Autonomous Object Discovery)** - Asset cataloging, Shadow IT detection, HITL triage
- ✅ **AAM (Adaptive API Mesh)** - 4 production connectors, drift detection, self-healing
- ✅ **DCL (Data Connection Layer)** - Enterprise ontology, AI mapping, knowledge graphs
- ✅ **Live Flow Monitoring** - Real-time telemetry across AAM → DCL → Agents pipeline

### In Development Modules
- 🔨 **AOA (Agentic Orchestration Architecture)** - Multi-step workflow engine, cross-domain playbooks
- 🔨 **Agents** - Pre-built AI agent library (FinOps, RevOps), HITL approval workflows
- 🔨 **NLP / Intent (Control Center)** - Production RAG knowledge base, real-time data integration

### Planned Priorities
- [ ] Scale AAM to several dozen connectors for enterprise scalability
- [ ] Enhanced graph visualization and query language for DCL
- [ ] Visual workflow designer for AOA
- [ ] Agent marketplace and custom agent builder
- [ ] SOC 2 Type II compliance certification
- [ ] Role-based access control (RBAC)

**Note:** Roadmap items are prioritized based on customer feedback and platform needs. We use an agile, priority-based approach rather than fixed timelines.

---

**Built with ❤️ by the AutonomOS Team**

*Empowering organizations with intelligent, self-healing data orchestration*
