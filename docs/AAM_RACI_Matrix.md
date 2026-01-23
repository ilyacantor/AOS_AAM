# AAM Engine - RACI Matrix

## Component: AAM (Adaptive API Mesh)

**Last Verified:** January 23, 2026

## System Architecture Context

| Component | Responsibility |
|-----------|---------------|
| **AAM** | Inventories reusable data pipes, infers minimal semantics, publishes DeclaredPipes. Does NOT move data. |
| **Farm** | Provides synthetic data streams and source of truth for verification and testing. |

## Core Philosophy

> "We do not change how data moves. We make its behavior and meaning explicit."

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
| Tee Request Management | FUNCTIONAL | Create/track tee artifacts |
| Pipe Versioning | FUNCTIONAL | Version history per pipe |
| DCL Export | FUNCTIONAL | Export declared pipes JSON |
| Enterprise Presets | FUNCTIONAL | 4 maturity patterns |
| Operator UI | FUNCTIONAL | 4 screens (Pipes, Detail, Candidates, Drift) |

## RACI Matrix

| Activity/Process | AAM | Farm |
|-----------------|-----|------|
| **Candidate Management** |
| Receive ConnectionCandidate | A | I |
| Triage Candidates | A | I |
| Match Candidate to Pipe | A | I |
| Defer Candidate | A | I |
| **Collector Operations** |
| Register Collectors | A | I |
| Run Collectors | A | C |
| Track Collector Runs | A | I |
| Generate Observations | A | C |
| **Pipe Inference** |
| Infer Fabric Plane | A | I |
| Infer Modality | A | I |
| Infer Transport Kind | A | I |
| Infer Entity Scope | A | I |
| Infer Identity Keys | A | I |
| Infer Change Semantics | A | I |
| Create DeclaredPipe | A | I |
| **Pipe Registry** |
| Store Declared Pipes | A | I |
| Version Pipe Changes | A | I |
| Compute Schema Hash | A | I |
| Serve Pipe Queries | A | I |
| **Drift Detection** |
| Detect Schema Drift | A | C |
| Detect Freshness Drift | A | C |
| Detect Contract Drift | A | C |
| Acknowledge Drift | A | I |
| Suppress Drift | A | I |
| **Tee Request Management** |
| Create Tee Request | A | I |
| Track Tee Status | A | I |
| Approve/Reject Tee | A | I |
| **Verification** |
| Provide Source of Truth | C | A |
| Verify Against Truth | R | A |
| Generate Test Data | I | A |
| **Operator UI** |
| Display Pipe Inventory | A | I |
| Display Drift Events | A | I |
| Display Candidates | A | I |
| Load Enterprise Presets | A | I |

## Legend
- **R** = Responsible (does the work)
- **A** = Accountable (final authority/approval)
- **C** = Consulted (provides input)
- **I** = Informed (kept updated)

## Key Integration Points

| Integration | AAM Role | Partner | Partner Role | Status |
|-------------|----------|---------|--------------|--------|
| Farm Source of Truth | Consumer | Farm | Provider | PLANNED |
| Farm Test Data | Consumer | Farm | Provider | PLANNED |
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
| Provision Infrastructure | We document what exists |
| Store Secrets | Access info contains NO credentials |

## Notes
- AAM attaches to existing enterprise integration fabric via collectors
- AAM infers minimal semantics from observations (transport, entities, freshness)
- DeclaredPipes are the ONLY product AAM outputs
- Farm provides source of truth for verification and test data generation
- Operators use UI to triage candidates, acknowledge drift, manage tee requests
- "Weak signals become labels, not blockers" - trust labels don't gate pipes
