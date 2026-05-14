# AAM — How It Works

*AOS Adaptive API Mesh | April 2026*
*Sources: AAM_Connectivity_Architecture_Blueprint_Master, AOS_MASTER_RACI_v8.6, pipeline_identity_architecture_v1, mai_blueprint_master.*

---

## What AAM does

AAM is the bridge between a customer's enterprise systems and AOS. Its job is to connect to whatever integration infrastructure the customer already runs — iPaaS platforms, API gateways, event buses, data warehouses — discover the data pipes that already exist there, and transport records through those pipes into the AOS semantic layer. AAM does not build connectors per application. It connects to the four pieces of middleware that already connect everything else, and reads the work that customer's integration team has already done.

A mid-market enterprise runs 200–500 applications. Connecting to six to ten plane instances reveals every integration in flight. Adapters for **four plane types** replace connectors for hundreds of apps. This is why AOS deployments are days, not months.

---

## Technologies deployed

| Layer | Choice | Role |
|---|---|---|
| Backend runtime | Python 3 / FastAPI (async) | One framework, one deployment model |
| Frontend (admin) | Server-rendered HTML + Tailwind | Operator-facing pipe inventory, health dashboard, drift queue |
| Control plane store | SQLite | Per-tenant connection registry, pipe catalog, run history |
| Semantic write path | Postgres on Supabase via `execute_values` | Same path Farm uses; one tenant-isolation model |
| Discovery protocol | Universal MCP client (Anthropic Model Context Protocol) | Vendor-maintained tool surface, one client covers all servers |
| Discovery vendor coverage | MCP servers: Workato, MuleSoft, Boomi, Apigee, Snowflake, Databricks. Disposable shims: Kong, AWS API Gateway, EventBridge, Redshift, BigQuery | Native where vendor ships MCP; shim where they don't |
| Transport — events | Kafka wire protocol (covers Confluent, Azure Event Hubs, AWS MSK with one impl) | Consumer subscription, offset tracking, schema registry |
| Transport — APIs | HTTP (webhooks, REST proxy, callable endpoints, pipeline polling) | Auth-injected passthrough through gateways |
| Transport — warehouses | Async SQL via vendor REST APIs (Snowflake, BigQuery, Databricks, Redshift) plus CDC (Streams, Delta CDF, streaming MV) | Bulk + incremental reads with provenance |
| Transport — push | WebSocket / SSE | Real-time streams when needed |
| Network plane | AOS Edge Agent — outbound-only WireGuard tunnel on 443 | Reaches private VPCs without inbound firewall changes |
| Process manager | pm2 | Same launch model on dev hosts and production |
| Hosting | Render | Per-service auto-deploy from `dev` |
| Identity contract | `tenant_id` (UUID) + `entity_id` (business key) on every stage response — namespaced `aam_inference_id` (no bare `run_id`) | Hard 422 on missing pair; no silent fallback |

---

## What's unique about AAM

- **MCP-first, not connector-first.** Major fabric-plane vendors are shipping MCP servers in 2026. AAM runs a single universal client. The vendor maintains the mapping from their API to MCP. When their API changes, AAM doesn't. Vendor shims for the laggards are explicitly disposable — deleted the day the vendor ships its server.
- **Four transports for everything.** Kafka, HTTP, SQL, WebSocket/SSE. One Kafka implementation covers Confluent, Azure Event Hubs, and AWS MSK. Four transports replace dozens of connectors.
- **Discovery and transport are separated.** Discovery runs over MCP (universal, vendor-maintained). Transport runs over native protocols (efficient, well-understood). Neither is bent into the other's shape.
- **The customer's middleware does the work.** AAM does not build integrations. It reads integrations the customer has already built. One Workato connection reveals 50–100 app integrations already in flight.
- **Self-healing per vendor, not per app.** 13 vendor health profiles cover every plane. Re-auth Workato, restart MuleSoft, resubscribe Boomi, resume Snowflake warehouse, reset Kafka offsets — all behind one health state machine.

---

## Governance and security posture

