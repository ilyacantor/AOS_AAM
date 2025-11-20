# AutonomOS - Multi-Tenant AI Orchestration Platform

**Last Updated:** November 20, 2025

**Recent Architecture Changes:**
- **Backend Event Loop Blocking Fix (Nov 20, 2025)**: Fixed Gateway middleware (Audit + Idempotency) that were making synchronous blocking calls in async context, causing complete server freeze. Implemented thread pool execution for DB/Redis operations. Audit and Idempotency middleware temporarily disabled until further testing.
- Platform Guide converted from static HTML to React component for deployment compatibility
- ArchitecturePage.tsx removed in favor of PlatformGuidePage.tsx (bundled with frontend)
- Flow Monitor moved from standalone tab to AAM (Connect) subtab
- Navigation structure: Platform Guide → AOD → Discovery Demo → AAM (with Connector Details + Flow Monitor) → DCL → AOA → Control Center → Help
- Database connection pool reduced (pool_size: 10→2, max_overflow: 20→3) to prevent Supabase Session mode MaxClients errors
- Platform Guide "What Makes Us Different" section updated to emphasize complexity abstraction and end-to-end platform approach
- **End-to-End Pipeline Demo**: New admin endpoints to toggle AAM production connectors and demonstrate full AOD→AAM→DCL→Agent flow with real data
- **Discovery Demo (Stage-Driven)**: Interactive `/demo-discovery` page with stage-driven UI showing pipeline graph and stage-specific detail panels. Each of 4 stages (AOD, AAM, DCL, Agent) displays different complexity with reactive graph animations. Features auto-progression, manual navigation, and enterprise console aesthetic

## Overview
AutonomOS is a production-ready, multi-tenant SaaS platform for AI-driven data orchestration. The platform is organized into three architectural layers:

**Operational Infrastructure (Production Ready):**
- **AOD (Autonomous Object Discovery)** - External microservice for hybrid AI/ML asset discovery, Shadow IT detection, and NLP-based cataloging. Features HITL triage workflows and enterprise auto-connect to AAM.
- **AAM (Adaptive API Mesh)** - Transport layer providing self-healing data connectivity with 4 production connectors (Salesforce, MongoDB, FileSource, Supabase). Handles authentication, data fetching, schema drift detection, and canonical event normalization.
- **DCL (Data Connection Layer)** - Intelligence layer for AI-driven entity mapping, graph generation, LLM-powered proposals, drift auto-repair, and agent execution context.

**Platform Services (In Development):**
- **AOA (Agentic Orchestration Architecture)** - High-level workflow orchestration engine with task queue management, AOD integration, and multi-tenant job enforcement. Working toward cross-domain playbooks and business process automation.
- **NLP / Intent (Control Center)** - Natural language interface with persona classification (CTO, CRO, COO, CFO) and query routing. Working toward production RAG knowledge base and real-time data integration.

**Tailored Applications (In Development):**
- **Pre-Built Agents** - Domain-specific AI agent library (FinOps, RevOps) with execution framework, context management, and metadata support. Working toward agent marketplace and multi-agent coordination.

The platform ensures complete data isolation with JWT authentication and user management, offering secure, scalable, and enterprise-grade orchestration. Data flows through the system as: AOD (discover) → AAM (connect) → DCL (intelligence) → Agents (action).

## User Preferences

**🚨 MOST CRITICAL PREFERENCE - READ THIS FIRST:**
**FOUNDATIONAL/FUNDAMENTAL FIXES ONLY** - When facing issues or bugs, ALWAYS choose fundamental/root-cause fixes over workarounds. No band-aids, no quick patches, no shortcuts. Fix the underlying architecture, data model, or type system properly. User explicitly demands "option 2, fundamental fix required always".

**Communication & Development:**
- Clear, concise explanations and direct answers
- Iterative development with frequent, small updates
- Ask for approval before major architectural changes or significant feature additions
- Detailed explanations for complex concepts, brevity for straightforward ones
- Do not make changes to folder `Z` and file `Y`

**CRITICAL: Task Planning Guidelines**
- NEVER reference duration/time estimates in task descriptions or plans
- NEVER organize plans around time-based phases (Week 1, Week 2, etc.)
- Organize by logical phases, dependencies, and priorities only
- Use priority levels (P0/Critical, High, Medium, Low) instead of timelines

## System Architecture
AutonomOS is a full-stack SaaS platform built around a multi-tenant architecture with UUID-based `tenant_id` scoping and JWT authentication for data isolation.

**UI/UX Decisions:**
The frontend uses React 18 and TypeScript with a responsive design, Quicksand typography, a Green, Blue, Purple color scheme, and dark mode. It features pages for platform guide, data discovery (AOD), API mesh connections with connector details and flow monitor (AAM), ontology graph visualization (DCL), agentic orchestration (AOA), and control center. Live status indicators (green pulsing dots) distinguish real backend data from mock data, managed via a centralized registry. Page titles follow "AOS [Feature]" branding. Enterprise reporting views include a tabular lineage grid, hierarchical tree view, and an evaluation dashboard. Flow Monitor is accessible as a subtab within AAM (Connect) for monitoring real-time telemetry across the data pipeline.

