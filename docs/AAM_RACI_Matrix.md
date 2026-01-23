# AAM Engine - RACI Matrix

## Component: AAM (Adaptive API Mesh)

**Last Verified:** January 23, 2026

## System Architecture Context

| Component | Responsibility |
|-----------|---------------|
| **AOD** | Autonomous Operations Director - emits connection intent as ConnectionCandidates to AAM. |
| **AAM** | Inventories reusable data pipes, infers minimal semantics, publishes DeclaredPipes for DCL consumption. Does NOT move data. |
| **DCL** | Ingests schemas and data from routed pipes, performs semantic mapping to unified ontology. |
| **Farm** | Provides synthetic data streams and source of truth for verification. |

## Core Philosophy

> "We do not change how data moves. We make its behavior and meaning explicit."

**Data Flow:**
```
AOD emits intent → AAM declares pipes → DCL unifies meaning
```

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
| Real Collectors | PLANNED | Salesforce API inventory next |
| Freshness Drift | PLANNED | Time-based staleness detection |

## RACI Matrix

| Activity/Process | AAM | AOD | DCL | Database |
|-----------------|-----|-----|-----|----------|
| **Candidate Management** |
| Emit Connection Intent | C | R/A | I | I |
| Receive ConnectionCandidate | R/A | C | I | C |
| Triage Candidates | R/A | I | I | C |
| Match Candidate to Pipe | R/A | I | C | C |
| Defer Candidate | R/A | I | I | C |
| **Collector Operations** |
| Register Collectors | R/A | I | I | C |
| Run Collectors | R/A | I | I | C |
| Track Collector Runs | R/A | I | I | C |
| Generate Observations | R/A | I | I | C |
| **Pipe Inference** |
| Infer Fabric Plane | R/A | I | I | I |
| Infer Modality | R/A | I | I | I |
| Infer Transport Kind | R/A | I | I | I |
| Infer Entity Scope | R/A | I | I | I |
| Infer Identity Keys | R/A | I | I | I |
| Infer Change Semantics | R/A | I | I | I |
| Create DeclaredPipe | R/A | I | C | C |
| **Pipe Registry** |
| Store Declared Pipes | R/A | I | I | A |
| Version Pipe Changes | R/A | I | I | C |
| Compute Schema Hash | R/A | I | I | I |
| Serve Pipe Queries | R/A | I | C | C |
| **Drift Detection** |
| Detect Schema Drift | R/A | I | C | C |
| Detect Freshness Drift | R/A | I | C | C |
| Detect Contract Drift | R/A | I | C | C |
| Acknowledge Drift | R/A | I | I | C |
| Suppress Drift | R/A | I | I | C |
| **Tee Request Management** |
| Create Tee Request | R/A | I | I | C |
| Track Tee Status | R/A | I | I | C |
| Approve/Reject Tee | R/A | C | I | C |
| **DCL Integration** |
| Export Declared Pipes | R/A | I | C | C |
| Route Pipes to DCL | R/A | I | C | I |
| Provision Connector Info | R/A | I | C | C |
| **Operator UI** |
| Display Pipe Inventory | R/A | I | I | C |
| Display Drift Events | R/A | I | I | C |
| Display Candidates | R/A | I | I | C |
| Load Enterprise Presets | R/A | I | I | C |

## Legend
- **R** = Responsible (does the work)
- **A** = Accountable (final authority/approval)
- **C** = Consulted (provides input)
- **I** = Informed (kept updated)

## Key Integration Points

| Integration | AAM Role | Partner | Partner Role | Status |
|-------------|----------|---------|--------------|--------|
| ConnectionCandidate Intake | Consumer | AOD | Provider | FUNCTIONAL |
| DeclaredPipe Export | Provider | DCL | Consumer | FUNCTIONAL |
| Connector Provisioning | Provider | DCL | Consumer | FUNCTIONAL |
| Pipe Routing | Provider | DCL | Consumer | FUNCTIONAL |
| Mock Collector | Internal | - | - | FUNCTIONAL |
| Salesforce Collector | Consumer | Salesforce | Provider | PLANNED |
| iPaaS Collector | Consumer | Workato/MuleSoft | Provider | PLANNED |
| SQLite Storage | Consumer | - | Provider | FUNCTIONAL |

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

## Verified Metrics (Sample Data)

| Metric | Value |
|--------|-------|
| Pipes Declared | 6-11 (varies by preset) |
| Candidates Tracked | 2-3 per preset |
| Collectors Registered | 1 (mock) |
| Observations Generated | Per collector run |
| Drift Events | Schema changes tracked |
| Fabric Planes | 4 types |
| Modalities | 4 types |

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
- AOD emits ConnectionCandidates representing discovery intent
- AAM attaches to existing enterprise integration fabric via collectors
- AAM infers minimal semantics from observations (transport, entities, freshness)
- DeclaredPipes are the ONLY product AAM outputs
- DCL consumes DeclaredPipes for semantic unification
- Operators use UI to triage candidates, acknowledge drift, manage tee requests
- "Weak signals become labels, not blockers" - trust labels don't gate pipes