- **Outbound-only network access.** The AOS Edge Agent is a sidecar deployed inside the customer network. It opens one encrypted tunnel on port 443 — no inbound firewall changes, no VPC peering, no security-team escalation. Endpoint allowlist enforced at the agent. Audit log on every proxied connection.
- **Credentials never leave the customer.** Edge Agent terminates auth locally. AOS sees data, not credentials.
- **Policy at the edge.** AAM is the policy point — PII redaction, auth validation, rate limiting — applied before any record crosses into the semantic store. Wrong place to fail is after the data lands.
- **Identity contract is hard.** Every stage response carries `tenant_id` + `entity_id`. Missing = 422. No silent degradation at service boundaries. Bare `run_id` is banned from payloads (pipeline_identity_architecture_v1, rule I1).
- **No silent fallback — anywhere.** If a fabric plane is unreachable, AAM raises a typed error with the endpoint, retry count, and downstream impact. Errors are loud. Empty results are not "soft success."
- **Tenant isolation via Supabase RLS** on the semantic write path. One identity column on every row.
- **Pre-commit guardrails.** CI blocks silent exception swallowing, defaulted exception returns, hardcoded entity names, hardcoded seed UUIDs, references to the deprecated demo-data file, and unnamespaced run identifiers in API payloads. Hooks cannot be bypassed.

---

## Use of AI

AAM uses LLMs in three bounded places. Nowhere does an LLM control flow.

- **Semantic field mapping (Sonnet).** The production ingest pipeline turns raw vendor records into semantic triples. An LLM proposes mappings from source fields to AOS's curated ontology (19 verified domains, 131 integration tests of concept definitions). It maps **to** existing concepts — it does not invent new ones. Confidence ≥ 0.9 auto-applies and flags for review; 0.7–0.9 routes to human confirmation; below 0.7 presents alternatives. All mappings clear human Layer-3 confirmation before going live.
- **MCP tool invocation (any client, model-agnostic).** Discovery is structured. The LLM is the consumer of MCP, not the inventor of behavior — tool definitions come from the vendor's MCP server, AAM calls them.
- **Maestra credential onboarding (Sonnet, supervised).** Maestra generates vendor-specific provisioning checklists with exact GRANT/CREATE commands and Edge Agent deployment instructions, validates credentials as they arrive, and walks the customer through discovery review. Every action is governed by the four-tier supervised-execution classifier: auto-execute, validate-with-Farm-dry-run, plan-mode, or escalate-only.

What AAM does not do with LLMs: route data, transform records, reconcile identities silently, or decide what's true. Hard accounting gates and identity invariants are deterministic.

---

## Learning and RAG

- **Pinecone vector store.** Semantic-mapping refinement uses embedding-based recall. When a similar field has been mapped before — across the same tenant, or across the AOS customer base where the customer opts in — the previous mapping is retrieved as a prior, raising the proposed mapping's confidence and shortening human review time.
- **Reuse across tenants is privacy-preserving.** Mapping shape (field name patterns, concept) carries forward; record content does not.
- **Drift-aware.** When a Workato pipeline schema drifts mid-sync, the field mapper re-proposes affected fields, flags them for re-confirmation, and continues with a hold rather than silently mapping to a stale concept.
- **Heal history is a learning surface.** Self-heal events (re-auth, warehouse resume, consumer restart) are logged with outcome. Repeat patterns surface to operators as standing alerts: "this tenant's Snowflake warehouse suspends six times a day — investigate auto-suspend setting."

---

## Speed and performance

- **Days, not months.** End-to-end deployment timeline:
  - Day 0: AOD scan + tech-stack interview. Maestra issues credential checklist + Edge Agent instructions. Farm pushes synthetic data matching the discovered pipe schemas through the production path — customer sees their actual topology with believable fake data before live credentials are granted.
  - Days 1–3: Customer provisions credentials and deploys Edge Agent (this is the gating step — AOS has no work here).
  - Day 3: Tunnel established, discovery runs, pipe catalog reviewed.
  - Day 4: Transport configured, semantic field mapping run, first live data lands.
  - Day 5: Semantic layer active. Customer asks first question against their own data.
- **5% latency budget.** More than a 5% regression on any AAM endpoint blocks merge. Hard ceilings are absolute. Latency ceilings mean the operation **completes** in time, not aborts in time — timeouts are not performance fixes.
- **Backpressure and dedup are first-class.** The continuous flow controller batches records for efficient PG writes (`execute_values`), deduplicates on `pipe_id + record_key + offset`, and applies rate limiting per pipe. No single pipe can starve the others.
- **No caching of stale state.** Health checks are live. Every test run hits the live system fresh.
- **Sub-ms cross-service reads.** Convergence reads DCL-owned tables directly (SELECT only) at report time. Same pattern keeps AAM's pipe catalog reads cheap from Console.

---

## Enterprise-grade aspects