**Technical Implementations:**
*   **Task Orchestration:** Asynchronous job processing using Python RQ and Redis Queue.
*   **Authentication & Security:** JWT-based authentication with Argon2 hashing.
*   **AOA (Agentic Orchestration Architecture):** High-level orchestration for DCL engine operations.
*   **End-to-End Pipeline Demo:** Admin API (`/api/v1/admin/feature-flags/*`) for toggling AAM production connectors vs legacy file sources. Demo API (`/api/v1/demo/pipeline/*`) simulates full AOD→AAM→DCL→Agent flow with real production connectors (Salesforce, MongoDB, FileSource, Supabase).
*   **DCL Engine (Data Connection Layer):** AI-driven, in-process engine for data orchestration, utilizing DuckDB for materialized views and Redis for concurrent access. Supports multiple connectors, AI-powered entity mapping, graph generation, and idempotent operations. LLM Telemetry tracks cumulative LLM calls and token usage via Redis. Includes intelligence services for LLM proposals, RAG lookup, confidence scoring, drift repair, and mapping approval.
*   **Adaptive API Mesh (AAM):** Provides self-healing data connectivity with production connectors (Salesforce, FileSource, Supabase, MongoDB). Features canonical event normalization (Pydantic), schema fingerprinting for drift detection, LLM-powered auto-repair, RAG intelligence, and an auto-onboarding system with Safe Mode. Integrates with DCL via Redis Streams. Includes Airbyte Sync Monitoring.
*   **NLP Gateway Service:** Dedicated natural-language processing service for persona-based routing with context-specific prompts. Includes a persona summary endpoint, tenant-scoped RAG knowledge base (Postgres + pgvector), hybrid retrieval, JWT auth, and PII redaction.
*   **Event Streaming System:** Real-time event delivery via Server-Sent Events (SSE) and WebSockets, using Redis Pub/Sub.
*   **API Endpoints:** Organized by domain with OpenAPI/Swagger documentation.
*   **Data Quality Intelligence Layer:** Implements canonical event processing, schema drift detection (fingerprinting with Redis), LLM/RAG-powered auto-repair, and a Human-in-the-Loop (HITL) workflow.
*   **Resilience Infrastructure:** Async circuit breaker, retry, timeout, and bulkhead decorators for intelligence services.
*   **Live Flow Telemetry (Phase 4):** Real-time data flow monitoring dashboard with Redis Streams infrastructure. Three separate streams (aam:flow, dcl:flow, agent:flow) track entity lifecycle events across AAM → DCL → Agent pipeline. Features include: FlowEventPublisher for event publishing, REST snapshot API (GET /api/v1/flow-monitor), WebSocket live streaming (/ws/flow-monitor), React dashboard at /flow-monitor with three-column layout, tenant-scoped event filtering, and demo endpoint for integration testing. Each layer publishes its own events maintaining RACI boundaries. Telemetry failures never break business logic (try/except wrappers).

**System Design Choices:**
The platform uses a "Strangler Fig" pattern with feature flags for zero downtime, structuring data flow as: Data Sources → AAM → DCL → Agents. A single Supabase PostgreSQL database is used for development and production, managed with Alembic for schema versioning. Deployment safety infrastructure prevents destructive database operations.
*   **Database Connection Architecture:** Centralized session factories ensure PgBouncer compatibility for Supabase. Connection pool sizes optimized for Supabase Session mode (pool_size=2, max_overflow=3) to prevent MaxClientsInSessionMode errors.
*   **Production Database Override:** Prioritizes `SUPABASE_DATABASE_URL` over Replit's auto-provisioned `DATABASE_URL`.
*   **AAM Production Connections:** Four operational AAM connectors (Salesforce, FileSource, MongoDB, Supabase) use real credentials from Replit Secrets.
*   **Redis Infrastructure:** All Redis connections (sync, async, RQ worker) use TLS encryption with full certificate validation. Shared Redis client prevents connection pool exhaustion. Includes graceful degradation and monitoring with watchdog processes and retry logic.
*   **Feature Flags:** Frontend (`VITE_CONNECTIONS_V2`) and backend (`USE_AAM_AS_SOURCE`, `USE_DCL_INTELLIGENCE_API`) feature flags managed via `.env.local` and Redis, respectively. The `USE_AAM_AS_SOURCE` flag is Redis-backed with multi-worker support, async pub/sub broadcasting, and persistence.
*   **Data Ingestion:** Script for populating `mapping_registry` from CSV files.
*   **DCL Graph Structure:** Simplified graph with a consolidated "from AAM" parent node and source names on entity node labels.

## External Dependencies
*   **FastAPI:** Web framework.
*   **uvicorn:** ASGI server.
*   **SQLAlchemy:** ORM.
*   **Alembic:** Database migration tool.
*   **psycopg2-binary, psycopg-binary:** PostgreSQL adapters.
*   **redis:** Python client for Redis.
*   **rq (Redis Queue):** Background job processing.
*   **pydantic:** Data validation.
*   **python-dotenv:** Environment variable management.
*   **httpx:** HTTP client.
*   **duckdb:** Embedded SQL database.
*   **pandas:** Data manipulation.
*   **pyyaml:** YAML parsing.
*   **google-generativeai:** Gemini AI integration.
*   **openai:** OpenAI API integration.
*   **Supabase PostgreSQL:** Primary database service.
*   **Upstash Redis:** External Redis for production.
*   **Slack Incoming Webhooks:** For notifications.
*   **AOS Discover (AOD):** External microservice for asset discovery.
*   **pgvector:** PostgreSQL extension for vector embeddings.