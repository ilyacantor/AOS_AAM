# AOD Fabric Plane Classification Blueprint

## Evidence-Based Pipe Discovery & Fabric Plane Assignment

**Status:** Architectural Redesign Proposal  
**Scope:** AOD Discovery Pipeline, Farm Test Oracle  
**Date:** February 2026

---

## 1. Problem Statement

### Current Approach: Category-Based Inference

AOD currently assigns assets to fabric planes using a static routing table:

| Asset Category | Inferred Plane | Reasoning |
|---|---|---|
| CRM, ERP, Finance, HCM, HRIS, ITSM, Marketing, Sales | iPaaS (MuleSoft) | "Business apps need complex workflow orchestration" |
| API, Gateway, REST, GraphQL | API Gateway (Kong) | "API-first services route through API management" |
| Data, Analytics, BI, Warehouse, Reporting | Data Warehouse (Snowflake) | "Analytics assets route through the data plane" |
| Messaging, Stream, Events, Kafka | Event Bus (Kafka) | "Real-time streaming goes through event infrastructure" |

The two-stage process detects fabric plane "motherships" first, then infers that downstream assets route through planes based on their category, with a default fallback to iPaaS. Confidence is set to a flat 0.70.

### Why This Is Wrong ~50% of the Time

**The fundamental error:** This approach assumes asset *type* determines *how* it connects. In reality, the same asset can connect through multiple planes simultaneously, and the routing path depends on the enterprise's specific architecture — not the asset's category.

Real-world examples that break category-based inference:

- **Salesforce (CRM)** → Routed to iPaaS by the current table. But in practice, a single Salesforce instance may have a Workato recipe syncing Opportunities (iPaaS pipe), a Kong-fronted REST API for real-time queries (API Gateway pipe), a Kafka CDC stream of Contact changes (Event Bus pipe), AND a Snowflake landing table with nightly extracts (Data Warehouse pipe). That's four pipes across four planes for one asset.

- **Tableau (BI)** → Routed to Data Warehouse. But Tableau might connect directly to Salesforce's API through Kong, or pull from a Kafka stream in real-time mode. The category "BI" tells you nothing about the integration path.

- **"Unknown App" with no category** → Defaults to iPaaS. This is a coin flip at best.

**The category table confuses two distinct questions:**
1. "What kind of asset is this?" (CRM, BI, etc.) — this is asset classification
2. "How does data flow to/from this asset?" — this is fabric plane assignment

These are independent dimensions. A CRM can route through any plane. A BI tool can route through any plane. The asset's category is not evidence of its routing.

---

## 2. Architectural Principle: Evidence-Based Classification

### Core Rule

**A pipe's fabric plane is determined by the evidence of how AOD discovered or observed the connection — never by inferring from asset type.**

Three categories of evidence, in descending order of reliability:

| Evidence Tier | Source | Confidence | Description |
|---|---|---|---|
| **Tier 1: Direct** | Fabric plane catalog crawl | 0.95 | AOD connected to the plane's management API and found the pipe listed there |
| **Tier 2: Observed** | Observation plane signals (Network, Cloud, IdP, CMDB, Finance) | 0.70–0.90 | AOD found evidence in observation data that a connection routes through a specific plane |
| **Tier 3: Inferred** | Heuristic reasoning | 0.30–0.50 | AOD has no direct evidence but can make an educated guess (current approach, downgraded) |

The current system operates entirely at Tier 3 and assigns 0.70 confidence — which overstates certainty. The redesign prioritizes Tier 1 and Tier 2 evidence and only falls back to Tier 3 when nothing better is available, with appropriately low confidence.

---

## 3. Discovery Sequence (Three Phases)

### Phase 1: Observation Plane Harvest

**What:** Extract fabric plane signals from AOD's existing 7 observation planes during the standard discovery scan.

**When:** During the existing AOD scan pipeline (the 7-stage process). No new scan is needed — this enriches what AOD already collects.

**Key principle:** AOD already collects the data. The change is adding fabric-aware analysis to existing observation plane outputs.

#### 3.1 Cloud Plane (☁️) — Fabric Infrastructure Discovery

**What it reveals:** The fabric planes themselves as cloud resources.

AOD's cloud scan already inventories AWS/Azure/GCP resources. Many fabric plane components are discoverable as cloud resources:

| Cloud Resource Type | Indicates Fabric Plane | Signal Strength |
|---|---|---|
| AWS API Gateway (REST/HTTP API) | API Gateway plane | Very High — the plane itself |
| Amazon MSK cluster | Event Bus plane | Very High — managed Kafka |
| AWS EventBridge bus | Event Bus plane | Very High |
| ECS/EKS service running Kong | API Gateway plane | High — container metadata reveals the image |
| Lambda + API Gateway integration | API Gateway plane | High — routing linkage in config |
| Snowflake account / Redshift cluster | Data Warehouse plane | Very High |
| EC2 running MuleSoft Mule Runtime | iPaaS plane | High — identifiable via AMI or process |
| Fivetran / Airbyte agents | iPaaS / Data Warehouse plane | High — ELT pipeline components |

