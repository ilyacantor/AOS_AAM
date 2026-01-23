# AAM Engine - RACI Matrix

## Component: AAM (Adaptive API Mesh)

**Last Verified:** January 23, 2026

## Global Architecture Pivot

> **Self-Healing Mesh + Zero-Trust Vision**

| Component | New Role | Boundary |
|-----------|----------|----------|
| **AAM** | The Mesh | Owns Self-Healing and Repair |
| **Farm** | The Verifier | Strictly a Test Oracle |
| **DCL** | The Brain | Metadata-Only (no raw data buffering) |
| **AOA** | The Orchestrator | Owns Execution and Infrastructure |

## System Architecture Context

| Component | Responsibility |
|-----------|---------------|
| **AAM** | The Self-Healing Mesh. Inventories pipes, infers semantics, AND owns repair operations. Active, not passive. |
| **Farm** | The Test Oracle. Provides synthetic data and source of truth for verification. Does NOT handle ops. |

## Core Philosophy

> "We do not change how data moves. We make its behavior and meaning explicit. We self-heal when things drift."

## Feature Status Summary

| Feature | Status | Notes |
|---------|--------|-------|
| Candidate Intake API | FUNCTIONAL | POST/GET/PATCH candidates |
| Candidate Match/Defer | FUNCTIONAL | Link to pipe or defer with reason |
| Mock Collector | FUNCTIONAL | Generates test observations |
| Collector Run Tracking | FUNCTIONAL | Run history with timestamps |
| DeclaredPipe Inference | FUNCTIONAL | Converts observations to pipes |
| Fabric Plane Inference | FUNCTIONAL | IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE |
| Modality Inference | FUNCTIONAL | CONTROL_PLANE, DECLARED_INTERFACE, etc. |
| Schema Hash Detection | FUNCTIONAL | Tracks schema changes |
| Drift Detection | FUNCTIONAL | Schema, freshness, contract drift |
| Drift Ack/Suppress | FUNCTIONAL | Operator workflow |
| Self-Healing Repair | PLANNED | AAM now owns this |
| Tee Request Management | FUNCTIONAL | Create/track tee artifacts |
| Pipe Versioning | FUNCTIONAL | Version history per pipe |
| DCL Export | FUNCTIONAL | Export declared pipes JSON |
| Enterprise Presets | FUNCTIONAL | 4 maturity patterns |
| Operator UI | FUNCTIONAL | 4 screens (Pipes, Detail, Candidates, Drift) |

## RACI Matrix

| Activity/Process | AAM | Farm |
|-----------------|-----|------|
| **Candidate Management** |
| Receive ConnectionCandidate | R/A | I |
| Triage Candidates | R/A | I |
| Match Candidate to Pipe | R/A | I |
| Defer Candidate | R/A | I |
| **Collector Operations** |
| Register Collectors | R/A | I |
| Run Collectors | R/A | I |
| Track Collector Runs | R/A | I |
| Generate Observations | R/A | I |
| **Pipe Inference** |
| Infer Fabric Plane | R/A | I |
| Infer Modality | R/A | I |
| Infer Transport Kind | R/A | I |
| Infer Entity Scope | R/A | I |
| Infer Identity Keys | R/A | I |
| Infer Change Semantics | R/A | I |
| Create DeclaredPipe | R/A | I |
| **Pipe Registry** |
| Store Declared Pipes | R/A | I |
| Version Pipe Changes | R/A | I |
| Compute Schema Hash | R/A | I |
| Serve Pipe Queries | R/A | I |
| **Drift Detection** |
| Detect Schema Drift | R/A | C |
| Detect Freshness Drift | R/A | C |
| Detect Contract Drift | R/A | C |
| Acknowledge Drift | R/A | I |
| Suppress Drift | R/A | I |
| **Self-Healing (NEW - AAM Owns)** |
| Identify Repair Candidates | R/A | C |
| Execute Repair Action | R/A | I |
| Validate Repair Success | R | A |
| Log Repair History | R/A | I |
| **Tee Request Management** |
| Create Tee Request | R/A | I |
| Track Tee Status | R/A | I |
| Approve/Reject Tee | R/A | I |
| **Verification (Farm = Oracle)** |
| Provide Source of Truth | C | R/A |
| Verify Against Truth | R | A |
| Generate Test Data | I | R/A |
| **Operator UI** |
| Display Pipe Inventory | R/A | I |
| Display Drift Events | R/A | I |
| Display Candidates | R/A | I |
| Load Enterprise Presets | R/A | I |

## Legend
- **R** = Responsible (does the work)
- **A** = Accountable (final authority/approval)
- **C** = Consulted (provides input)
- **I** = Informed (kept updated)

## Architectural Boundaries

### AAM Owns (Self-Healing Mesh)
- Pipe inventory and inference
- Drift detection AND repair
- Self-healing operations
- Active mesh management

### Farm Owns (Test Oracle Only)
- Source of truth data
- Verification responses
- Test data generation
- Does NOT handle ops or infrastructure

### AAM Does NOT Own (Delegated to AOA)
- Infrastructure provisioning
- Execution orchestration
- Runtime operations

## Key Integration Points

| Integration | AAM Role | Partner | Partner Role | Status |
|-------------|----------|---------|--------------|--------|
| Farm Source of Truth | Consumer | Farm | Provider | PLANNED |
| Farm Verification | Consumer | Farm | Oracle | PLANNED |
| Self-Healing Repair | Owner | - | - | PLANNED |
| Mock Collector | Internal | - | - | FUNCTIONAL |

## Fabric Plane Distribution

| Fabric Plane | Description | Example Vendors |
|--------------|-------------|-----------------|
| IPAAS | Integration platform control plane | Workato, MuleSoft, Boomi, Tray.io |
| API_GATEWAY | Direct API access | Kong, Apigee, custom APIs |
| EVENT_BUS | Event streaming backbone | Kafka, EventBridge, Pulsar |
| DATA_WAREHOUSE | Warehouse as source of truth | Snowflake, BigQuery, Redshift |

## Enterprise Preset Patterns

| Preset | Pipes | Pattern | Typical Org |
|--------|-------|---------|-------------|
| Early/Scrappy | 6 | Point-to-point APIs | Startup, <50 employees |
| iPaaS-Centric | 8 | Workato/MuleSoft control plane | Mid-market, IT-led |
| Platform-Oriented | 9 | Kafka/EventBridge backbone | Enterprise, platform team |
| Warehouse-Centric | 11 | Snowflake as truth | Analytics-first org |

## What AAM Does NOT Do

| Activity | Reason |
|----------|--------|
| Move Data | We observe, not orchestrate |
| Transform Data | Not an ETL/ELT tool |
| Act as iPaaS | We inventory iPaaS, not replace it |
| Act as Kafka | We observe streams, not run them |
| Build SaaS Connectors | We catalog existing fabric |
| Provision Infrastructure | Delegated to AOA |
| Store Secrets | Access info contains NO credentials |
| Handle Ops | Delegated to AOA (formerly Farm's burden) |

## Notes
- AAM is now ACTIVE, not passive - owns self-healing and repair
- Farm is strictly a Test Oracle - no ops responsibilities
- DCL receives metadata only from AAM (zero-trust, no raw data)
- AOA owns execution and infrastructure (picked up from Farm)
- DeclaredPipes are the ONLY product AAM outputs
- "Weak signals become labels, not blockers" - trust labels don't gate pipes