- **Multi-tenant by construction.** Per-tenant MCP connection registry, per-tenant pipe catalog, per-tenant Edge Agent token, per-tenant Postgres rows behind RLS. One tenant cannot see another tenant's pipes, credentials, or records.
- **13 vendors, four planes, one health model.** Reachable / degraded / unreachable / auth_expired. Detection signals and self-heal actions are wired per vendor (re-auth Workato, restart MuleSoft app, resume Snowflake warehouse, reset Kafka offsets, throttle AWS API Gateway, refresh Redshift streaming MV — full table in the blueprint). Self-heal actions are logged.
- **CDC where it matters.** Snowflake Streams, Delta Change Data Feed, Redshift streaming MV, Snowpipe Streaming for real-time. AAM doesn't re-read full tables when the warehouse already exposes change feeds.
- **Provenance on every triple.** Source system, source field, pipe ID, AAM inference ID, confidence score, created-at. Every value in DCL is traceable to the record, the pipe, and the run that produced it.
- **Maestra runs the prework.** Tech-stack identification from AOD plus structured interview. Vendor-specific credential checklists with exact commands. Credential validation as credentials arrive. Discovery review with the customer. Transport configuration walkthrough. Maestra is the interface between the customer's IT team and the AOS pipeline — the customer's IT team gets exact commands, not generic instructions.
- **Branch hygiene enforced.** Feature branches merge to `dev` and delete in the same session. Pre-commit hooks block silent-fallback patterns and identity violations. `--no-verify` is banned.

---

## How AAM is tested via Farm

Farm is AAM's ground-truth oracle. AAM's correctness is measured against what Farm knows is true.

**Schema-aware synthetic data.** Farm reads DeclaredPipe schemas from AAM's MCP discovery and generates realistic synthetic records conforming to those schemas. Records flow through the **production** path — same transport shims, same flow controller, same triple converter, same `execute_values` write — that live data will use. The customer sees their actual topology working on Day 0. Synthetic triples are tagged `source_system='synthetic'` and purgeable.

**Synthetic harness — AAM's real code, simulated vendor endpoints.** The harness replaces live vendor endpoints with five local stubs so AAM's real MCP client, transport shims, and ingest pipeline run end-to-end in CI without credentials:

| Stub | What it simulates |
|---|---|
| `ipaas_stub` | Workato / MuleSoft / Boomi MCP responses + webhook delivery + pipeline status + event streams (vendor flavor selected per test) |
| `gateway_stub` | Kong / Apigee / AWS API Gateway admin API + proxy passthrough + per-vendor auth |
| `kafka_stub` | Kafka broker — consumer subscription, message delivery, offset tracking, schema registry. Dual auth: Confluent API key + Azure AD/SAS (Event Hubs) |
| `eventbridge_stub` | EventBridge rules, pipes, schema registry, event delivery |
| `warehouse_stub` | Snowflake / BigQuery / Databricks / Redshift SQL API, INFORMATION_SCHEMA, status commands, CDC responses |

**Eleven scenarios cover the failure surface.** `healthy`, `degraded`, `auth_failure`, `drift_connectivity` (reachable → unreachable mid-flow), `consumer_lag`, `warehouse_suspended`, `webhook_failure`, `pipeline_schema_drift`, `gateway_502`, `recovery` (failure → self-heal → recovery verified), `multi_vendor`. Every scenario asserts a positive expected outcome — never "it didn't crash."

**Test discipline (HARNESS_RULES v2):**
- The harness only runs after a fresh pipeline run (rule B15).
- Tests assert against Farm ground-truth fetched at runtime — no hardcoded expected values matching current wrong output (rule B8).
- Every data test checks `source=Ingest` — a correct number from the wrong source is not a pass (rule B12).
- Frontend is the pass/fail gate. Playwright drives the operator path through real UI events (`locator.click()`, `selectOption()`, file pickers), not POSTs from the test runner. A correct API response that doesn't render is not a pass (rule B17).
- All tests pass at session end, including pre-existing failures (rule D6). 100% or not done.
- Run the harness twice — results must be identical (rule B14).

**What pass means.** MCP client connects to harness stubs and discovers tools for every vendor flavor. Transport shims move data through the production ingest pipeline into DCL as semantic triples with correct provenance. Adapter factory selects correct discovery client + transport shim based on vendor config. Edge Agent establishes tunnel and proxies through to simulated internal endpoints. Self-healing detects every injected failure and recovers across all plane types with audit logging. Maestra credential module generates correct provisioning checklists for all vendors and validates credentials against harness stubs. Semantic field mapper proposes reasonable mappings against DCL's 19 known domains with human confirmation. Farm-generated synthetic data lands in DCL with correct triples and `source_system='synthetic'` tag.

No test is skipped. No test is marked `xfail`. Pre-existing failures are fixed, not routed around.
