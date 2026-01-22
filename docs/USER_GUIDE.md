# AAM Operator User Guide

## What is AAM?

**AAM (Adaptive API Mesh)** is the integration layer that inventories your enterprise's reusable data pipes and makes their behavior and meaning explicit. Think of it as a catalog of all the ways data can flow between your systems.

### The Big Picture

AAM sits between two other systems:

```
AOD (discovers what exists) → AAM (catalogs the pipes) → DCL (unifies meaning)
```

- **AOD** discovers what systems and connections exist in your enterprise and sends "connection candidates" to AAM
- **AAM** (this system) catalogs those connections as "declared pipes" with metadata about how they behave
- **DCL** consumes those declared pipes to build a unified understanding of your data

### What AAM Does NOT Do

AAM does not move data, transform data, or act as an integration platform. It only **observes** and **documents** what already exists.

---

## The Three Operator Jobs

As an operator, AAM supports exactly three jobs:

1. **See what pipes exist** - View the inventory of data pipes with their metadata and trust state
2. **See what's wrong** - Identify drift, health issues, and coverage gaps with evidence
3. **Take bounded actions** - Run collectors, acknowledge drift, tag ownership, export to DCL

Nothing more, nothing less. AAM deliberately avoids "magic" actions like "fix automatically" or "connect now."

---

## The Four Screens

### 1. Pipes Inventory (`/ui/pipes`)

This is your main dashboard showing all discovered data pipes.

#### What You See

| Element | What It Means |
|---------|---------------|
| **Pipe Name** | Human-readable name for this data pipe (clickable to view details) |
| **Source System** | Where the data comes from (e.g., "Salesforce", "Workday") |
| **Modality** | How this pipe connects: `CONTROL_PLANE`, `DECLARED_INTERFACE`, `PASSIVE_SUBSCRIPTION`, or `MINIMAL_TEE` |
| **Transport** | How data moves: `API`, `EVENT_STREAM`, `TABLE`, `FILE`, or `WEBHOOK` |
| **Change Semantics** | How updates work: `SNAPSHOT`, `APPEND_ONLY`, `CDC_UPSERT`, or `UNKNOWN` |
| **Trust Labels** | Quality signals like data freshness, schema stability, ownership clarity |

#### Actions You Can Take

| Button | What It Does |
|--------|--------------|
| **Run Collector** | Triggers a collector to observe systems and update pipe information |
| **Run Inference** | Processes raw observations into declared pipes |
| **Export to DCL** | Generates a snapshot of all pipes in DCL format |

#### The Collector Runs Section

Below the pipe table, you'll see recent collector runs. This shows:
- When each collector ran
- How many observations it captured
- Whether it succeeded or failed

---

### 2. Pipe Detail (`/ui/pipes/{id}`)

Clicking on a pipe name takes you to its detail view with complete information.

#### Sections

**Identity & Classification**
| Field | What It Means |
|-------|---------------|
| **Pipe ID** | Unique identifier (UUID format) |
| **Display Name** | Human-readable name |
| **Source System** | The system this pipe connects to |
| **Modality** | Connection approach (see above) |
| **Transport Kind** | How data moves (see above) |

**Data Characteristics**
| Field | What It Means |
|-------|---------------|
| **Entity Scope** | What types of data this pipe covers (e.g., "Account", "Contact") |
| **Identity Keys** | Fields that uniquely identify records (e.g., "id", "account_id") |
| **Change Semantics** | How updates are communicated |
| **Freshness** | How current the data is (e.g., "near-realtime", "daily") |

**Provenance**
| Field | What It Means |
|-------|---------------|
| **Discovery Source** | How this pipe was discovered (e.g., "mock_collector") |
| **Discovered At** | When this pipe was first seen |
| **Lineage Hint** | Upstream/downstream relationships if known |

**Trust & Ownership**
| Field | What It Means |
|-------|---------------|
| **Trust Labels** | Quality signals (e.g., "SCHEMA_STABLE", "OWNER_KNOWN") |
| **Owner Signals** | Who owns or maintains this pipe |

**Technical Reference**
| Field | What It Means |
|-------|---------------|
| **Endpoint Ref** | Technical details for connecting (opaque to operators) |
| **Schema Info** | Schema hash and version information |
| **Access Info** | Access method details (never contains secrets) |

#### Version History

Shows how this pipe's definition has changed over time. Each version has:
- Version number
- When it was created
- Schema hash (for detecting changes)

#### Drift Events

Lists any drift events for this specific pipe (see Drift & Health section).

---

### 3. Candidates (`/ui/candidates`)

Shows connection candidates from AOD that haven't been fully processed yet.

#### What You See

| Column | What It Means |
|--------|---------------|
| **Asset Key** | Unique identifier from AOD |
| **Vendor** | The vendor/provider (e.g., "Salesforce", "Workday") |
| **Display Name** | Human-readable name |
| **Category** | Type of system: `CRM`, `ERP`, `HRIS`, `iPaaS` |
| **Status** | Current state in the workflow (see below) |
| **Matched Pipe** | If matched, shows which pipe this became |

#### Candidate Statuses

| Status | What It Means |
|--------|---------------|
| **New** | Just arrived from AOD, not yet reviewed |
| **Triaged** | Reviewed but not yet connected to a pipe |
| **Connected** | Successfully matched to a declared pipe |
| **Deferred** | Intentionally set aside (with a reason) |

#### Actions You Can Take

