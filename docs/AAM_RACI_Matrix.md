# AAM Engine - RACI Matrix

## Component: AAM (Adaptive API Mesh)

**Last Verified:** January 23, 2026

## Global Architecture Pivot

> **Self-Healing Mesh + Zero-Trust Vision**

| Component | Role | Boundary |
|-----------|------|----------|
| **AAM** | The Mesh | Owns Self-Healing and Repair (ACTIVE, not passive) |
| **Farm** | The Verifier | Strictly a Test Oracle (no ops) |
| **DCL** | The Brain | Metadata-Only (no raw data buffering) |
| **AOA** | The Orchestrator | Owns Execution and Infrastructure |

## Fabric Plane Architecture

> **AAM connects to Fabric Planes, NOT individual SaaS apps**

| Fabric Plane | Adapter | Modality | Example Vendors |
|--------------|---------|----------|-----------------|
| **IPAAS** | IPaaSAdapter | Webhooks/Signals | Workato, MuleSoft, Boomi |
| **API_GATEWAY** | GatewayAdapter | Proxy/REST | Kong, Apigee, AWS API GW |
| **EVENT_BUS** | EventBusAdapter | Streaming Consumer | Kafka, EventBridge, Pulsar |
| **DATA_WAREHOUSE** | WarehouseAdapter | JDBC/Bulk Read | Snowflake, BigQuery, Redshift |

**CRITICAL CONSTRAINT:** AAM connects to Fabric Planes, NOT individual apps (Salesforce, HubSpot). Fabric plane inference uses evidence leads from AOD, vendor identity, endpoint signals, and display name hints.

## System Architecture Context

| Component | Responsibility |
|-----------|---------------|
| **AAM** | Self-Healing Mesh. Connects to Fabric Planes (not apps). Owns repair operations. |
| **Farm** | Test Oracle. Provides synthetic data and verification. Does NOT handle ops. |

## Feature Status Summary

| Feature | Status | Notes |
|---------|--------|-------|
| FabricAdapter Interface | FUNCTIONAL | Polymorphic base class |
| IPaaSAdapter | FUNCTIONAL | Workato, MuleSoft, Boomi |
| GatewayAdapter | FUNCTIONAL | Kong, Apigee |
| EventBusAdapter | FUNCTIONAL | Kafka, EventBridge |
| WarehouseAdapter | FUNCTIONAL | Snowflake, BigQuery |
| Fabric Plane Inference | FUNCTIONAL | Evidence-based inference cascade |
| FabricDriftDetector | FUNCTIONAL | Connectivity drift detection |
| Self-Healing Repair | FUNCTIONAL | AAM-owned, not Farm |
| Governance Policies | FUNCTIONAL | Plane-level enforcement |
| DeclaredPipe Inference | FUNCTIONAL | Converts observations to pipes |
| Schema Drift Detection | FUNCTIONAL | Data structure changes |
| Operator UI | FUNCTIONAL | 4 screens |

## RACI Matrix

| Activity/Process | AAM | Farm |
|-----------------|-----|------|
| **Fabric Plane Management** |
| Connect to IPAAS | R/A | I |
| Connect to API_GATEWAY | R/A | I |
| Connect to EVENT_BUS | R/A | I |
| Connect to DATA_WAREHOUSE | R/A | I |
| Infer Fabric Plane for Candidates | R/A | I |
| Enforce Routing Policies | R/A | I |
| **Adapter Operations** |
| Register Adapters | R/A | I |
| Discover Pipes from Plane | R/A | I |
| Check Plane Health | R/A | I |
| **Self-Healing (AAM Owns)** |
| Detect Connection Drift | R/A | I |
| Detect Consumer Lag | R/A | I |
| Detect Warehouse Suspended | R/A | I |
| Execute Self-Heal | R/A | I |
| Log Heal History | R/A | I |
| **Governance** |
| Apply PII Redaction Policy | R/A | I |
| Enforce Rate Limits | R/A | I |
| Validate Routing Decisions | R/A | I |
| Block Direct App Access | R/A | I |
| **Pipe Inference** |
| Infer Fabric Plane | R/A | I |
| Infer Modality | R/A | I |
| Create DeclaredPipe | R/A | I |
| **Verification (Farm = Oracle)** |
| Provide Source of Truth | C | R/A |
| Verify Against Truth | R | A |
| Generate Test Data | I | R/A |

## Legend
- **R** = Responsible (does the work)
- **A** = Accountable (final authority/approval)
- **C** = Consulted (provides input)
- **I** = Informed (kept updated)

## Drift Types

### Schema Drift (existing)
- Data structure changes in pipes
- Field additions/removals
- Type changes

### Fabric Drift (NEW - AAM owns)
| Drift Type | Plane | Severity | Self-Heal Action |
|------------|-------|----------|------------------|
| connection_lost | All | CRITICAL | Reconnect |
| consumer_lag | EVENT_BUS | HIGH | Restart consumer |
| warehouse_suspended | DATA_WAREHOUSE | HIGH | Wake warehouse |
| latency_spike | All | MEDIUM | Monitor/alert |
| auth_expired | All | HIGH | Refresh credentials |
| webhook_failed | IPAAS | MEDIUM | Re-register |
| rate_limited | API_GATEWAY | MEDIUM | Back off/retry |

## Architectural Boundaries

### AAM Owns (Self-Healing Mesh)
- Fabric Plane adapters (NOT app connectors)
- Fabric plane inference and routing
- Connectivity drift detection AND repair
- Governance policy enforcement at Plane level

### Farm Owns (Test Oracle Only)
- Source of truth data
- Verification responses
- Test data generation
- Does NOT handle ops or infrastructure

### AAM Does NOT Own
- Individual SaaS app connectors (deleted)
- Infrastructure provisioning (delegated to AOA)
- Runtime operations (delegated to AOA)
- Direct app connections (connects to Planes only)

## What AAM Does NOT Do

| Activity | Reason |
|----------|--------|
| Connect to SaaS apps directly | Connects to PLANES that manage them |
| Build app connectors | Builds PLANE ADAPTERS instead |
| Move Data | We observe, not orchestrate |
| Transform Data | Not an ETL/ELT tool |
| Handle Infrastructure | Delegated to AOA |

## Notes
- AAM connects to Fabric Planes, NOT individual applications
- AAM owns self-healing of Plane connections - Farm is NOT involved
- FabricDriftDetector handles connectivity issues; SchemaHash handles data drift
- Fabric plane inference uses evidence leads, vendor identity, and endpoint signals
- Governance policies are applied at the Plane level (not app level)