**Additionally:** Cloud resource metadata reveals *connections between* resources:
- Security groups / VPC peering → which services can talk to which plane infrastructure
- IAM roles with cross-service permissions → which assets are authorized to use which plane
- API Gateway route tables → literally a list of upstream services (i.e., pipes)

**AOD action:** During cloud resource enumeration, tag any resource matching known fabric plane vendors/patterns as `fabric_plane_candidate`. Extract connection metadata (routes, security groups, IAM bindings) as `fabric_routing_evidence`.

#### 3.2 Network Plane (🌐) — Traffic-Based Fabric Detection

**What it reveals:** Actual traffic patterns showing which assets communicate through which planes.

This is the most direct evidence of fabric belonging because it observes what's actually happening, regardless of what anyone configured or documented.

| Network Signal | Indicates | Confidence |
|---|---|---|
| Traffic from `app-x` → `kong-proxy.internal:8443` | App routes through API Gateway | 0.90 |
| DNS resolution for `hooks.workato.com` by `marketing-tool` | Asset connects via iPaaS | 0.85 |
| TCP connections to `kafka-broker-1:9092` from `service-y` | Service uses Event Bus | 0.90 |
| HTTPS to `account.snowflakecomputing.com` from `etl-job` | ETL routes through Data Warehouse | 0.85 |
| Traffic to `hooks.zapier.com` from unknown source | Shadow iPaaS plane detected | 0.80 |

**The challenge:** Volume. 10,387 network records include health checks, CDN traffic, SaaS UI access, and countless non-integration connections. AOD needs heuristics to filter:

- **Include:** Traffic to known fabric plane endpoints (Kong, Workato, Kafka, Snowflake hostnames/IPs), sustained/recurring patterns (not one-off), high data volume connections, connections using integration-specific ports (9092 for Kafka, 8443 for Kong admin)
- **Exclude:** Browser-based SaaS access (short sessions, low volume), health check / monitoring pings, CDN and static asset traffic

**AOD action:** Cross-reference network flow records against known fabric plane infrastructure (identified in Cloud scan and from vendor hostname patterns). For each match, create a `fabric_routing_evidence` record linking the source asset to the detected plane.

#### 3.3 CMDB Plane (📋) — Declared Relationships

**What it reveals:** Explicitly documented integration relationships and asset classifications.

CMDB data quality varies wildly across organizations, but when present, declared relationships are strong evidence:

| CMDB Signal | Indicates | Confidence |
|---|---|---|
| Dependency record: "App X depends on MuleSoft" | iPaaS plane routing | 0.80 (if CMDB is maintained) |
| Config item type = "integration platform" for Workato | Fabric plane existence | 0.90 |
| Relationship: "Service A integrated with Service B via Kong" | API Gateway pipe | 0.85 |
| Asset tagged as "middleware" or "integration" | Potential plane or pipe | 0.60 |

**The risk:** Stale CMDB data. Finance might show no MuleSoft contract, but CMDB still says "integrated via MuleSoft" — a contradiction that is itself a valuable finding.

**AOD action:** Extract all CMDB dependency/relationship records that reference known fabric plane vendors. Cross-reference against Finance plane to validate currency. Flag contradictions.

#### 3.4 Finance Plane (💰) — Organizational Fabric Plane Map

**What it reveals:** Which fabric planes exist (paid for) and who owns them.

| Finance Signal | Indicates | Confidence |
|---|---|---|
| Enterprise contract for Workato/MuleSoft/Tray.io | iPaaS plane exists | 0.95 (existence) |
| Confluent Cloud subscription | Event Bus plane exists | 0.95 (existence) |
| Snowflake / BigQuery billing | Data Warehouse plane exists | 0.95 (existence) |
| Kong Enterprise / Apigee subscription | API Gateway plane exists | 0.95 (existence) |
| Department-level Zapier subscription | Shadow iPaaS plane | 0.85 |
| Usage-based invoices with volume data | Scale of integration through plane | Medium |

**Critical insight:** Finance data reveals **shadow fabric planes** — a marketing team paying for their own Zapier Pro account is a fabric plane that IT doesn't know about. This is a high-value finding.

**Finance does NOT tell you** which specific assets route through which planes. It only confirms plane existence and ownership at an organizational level.

**AOD action:** Use Finance data to build the "expected fabric plane inventory" for the environment. Any plane found in Cloud/Network scans that doesn't appear in Finance = potential shadow plane. Any plane in Finance that doesn't appear in Cloud/Network = possible decommissioned or underused plane.

#### 3.5 IdP Plane (🔐) — Authentication Relationships

**What it reveals:** Which assets have authentication/authorization relationships with fabric plane platforms.

| IdP Signal | Indicates | Confidence |
|---|---|---|
| OAuth grant from App → Workato | App is connected via iPaaS | 0.75 |
| SAML assertion for Kong admin portal | User manages API Gateway | 0.60 (admin, not a pipe) |
| OAuth client ID in API Gateway matching known app | App routes through gateway | 0.80 |
| Service account credentials for Snowflake from ETL tool | ETL routes through warehouse | 0.75 |

**Limitation:** IdP data shows authentication relationships, not data flow. An OAuth grant from Salesforce to Workato means Workato *can* access Salesforce — not that it currently *does*. Useful as corroborating evidence, not primary.