| Button | What It Does |
|--------|--------------|
| **Match to Pipe** | Links this candidate to an existing pipe (requires pipe ID) |
| **Defer** | Sets the candidate aside with a reason |

#### When to Use Each Action

- **Match to Pipe**: When you recognize this candidate refers to a pipe that already exists in the inventory
- **Defer**: When the candidate isn't actionable right now (e.g., "Waiting for vendor API access", "Duplicate entry")

---

### 4. Drift & Health (`/ui/drift`)

Shows issues that need attention - places where reality has diverged from expectations.

#### What You See

| Column | What It Means |
|--------|---------------|
| **Pipe** | Which pipe has the drift (clickable) |
| **Drift Type** | What changed: `SCHEMA`, `FRESHNESS`, or `CONTRACT` |
| **Severity** | How serious: `critical`, `high`, `medium`, or `low` |
| **Description** | What specifically changed |
| **Status** | Current state: `open`, `acknowledged`, or `suppressed` |
| **Detected** | When the drift was first noticed |

#### Drift Types

| Type | What It Means |
|------|---------------|
| **SCHEMA** | The structure of the data changed (fields added/removed/modified) |
| **FRESHNESS** | Data stopped updating at the expected rate |
| **CONTRACT** | The agreed behavior of the pipe changed |

#### Severity Levels

| Level | What It Means | Typical Response |
|-------|---------------|------------------|
| **Critical** | Major breaking change affecting downstream systems | Immediate action required |
| **High** | Significant change that may cause issues | Review within 24 hours |
| **Medium** | Notable change worth tracking | Review within a week |
| **Low** | Minor change, informational | Review when convenient |

#### Drift Statuses

| Status | What It Means |
|--------|---------------|
| **Open** | Needs attention - not yet reviewed |
| **Acknowledged** | Reviewed and noted - someone is aware |
| **Suppressed** | Intentionally hidden (not a real issue, or expected) |

#### Actions You Can Take

| Button | What It Does |
|--------|--------------|
| **Acknowledge** | Marks the drift as "I've seen this and noted it" |
| **Suppress** | Hides the drift (for false positives or expected changes) |

---

## The API Screen (`/docs`)

The API screen shows the complete Swagger documentation for all AAM endpoints. This is useful for:
- Developers integrating with AAM
- Debugging issues
- Understanding what's possible programmatically

The API is organized into sections:
- **Candidates** - Endpoints for managing connection candidates
- **Collectors** - Endpoints for running collectors
- **Pipes** - Endpoints for viewing declared pipes
- **Drift** - Endpoints for managing drift events
- **TEE Requests** - Endpoints for minimal TEE artifacts
- **Export** - Endpoints for DCL export

---

## Common Workflows

### Workflow 1: Processing New Candidates

1. Go to **Candidates** screen
2. Review candidates with "New" status
3. For each candidate:
   - If it matches an existing pipe → Click **Match to Pipe** and enter the pipe ID
   - If it's not actionable → Click **Defer** and enter a reason
   - If it needs collector observation → Move to workflow 2

### Workflow 2: Discovering New Pipes

1. Go to **Pipes** screen
2. Click **Run Collector** to observe systems
3. Wait for the collector to complete (watch the Collector Runs section)
4. Click **Run Inference** to process observations into pipes
5. Review newly created pipes in the table

### Workflow 3: Investigating Drift

1. Go to **Drift & Health** screen
2. Review items with "Open" status
3. Click on the pipe name to see full details
4. Investigate the change:
   - If it's expected → Click **Suppress**
   - If it's real but understood → Click **Acknowledge**
   - If it needs action → Handle it outside AAM, then acknowledge

### Workflow 4: Exporting to DCL

1. Go to **Pipes** screen
2. Review that all pipes look correct
3. Click **Export to DCL**
4. The JSON response contains all declared pipes in DCL format

---

## Understanding Trust Labels

Trust labels are weak signals that help you understand the reliability of a pipe. They don't block anything - they're informational.

| Label | What It Means |
|-------|---------------|
| **SCHEMA_STABLE** | Schema hasn't changed recently |
| **OWNER_KNOWN** | Someone is responsible for this pipe |
| **FRESHNESS_OK** | Data is updating at expected intervals |
| **ACCESS_VERIFIED** | Connection has been tested recently |

Missing labels aren't failures - they just mean we don't have evidence yet.

---

## Glossary

| Term | Definition |
|------|------------|
| **Candidate** | A potential connection discovered by AOD that AAM might catalog |
| **Collector** | A component that observes enterprise systems and creates observations |
| **Declared Pipe** | A cataloged data connection with full metadata |
| **DCL** | Data Catalog Layer - consumes pipes from AAM to unify meaning |
| **Drift** | When reality diverges from what was previously observed |
| **Modality** | The approach for connecting (control plane, declared interface, etc.) |
| **Observation** | Raw data from a collector before being processed into a pipe |
| **Pipe** | A reusable data connection between systems |
| **Provenance** | Origin and lineage information about a pipe |
| **Schema Hash** | A fingerprint of the data structure for detecting changes |
| **TEE** | Trusted Execution Environment - minimal secure processing |
| **Transport** | How data physically moves (API, events, files, etc.) |

---

## Getting Help

- **API Documentation**: Visit `/docs` for complete endpoint documentation
- **Sample Data**: Check `/api/aam/collectors` to see available collectors
- **Health Check**: Visit `/health` to verify the system is running

