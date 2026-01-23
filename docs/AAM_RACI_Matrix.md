# AAM Engine - RACI Matrix

## Component: AAM (Adaptive API Mesh)

**Last Verified:** January 23, 2026

## System Architecture Context

| Component | Responsibility |
|-----------|---------------|
| **AOD** | Autonomous Operations Director - emits connection intent as ConnectionCandidates to AAM. |
| **AAM** | Inventories reusable data pipes, infers minimal semantics, publishes DeclaredPipes for DCL consumption. Does NOT move data. |
| **DCL** | Ingests schemas and data from routed pipes, performs semantic mapping to unified ontology. |

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

## RACI Matrix

| Activity/Process | AAM | AOD | DCL |
|-----------------|-----|-----|-----|
| **Candidate Management** |
| Emit Connection Intent | C | A | I |
| Receive ConnectionCandidate | A | R | I |
| Triage Candidates | A | I | I |
| Match Candidate to Pipe | A | I | C |
| Defer Candidate | A | I | I |
| **Collector Operations** |
| Register Collectors | A | I | I |
| Run Collectors | A | I | I |
| Track Collector Runs | A | I | I |
| Generate Observations | A | I | I |
| **Pipe Inference** |
| Infer Fabric Plane | A | I | I |
| Infer Modality | A | I | I |
| Infer Transport Kind | A | I | I |
| Infer Entity Scope | A | I | I |
| Infer Identity Keys | A | I | I |
| Infer Change Semantics | A | I | I |
| Create DeclaredPipe | A | I | C |
| **Pipe Registry** |
| Store Declared Pipes | A | I | I |
| Version Pipe Changes | A | I | I |
| Compute Schema Hash | A | I | I |
| Serve Pipe Queries | A | I | C |
| **Drift Detection** |
| Detect Schema Drift | A | I | C |
| Detect Freshness Drift | A | I | C |
| Detect Contract Drift | A | I | C |
| Acknowledge Drift | A | I | I |
| Suppress Drift | A | I | I |
| **Tee Request Management** |
| Create Tee Request | A | I | I |
| Track Tee Status | A | I | I |
| Approve/Reject Tee | A | C | I |
| **DCL Integration** |
| Export Declared Pipes | A | I | R |
| Route Pipes to DCL | A | I | R |
| Provision Connector Info | A | I | R |
| **Operator UI** |
| Display Pipe Inventory | A | I | I |
| Display Drift Events | A | I | I |
| Display Candidates | A | I | I |
| Load Enterprise Presets | A | I | I |

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
- AOD emits ConnectionCandidates representing discovery intent
- AAM attaches to existing enterprise integration fabric via collectors
- AAM infers minimal semantics from observations (transport, entities, freshness)
- DeclaredPipes are the ONLY product AAM outputs
- DCL consumes DeclaredPipes for semantic unification
- Operators use UI to triage candidates, acknowledge drift, manage tee requests
- "Weak signals become labels, not blockers" - trust labels don't gate pipes