**AOD action:** Cross-reference IdP OAuth grants and service account bindings against known fabric plane platforms. Use as Tier 2 evidence when combined with other signals.

#### 3.6 Endpoint Plane (💻) — Minimal Fabric Signal

**What it reveals:** Mostly irrelevant for fabric plane classification.

Endpoint data (installed software, device inventory) occasionally reveals locally installed integration agents (MuleSoft Mule Runtime on a server, Kafka client libraries) but this is rare and unreliable.

**AOD action:** Low priority. Only flag if specific integration runtime binaries are detected on server endpoints.

### Phase 1 Output

After processing all observation planes, AOD should have:

1. **Fabric Plane Registry** — Confirmed list of planes in the environment, with source evidence (Cloud found it, Finance confirms payment, Network shows traffic)
2. **Routing Evidence Table** — Per-asset collection of all signals indicating fabric plane connections, each with a source tag and individual confidence score
3. **Shadow Plane Candidates** — Planes detected in Network/Cloud that aren't in Finance/CMDB, or Finance entries with no Cloud/Network presence
4. **Unattached Assets** — Assets with no fabric routing evidence from any observation plane

---

### Phase 2: Direct Fabric Plane Crawl

**What:** Connect directly to each confirmed fabric plane's management/admin API and pull the authoritative pipe catalog.

**When:** After Phase 1, using the Fabric Plane Registry as the target list.

**Why this is Phase 2 not Phase 1:** The observation plane harvest (Phase 1) tells AOD *which planes exist* and gives preliminary routing evidence. The direct crawl then *validates and enriches* with authoritative catalog data. This is better than guessing which planes to crawl.

| Fabric Plane | API / Method | What You Get | Readiness |
|---|---|---|---|
| **Kong** | Admin API (`/services`, `/routes`, `/upstreams`) | Every registered service, route, and plugin — each one is a pipe | Day-one ready |
| **Apigee** | Management API (API proxies, products, deployments) | API proxy catalog with target endpoints | Day-one ready |
| **AWS API Gateway** | AWS SDK (REST APIs, HTTP APIs, routes, integrations) | Full route and integration target map | Day-one ready |
| **Workato** | Platform API (recipes, connections, job history) | Recipe catalog with connected apps — each recipe = pipe(s) | Day-one ready, needs admin API key |
| **MuleSoft** | Anypoint Platform API (apps, flows, API specs) | Application and flow catalog | Ready, but access varies by licensing |
| **Confluent Cloud** | Management API (clusters, topics, schemas) | Topic catalog with schema metadata | Ready if using Confluent managed |
| **Self-hosted Kafka** | Admin client (topic list) + Schema Registry API | Topic list, possibly schemas | Depends on setup, may lack schema registry |
| **Snowflake** | `INFORMATION_SCHEMA` + `ACCOUNT_USAGE` views via SQL | Full table/schema/database catalog | Day-one ready, but noisy (see below) |
| **BigQuery** | `INFORMATION_SCHEMA` or REST API | Dataset and table catalog | Day-one ready, similarly noisy |

#### Data Warehouse Noise Problem

Warehouse plane crawls return *everything* in the warehouse — staging tables, analytics models, scratch work, dbt transformations, as well as actual landing zones from external systems. AOD needs heuristics to identify which tables represent "pipes":

- **Naming conventions:** Tables in schemas named `raw_*`, `landing_*`, `source_*`, or `stg_*` are likely ingest pipes
- **Freshness patterns:** Tables with regular write cadences (daily, hourly) from identifiable ETL processes
- **Cross-reference with iPaaS crawl:** If Workato has a recipe writing to Snowflake table X, that table is a confirmed pipe endpoint
- **Fivetran/Airbyte metadata:** If a managed ELT tool is present, its connector catalog directly maps to warehouse pipes

#### Phase 2 Output

For each confirmed pipe discovered through direct crawl:

- Pipe name and identifier from the plane's catalog
- Source system (the SOR at the other end of the pipe)
- Fabric plane (automatically correct — determined by *which crawl found it*)
- Connectivity modality (from plane metadata: CONTROL_PLANE for iPaaS recipes, DECLARED_INTERFACE for gateway routes, PASSIVE_SUBSCRIPTION for event bus topics, etc.)
- Schema/entity information (if available from the plane)
- Health/status (if the plane reports it)
- Confidence: **0.95** (Tier 1 — authoritative source)

---

### Phase 3: Reconciliation & Gap Analysis

**What:** Cross-reference Phase 1 evidence against Phase 2 catalog data. Identify discrepancies and unresolved assets.

#### 3.1 Validation

For each pipe found in Phase 2 (direct crawl), check whether Phase 1 (observation planes) had corroborating evidence:

| Scenario | Meaning | Action |
|---|---|---|
| Phase 2 pipe confirmed by Phase 1 evidence | Full corroboration | Confidence → 0.95+ |
| Phase 2 pipe found, no Phase 1 evidence | Possible stale/inactive pipe | Flag for drift review |
| Phase 1 evidence exists, no Phase 2 match | Pipe exists but isn't in plane catalog | Investigate — could be direct/unmanaged connection using plane infra informally |

#### 3.2 Cross-Plane Deduplication

The same SOR may appear as pipes in multiple planes. This is expected and correct — but AOD should correlate them:

Example: Salesforce appears as:
- Workato recipe "Sync SF Opportunities" → iPaaS pipe
- Kong service "salesforce-api-proxy" → API Gateway pipe  
- Snowflake table `raw.salesforce.contacts` → Data Warehouse pipe

These are **three distinct pipes** to the **same SOR**. AOD should link them via the SOR identity while keeping them as separate pipe records with distinct fabric plane assignments.

#### 3.3 Unresolved Asset Triage

For assets that have *no* fabric routing evidence from Phase 1 or Phase 2:

| Scenario | Classification | Value |
|---|---|---|
| Asset is a standalone SaaS (no integration needed) | No pipe expected | Low — document and move on |
| Asset should have integration but doesn't | Integration gap | Medium — potential AAM onboarding candidate |
| Asset has direct point-to-point connections (detected via Network plane) bypassing all fabric planes | Unmanaged pipe | **High** — shadow integration, governance risk |
| Asset has evidence of connecting to a plane that AOD couldn't crawl (e.g., self-hosted Kafka with no admin access) | Unverified pipe | Medium — note the limitation, suggest access provisioning |

#### 3.4 Shadow IT Detection via Fabric Evidence

One of the highest-value outputs of the new approach:

**On-plane shadow assets:** Phase 2 direct crawl finds a pipe connecting to an SOR that doesn't appear in AOD's known asset inventory (not in CMDB, not in SSO, not in Finance). The *pipe reveals the shadow asset*. This is more valuable than traditional shadow IT detection because it catches shadow apps that are **actively moving data**.

**Shadow fabric planes:** Phase 1 observation planes (especially Finance and Network) detect fabric infrastructure that IT doesn't know about — a team's Zapier account, an unauthorized Kafka cluster, a rogue API gateway.

---

## 4. Revised Data Model

### 4.1 Pipe Record (Updated)

```
pipe:
  id: string                          # Unique pipe identifier
  name: string                        # Human-readable name (should encode routing path)
  source_system: string               # The SOR at the data-producing end
  target_system: string               # The SOR at the data-consuming end (if known)
  
  fabric_plane: enum                  # API_GATEWAY | IPAAS | EVENT_BUS | DATA_WAREHOUSE | UNMANAGED
  fabric_plane_instance: string       # Specific instance: "Kong Production", "Workato Org 1"
  
  modality: enum                      # CONTROL_PLANE | DECLARED_INTERFACE | PASSIVE_SUBSCRIPTION | MINIMAL_TEE
  
  classification_method: enum         # DIRECT_CRAWL | OBSERVED | INFERRED
  classification_evidence: []         # List of evidence records (see below)
  classification_confidence: float    # 0.0 – 1.0, computed from evidence
  
  governance_status: enum             # SANCTIONED | UNDER_REVIEW | SHADOW | UNKNOWN
  
  entity_scope: string[]              # Business entities flowing through this pipe
  trust_labels: int                   # Count of applied trust labels
  drift_status: enum                  # OK | OPEN | DETECTED
  owner: string                       # Team/vendor ownership
```

### 4.2 Evidence Record

```
evidence:
  source_plane: enum                  # CLOUD | NETWORK | CMDB | FINANCE | IDP | ENDPOINT | DIRECT_CRAWL
  signal_type: string                 # e.g., "network_flow_to_kong", "cmdb_dependency_record"
  signal_detail: string               # Raw evidence: IP, hostname, CMDB record ID, etc.
  confidence: float                   # Individual signal confidence
  timestamp: datetime                 # When this evidence was collected
```

### 4.3 Composite Confidence Scoring

Instead of a flat 0.70 for everything, confidence is computed from accumulated evidence:

```
Rules:
  - Single Tier 1 evidence (direct crawl) → 0.95
  - Multiple Tier 2 evidence (2+ observation planes agree) → 0.85
  - Single Tier 2 evidence → 0.70
  - Tier 3 only (category inference) → 0.35
  - Contradictory evidence across tiers → flag for manual review, confidence = 0.40
  - No evidence → no fabric assignment (don't guess)
```

### 4.4 Naming Convention

Pipe names should encode the routing path, not just the SOR:

| Current (Ambiguous) | Proposed (Clear) |
|---|---|
| Salesforce - Direct Query (Legacy) | Kong → Salesforce Direct Query |
| Marketo - Lead Events | Workato → Marketo Lead Events |
| Workato - Slack Notifications | Workato: Slack Notification Recipe |

Format: `{Plane Instance} → {Source System} {Descriptor}` for pipes discovered through a plane, or `{Source} ↔ {Target} (Unmanaged)` for direct connections.

---

## 5. What Changes for Category-Based Inference

The existing category routing table is **not eliminated** — it is **demoted to Tier 3** and its confidence is reduced to accurately reflect its reliability.

### When Tier 3 Still Applies

Category-based inference becomes the fallback when:
- No observation plane signals exist for the asset
- Direct plane crawl didn't surface the asset
- But the asset *is* known to exist (via CMDB, Finance, or IdP)

In this case, AOD applies the existing routing table but with these changes:

| Change | Old | New |
|---|---|---|
| Confidence | 0.70 | 0.30–0.50 |
| Default to iPaaS | Always | Only if iPaaS plane is confirmed to exist |
| Single assignment | One plane per asset | Flag as "inferred, may have multiple paths" |
| Presentation | Shown as fact | Shown as hypothesis requiring validation |

### Eliminated Assumptions

- ~~CRM always routes through iPaaS~~ → CRM connects however the enterprise configured it
- ~~BI always routes through Data Warehouse~~ → BI may go through any plane
- ~~Unknown defaults to iPaaS~~ → Unknown = no assignment, flagged for investigation

---

## 6. Impact on Farm (Test Oracle)

Farm generates test data with known correct answers. The current Farm likely generates assets with category-based plane assignments. The Farm must be updated to reflect the evidence-based model.

### 6.1 Tenant / Snapshot Composition Changes

Farm test tenants need to include:

**Observation plane data that implies fabric routing:**
- Mock cloud resource inventories containing fabric plane infrastructure (API Gateway instances, Kafka clusters, Snowflake endpoints)
- Mock network flow records showing traffic patterns between assets and fabric plane endpoints
- Mock CMDB dependency records (including some deliberately stale ones)
- Mock finance records showing fabric plane subscriptions (including shadow plane subscriptions under non-IT cost centers)
- Mock IdP OAuth grant records

**Multi-plane SOR scenarios:**
- At least one SOR that connects through 2+ fabric planes simultaneously
- Correct answer key: the SOR should have multiple pipe records, one per plane

**Shadow asset scenarios:**
- Fabric plane crawl reveals a pipe connecting to an SOR that's not in CMDB/Finance/IdP
- Correct answer: asset flagged as shadow with governance_status = SHADOW

**Shadow plane scenarios:**
- Finance data shows a department paying for Zapier (shadow iPaaS)
- Network data shows traffic to `hooks.zapier.com`
- But Zapier is not in the primary fabric plane registry
- Correct answer: new fabric plane discovered, flagged as shadow

**Contradictory evidence scenarios:**
- CMDB says "integrated via MuleSoft" but Finance shows no MuleSoft contract
- Network shows no traffic to MuleSoft endpoints
- Correct answer: stale CMDB record, low confidence, flagged for review

**Unmanaged pipe scenarios:**
- Network shows direct API-to-API traffic between two SORs bypassing all fabric planes
- Correct answer: pipe with fabric_plane = UNMANAGED, high-value finding

### 6.2 Test Validation Changes

Farm's correctness validation must check:

1. **Fabric plane assignment matches evidence, not category** — if the test data has Salesforce traffic going through Kong (Network plane evidence) AND a Workato recipe for Salesforce (direct crawl evidence), the correct answer is TWO pipes, not one iPaaS pipe
2. **Confidence scores reflect evidence tier** — Tier 1 evidence should produce higher confidence than Tier 3
3. **No assignment is better than wrong assignment** — if test data deliberately omits evidence for an asset, AOD should produce NO fabric plane assignment (not a default iPaaS assignment)
4. **Shadow detection fires correctly** — shadow assets and shadow planes should be identified when evidence is present
5. **Contradictions are flagged** — when evidence conflicts, the system should surface the conflict rather than silently picking one

---

## 7. Implementation Sequence

### Sprint 1: Evidence Collection Layer

- Add fabric-plane-aware analysis to Cloud observation plane processing
- Add fabric-plane-aware analysis to Network observation plane processing  
- Add fabric-plane-aware analysis to Finance observation plane processing
- Define the `evidence` data structure and attach it to pipe/asset records
- Demote category-based inference to Tier 3 with reduced confidence

### Sprint 2: Direct Plane Crawl Connectors

- Build Kong Admin API connector (easiest, most well-documented)
- Build Workato Platform API connector
- Build Snowflake INFORMATION_SCHEMA query connector
- Define connector interface for future plane additions

### Sprint 3: Reconciliation Engine

- Cross-reference Phase 1 evidence against Phase 2 catalog data
- Implement composite confidence scoring
- Implement cross-plane SOR deduplication (same SOR, multiple pipes)
- Build contradiction detection logic

### Sprint 4: Farm Test Oracle Update

- Redesign tenant snapshots with multi-signal evidence data
- Add multi-plane SOR test cases
- Add shadow asset / shadow plane test cases
- Add contradiction test cases
- Update correctness validation to check evidence-based classification

### Sprint 5: AAM Handoff Enhancement

- Pass evidence records along with pipe data in AOD → AAM handoff
- AAM uses evidence to assess connection reliability (Tier 1 evidence = pipe already exists and is healthy; Tier 3 = pipe is hypothetical)
- Shadow assets discovered on-plane already have a natural connection path — AAM doesn't need to figure out how to connect, just whether to trust the existing pipe

---

## 8. Success Criteria & Evaluation Framework

### 8.1 Primary Success Metric: Classification Accuracy

The single most important measure is: **when AOD assigns a pipe to a fabric plane, how often is it correct?**

| Metric | Current (Category Inference) | Target (Evidence-Based) | How to Measure |
|---|---|---|---|
| **Overall classification accuracy** | ~50% (estimated) | ≥ 85% for Tier 1+2 evidence | Farm oracle comparison: AOD output vs. known-correct answer key |
| **Tier 1 accuracy (direct crawl)** | N/A (doesn't exist) | ≥ 95% | Pipe found via plane crawl should match ground truth in 95%+ of cases |
| **Tier 2 accuracy (observed)** | N/A (doesn't exist) | ≥ 80% | Observation-plane-based assignment should match ground truth in 80%+ |
| **Tier 3 accuracy (inferred)** | ~50% | ≥ 50% (but confidence correctly reflects this) | Category inference accuracy doesn't need to improve — it just needs honest confidence |
| **False positive rate** | Unknown (no tracking) | ≤ 10% | Pipes assigned to a plane they don't actually belong to |
| **False negative rate** | High (multi-plane not supported) | ≤ 15% | Real pipes that exist but AOD fails to discover or classify |

**Key distinction:** The goal is not just higher accuracy but *calibrated confidence*. A system that says "I'm 35% sure this is iPaaS" and is right 35% of the time is better than one that says "I'm 70% sure" and is right 50% of the time. Calibration matters as much as accuracy.

### 8.2 Confidence Calibration Metric

For each confidence tier, the actual accuracy should approximate the stated confidence:

| Confidence Band | Expected Accuracy | Acceptable Range | Failure Condition |
|---|---|---|---|
| 0.90–0.95 (Tier 1) | ~93% | 88–98% | Accuracy below 85% means crawl connectors have bugs |
| 0.70–0.90 (Tier 2) | ~80% | 70–90% | Accuracy below 65% means observation plane signals are unreliable |
| 0.30–0.50 (Tier 3) | ~40% | 25–55% | Accuracy above 70% means we're underrating the inference (raise confidence) |

**How to evaluate:** Run AOD against Farm test tenants where ground truth is known. Group all classifications by their confidence score. For each group, calculate what percentage were actually correct. Plot a calibration curve — ideal is a diagonal line (stated confidence = actual accuracy).

### 8.3 Coverage Metrics

Accuracy means nothing if AOD only classifies 10 out of 200 assets. Coverage measures completeness:

| Metric | Current | Target | Definition |
|---|---|---|---|
| **Pipe discovery rate** | Unknown | ≥ 70% of real pipes | Of all pipes that exist in the test environment, how many does AOD find? |
| **Tier 1 coverage** | 0% | ≥ 60% of discovered pipes | What percentage of discovered pipes have direct crawl evidence? |
| **Tier 2 coverage** | 0% | ≥ 25% of discovered pipes | What percentage have observation plane evidence (may overlap with Tier 1)? |
| **Tier 3 only** | 100% | ≤ 20% of discovered pipes | What percentage rely solely on category inference? Should shrink dramatically |
| **Unclassified rate** | 0% (everything gets iPaaS default) | 5–15% | Assets with genuinely no evidence — should exist but be small |
| **Multi-plane SOR detection** | 0% (not supported) | ≥ 80% | Of SORs with multiple plane connections, how many does AOD correctly identify as multi-plane? |
| **Shadow pipe detection rate** | 0% (separate system) | ≥ 50% of shadow pipes | Of pipes connecting to shadow assets, how many are caught via plane evidence? |

### 8.4 Farm Test Scenarios with Expected Outcomes

Each Farm test tenant must include these scenario types with explicit expected outputs that the oracle validates:

#### Scenario 1: Single-Plane SOR (Basic)

**Setup:** Salesforce instance with exactly one Workato recipe syncing Opportunities.

**Evidence provided:**
- Cloud plane: Workato agent running on ECS
- Network plane: traffic from Workato IP to Salesforce API
- Finance plane: Workato Enterprise subscription
- Direct crawl: Workato recipe catalog returns "Sync SF Opportunities"

**Expected AOD output:**
- 1 pipe: "Workato → Salesforce Opportunity Sync"
- Fabric plane: IPAAS
- Confidence: 0.95 (Tier 1 — direct crawl found it)
- Evidence records: 4 (one from each source)

**Pass criteria:** Pipe exists, plane = IPAAS, confidence ≥ 0.90, evidence count ≥ 1 from direct crawl.

#### Scenario 2: Multi-Plane SOR (Critical)

**Setup:** Salesforce instance connected through 3 planes simultaneously.

**Evidence provided:**
- Workato recipe syncing Opportunities (iPaaS)
- Kong service proxying Salesforce REST API (API Gateway)
- Snowflake table `raw.salesforce.contacts` with daily refresh (Data Warehouse)
- Network flows confirming traffic to all three planes
- Finance records for all three plane subscriptions

**Expected AOD output:**
- 3 separate pipes, all linked to SOR "Salesforce"
- Pipe 1: IPAAS, confidence 0.95
- Pipe 2: API_GATEWAY, confidence 0.95
- Pipe 3: DATA_WAREHOUSE, confidence 0.95

**Pass criteria:** Exactly 3 pipes created (not 1). All linked to same SOR. Each assigned to correct plane. This is the most important test — if this fails, the fundamental multi-plane model is broken.

**Fail conditions:**
- Only 1 pipe created → multi-plane logic not implemented
- 3 pipes but wrong plane assignments → classification logic broken
- 3 pipes but no SOR linkage → deduplication not working

#### Scenario 3: Shadow Asset Discovered Via Plane

**Setup:** Workato recipe connects to "Notion" — but Notion is not in CMDB, not in SSO, not in Finance.

**Evidence provided:**
- Direct crawl: Workato recipe "Sync Notion Tasks" found
- CMDB: No entry for Notion
- Finance: No Notion subscription found
- IdP: No Notion SSO integration

**Expected AOD output:**
- 1 pipe: "Workato → Notion Task Sync"
- Fabric plane: IPAAS, confidence 0.95
- Governance status: SHADOW
- Finding generated: "Shadow SaaS detected — Notion is actively integrated via Workato but has no CMDB, Finance, or IdP presence"

**Pass criteria:** Pipe discovered with correct plane. Governance status = SHADOW (not SANCTIONED). Finding generated.

#### Scenario 4: Shadow Fabric Plane

**Setup:** Marketing team has a Zapier Pro subscription. IT doesn't know about it.

**Evidence provided:**
- Finance: Zapier Pro invoice under Marketing cost center
- Network: Traffic from 3 marketing servers to `hooks.zapier.com`
- Cloud/CMDB/IdP: No Zapier presence

**Expected AOD output:**
- New fabric plane registered: IPAAS (Zapier) with governance_status SHADOW
- 3 candidate pipes (one per traffic source) with plane = IPAAS (Zapier)
- Confidence: 0.80 (Tier 2 — observed but not directly crawled, since we may not have Zapier admin access)
- Finding: "Shadow iPaaS plane detected — Zapier subscription found under Marketing, not in IT-managed fabric plane registry"

**Pass criteria:** Shadow plane detected. Not merged with the primary iPaaS plane. Finding generated with correct cost center attribution.

#### Scenario 5: Contradictory Evidence

**Setup:** CMDB says ServiceNow integrates via MuleSoft. But there's no MuleSoft subscription, no MuleSoft cloud resources, and no network traffic to MuleSoft.

**Evidence provided:**
- CMDB: Dependency record "ServiceNow → MuleSoft"
- Finance: No MuleSoft contract
- Cloud: No MuleSoft infrastructure
- Network: No traffic to MuleSoft endpoints
- Network: Direct HTTPS traffic from internal app to ServiceNow API (bypassing all planes)

**Expected AOD output:**
- Contradiction flag on the CMDB record
- Pipe: "Internal App ↔ ServiceNow (Unmanaged)" with fabric_plane = UNMANAGED
- Confidence for CMDB claim: ≤ 0.30 (contradicted by 3 other sources)
- Finding: "CMDB dependency record 'ServiceNow → MuleSoft' contradicted — no MuleSoft presence confirmed. Direct unmanaged connection detected instead."

**Pass criteria:** CMDB record not blindly trusted. Unmanaged pipe created from network evidence. Contradiction explicitly surfaced.

#### Scenario 6: No Evidence (Correct Non-Classification)

**Setup:** Asset "Canva" exists in SSO/Finance (known, sanctioned) but has zero integration evidence — no network flows to any plane, no recipes, no gateway routes, no warehouse tables.

**Evidence provided:**
- Finance: Canva subscription
- IdP: Canva SSO integration
- Network/Cloud/CMDB: Nothing referencing Canva in integration context

**Expected AOD output:**
- Asset "Canva" cataloged with governance_status = SANCTIONED
- **No pipe record created**
- Fabric plane: None / Unassigned
- Classification: NOT "defaults to iPaaS" — genuinely unassigned

**Pass criteria:** Zero pipes created for this asset. This validates that AOD doesn't hallucinate connections. The old system would have assigned iPaaS at 0.70 confidence — the new system should produce nothing.

**Fail condition:** Any pipe created with any fabric plane assignment → the system is still guessing.

#### Scenario 7: Data Warehouse Noise Filtering

**Setup:** Snowflake instance with 500 tables. Only 12 are actual landing zones from external systems. The rest are dbt models, staging tables, analyst scratch work.

**Evidence provided:**
- Direct crawl: Snowflake INFORMATION_SCHEMA returns all 500 tables
- Cross-reference: Workato/Fivetran writes to 12 specific tables (identifiable via iPaaS crawl or naming convention)

**Expected AOD output:**
- 12 Data Warehouse pipes (not 500)
- Each linked to the correct source SOR
- 488 tables excluded as non-pipe warehouse objects

**Pass criteria:** Pipe count between 10–15 (allowing some tolerance). Definitely not 500. The false positive rate on warehouse pipe identification should be ≤ 20%.

### 8.5 Regression Criteria

The new system must not break things the old system got right:

| Regression Check | Definition | Threshold |
|---|---|---|
| **Plane detection** | Fabric plane "mothership" detection (Stage 1 of old system) | Must still detect 100% of planes the old system found |
| **iPaaS pipe accuracy** | For assets that genuinely DO route through iPaaS | Accuracy must be ≥ old system (category inference was often right for iPaaS-heavy environments) |
| **Scan completion time** | Total time for AOD discovery scan | ≤ 2x current scan time (adding observation plane analysis and direct crawls has a cost) |
| **Pipe count** | Total pipes discovered | Should be ≥ old system count (new system should find MORE pipes due to multi-plane discovery, not fewer) |

### 8.6 Per-Sprint Acceptance Criteria

#### Sprint 1: Evidence Collection Layer — DONE WHEN:
- [ ] Cloud plane processing extracts fabric plane candidates from cloud resource inventory
- [ ] Network plane processing identifies traffic flows to known fabric plane endpoints
- [ ] Finance plane processing identifies fabric plane subscriptions and flags shadow plane candidates
- [ ] Evidence data structure is defined and attached to asset/pipe records
- [ ] Category inference confidence reduced to 0.30–0.50
- [ ] **Eval:** Run against Farm tenant with known cloud/network/finance data. Evidence records are correctly generated for ≥ 90% of fabric plane signals present in the test data.

#### Sprint 2: Direct Plane Crawl Connectors — DONE WHEN:
- [ ] Kong connector pulls service/route catalog and creates pipe records
- [ ] Workato connector pulls recipe catalog and creates pipe records  
- [ ] Snowflake connector queries INFORMATION_SCHEMA and creates pipe records with noise filtering
- [ ] All connector-discovered pipes have Tier 1 confidence (0.95)
- [ ] Connector interface is defined so new plane connectors follow the same pattern
- [ ] **Eval:** Run connectors against mock plane APIs (Farm-generated). 100% of catalog entries are captured as pipes. Snowflake noise filter excludes ≥ 80% of non-pipe tables.

#### Sprint 3: Reconciliation Engine — DONE WHEN:
- [ ] Phase 1 evidence is cross-referenced against Phase 2 catalog data
- [ ] Composite confidence score is computed from multiple evidence sources
- [ ] Multi-plane SOR deduplication links pipes from different planes to same SOR
- [ ] Contradiction detection fires when evidence sources disagree
- [ ] **Eval:** Run Scenarios 2, 5, and 7 from Section 8.4. All pass criteria met.

#### Sprint 4: Farm Test Oracle Update — DONE WHEN:
- [ ] Farm generates test tenants with observation plane data (network flows, cloud resources, finance records, CMDB entries)
- [ ] Farm generates multi-plane SOR scenarios with known-correct answer keys
- [ ] Farm generates shadow asset and shadow plane scenarios
- [ ] Farm generates contradiction scenarios
- [ ] Farm generates "no evidence" scenarios where correct answer is no classification
- [ ] All 7 scenarios from Section 8.4 are implemented as automated test cases
- [ ] **Eval:** Full test suite runs end-to-end. Overall classification accuracy ≥ 85% on Tier 1+2 evidence. Confidence calibration within acceptable ranges per Section 8.2.

#### Sprint 5: AAM Handoff Enhancement — DONE WHEN:
- [ ] Evidence records are passed in AOD → AAM handoff payload
- [ ] AAM can distinguish Tier 1 pipes (ready to manage) from Tier 3 pipes (hypothetical, needs validation)
- [ ] Shadow assets discovered on-plane include the existing connection path in handoff data
- [ ] **Eval:** AAM receives handoff data for all 7 test scenarios. AAM correctly prioritizes Tier 1 pipes for immediate management and flags Tier 3 pipes for manual review.

### 8.7 Ongoing Health Metrics (Post-Launch)

After deployment, track these weekly:

| Metric | Target | Alert Threshold |
|---|---|---|
| % of pipes with Tier 1 evidence | ≥ 60% | Alert if drops below 50% (connectors may be failing) |
| % of pipes with Tier 3 only | ≤ 20% | Alert if rises above 30% (evidence collection may be degraded) |
| Contradiction rate | 5–15% is healthy | Alert if above 25% (data quality issue) or below 2% (detection may be broken) |
| Unclassified asset rate | 5–15% | Alert if above 25% (evidence collection gaps) or 0% (system is probably guessing again) |
| Shadow detection rate per scan | Varies | Track trend — should be stable or declining as shadow IT is remediated |
| Scan completion time | ≤ defined SLA | Alert if exceeds 2x baseline |
| Confidence calibration drift | Diagonal ± 10% | Alert if any confidence band's actual accuracy diverges more than 15% from stated confidence |

---

## 9. Summary of Key Shifts

| Dimension | Old (Category Inference) | New (Evidence-Based) |
|---|---|---|
| **Primary signal** | Asset category/type keywords | Observation plane evidence + direct plane crawl |
| **Discovery direction** | Asset-first ("find Salesforce, guess its plane") | Plane-first ("crawl Kong, find what's registered") |
| **Confidence model** | Flat 0.70 for all inferences | Tiered: 0.95 (direct) / 0.70–0.90 (observed) / 0.30–0.50 (inferred) |
| **Multi-plane support** | One plane per asset | Multiple pipes per SOR, one per plane |
| **Shadow IT detection** | Separate concern | Integrated — planes reveal shadow SORs, observation data reveals shadow planes |
| **Unmanaged connections** | Not captured (everything gets a plane) | Explicit UNMANAGED classification for direct point-to-point |
| **Default behavior** | Unknown → iPaaS | Unknown → no assignment, flagged for investigation |
| **Evidence trail** | None | Every classification has attached evidence records with source and confidence |
| **Farm test coverage** | Category → plane correctness | Multi-signal, multi-plane, shadow, contradiction scenarios |
