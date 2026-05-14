# AAM FinOps Demo — End-to-End

*Module: AAM. Source: `app/routers/demo.py`, `app/routers/ingest_demo.py`, `app/ingest/mappings.py`, `tests/fixtures/harness/finops_saas_data/`.*

---

## Intent

Prove "two systems of record, two iPaaS vendors, one unified context" on a question a CFO actually asks. The operator sees the same AAM code path running NetSuite (via Workato) and Okta (via Boomi) end-to-end through MCP discovery → transport → triple write → semantic answer with provenance. No vendor-specific branching downstream of the adapter factory.

The canonical question:

> "Show me SaaS subscriptions where actual utilization is below 50% of paid licenses, ranked by potential annual savings."

The answer is computed deterministically from `semantic_triples` (no LLM), so every dollar figure traces back to a NetSuite invoice or an Okta assignment.

---

## Dataset (fixtures, `tests/fixtures/harness/finops_saas_data/`)

| File | Count | Source path |
|---|---|---|
| `vendors_netsuite.json` | 200 | Workato → NetSuite vendor master |
| `ap_invoices_netsuite.json` | 4,800 | Workato → NetSuite AP invoices (24 months) |
| `apps_okta.json` | 200 | Boomi → Okta SaaS app catalog (license seats + per-seat cost) |
| `users_okta.json` | 600 | Boomi → Okta user directory |
| `assignments_okta.json` | 27,345 | Boomi → Okta app assignments + 30-day-active telemetry |
| `identity_matches.json` | 200 | Pre-computed vendor↔app pairs, one held in review at 0.71 |

Identity-resolution pivot: 199 auto-accepted (exact name match), 1 pending review — *LinkedIn Sales Navigator* (NetSuite) vs *LinkedIn Sales Nav.* (Okta) at 0.71 fuzzy confidence. The pending case proves the pipeline keeps producing an answer while one match is held.

---

## End-to-end workflow

```
┌──────────────────────────┐    ┌────────────────────────┐
│ POST /api/aam/ingest/demo│ →  │ factory → discovery →  │
│ vendors:[workato,boomi]  │    │ DeclaredPipes (MCP)    │
└──────────────────────────┘    └────────────────────────┘
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                      HTTPTransport.fetch     HTTPTransport.fetch
                      (NetSuite vendor +      (Okta apps + users +
                       AP invoices)            assignments)
                              │                       │
                              ▼                       ▼
                      FlowController batches → ingest_records() →
                      app/db/triple_writer → semantic_triples (PG)
                              │
                              ▼
                      GET /api/aam/demo/answer?question=…
                      → SQL aggregation across triples → JSON answer
                              │
                              ▼
                      GET /api/aam/demo/provenance?pipe_id=…&record_key=…
                      → raw triples with source_field per AOS property
```

Identity pair (`tenant_id` UUID + `entity_id` business key) is required on the ingest call. Missing = 422 (no silent fallback per I2). The ingest endpoint resolves identity from request body → latest AOD handoff → `AOS_TENANT_ID` + `AOS_DEMO_ENTITY_ID` env, in that order.

---

## UI surfaces (`/ui/demo/*`)

Nav entry: **"FinOps Demo"** in the top bar (`app/ui/styles.py:91`). Landing page has four cards:

### 1. Pipe Catalog (`/ui/demo/pipe-catalog`)
- **What the operator sees:** A 5-row table — NetSuite vendor master + AP invoices (Workato), Okta SaaS apps + users + assignments (Boomi). Columns: Display Name, Vendor, Source System, Fabric Plane, Modality, Identity Keys.
- **Backend:** `GET /api/aam/demo/pipes` runs MCP discovery live across every vendor in `supported_vendors()`. Same factory call for both — no vendor branching.
- **Proof:** "Same code path across NetSuite (Workato) and Okta (Boomi)." Vendor name is inferred from `lineage_hints` provenance, not hard-coded.

### 2. Semantic Mapping (`/ui/demo/semantic-mapping`)
- **What the operator sees:** 5 cards (one per pipe). Each lists raw vendor fields → AOS concept properties with confidence pills (green ≥0.90, yellow 0.70–0.89, red <0.70).
- **Operator action:** One mid-confidence field needs an explicit click — **NetSuite AP `amount` → `APInvoice.gross_billed_usd`** at 0.78. Rationale displayed: "amount" could mean gross billed or net recognized. Click **Confirm mapping** to push it to 0.99.
- **Backend:** `GET /api/aam/demo/mappings` reads `MAPPINGS` (`app/ingest/mappings.py:62-119`). `POST /api/aam/demo/mappings/approve` stores the approval in memory.

### 3. Identity Resolution (`/ui/demo/identity-resolution`)
- **What the operator sees:** Two panels.
  - **Review queue:** One pending row at 0.71 — LinkedIn Sales Navigator (NetSuite) ↔ LinkedIn Sales Nav. (Okta). Approve / Reject buttons.
  - **Auto-accepted matches:** Up to 80 of the 199 exact-name matches displayed in a table.
- **Operator action:** Click **Approve** → the queue collapses, the match flips to `auto_accepted` (confidence 0.99), and downstream answer count grows by one.
- **Backend:** `GET /api/aam/demo/identity-matches` reads `identity_matches.json`, overlaying any in-memory resolutions. `POST /api/aam/demo/identity-matches/resolve` records the decision.

### 4. Consumer View (`/ui/demo/consumer-view`)
- **What the operator sees:** Question pre-filled. Click **Ask**.
  - **Answer card:** One-sentence summary ("N SaaS subscriptions are under 50% utilization, costing $X/year. Right-sizing recovers ~$Y. M vendor↔app matches held in review."). Table: App, Paid Licenses, Active Users, Utilization %, Annual Cost, Projected Savings.
  - **Matches held in review:** Yellow callout — the system continues producing the answer.
  - **Provenance Drill-Through:** Per row, two outlined buttons — *NetSuite (Workato)* and *Okta (Boomi)*. Click either to load source triples for that vendor record: Property, Value, Source Field, Confidence.
- **Backend:** `GET /api/aam/demo/answer` aggregates over `semantic_triples` for the latest `run_id` per concept (`SaaSApp`, `Assignment`, `APInvoice`). Utilization = active_in_last_30d count ÷ license_seat_count. Projected savings = (seats − max(active × 2, 1)) × per_seat_cost. Annual cost = sum of `gross_billed_usd` over the trailing 12 months relative to the latest invoice's `due_date`. Drill-through hits `/api/aam/demo/provenance` and matches by `source_run_tag LIKE %::{record_key}`.

---

## How the user is supposed to operate it

1. **Ingest.** From a terminal or curl: `POST /api/aam/ingest/demo` with `{"vendors": ["workato","boomi"], "tenant_id": "<uuid>", "entity_id": "<string>"}`. Or rely on AOD handoff / env vars. Response carries `aam_inference_id`, totals per vendor (~33k records, ~210k triples), and the identity pair.
2. **Open `/ui/demo`.** Visit each card in order: Pipe Catalog (confirm 5 pipes), Semantic Mapping (click Confirm mapping on NetSuite `amount`), Identity Resolution (Approve or skip the pending LinkedIn match), Consumer View (click Ask).
3. **Drill in.** From any under-utilized row, click NetSuite or Okta to inspect the underlying triples and verify the field-level provenance (`source_field` shows the raw vendor field for every AOS property).
4. **Optional reset.** `POST /api/aam/demo/reset` clears in-memory mapping approvals and identity decisions (does NOT touch persisted triples) — used by Playwright for clean test state.

---

## Known constraints (from `aam_deferred_work.md`)

- **#3:** Demo ingest writes triples via the direct-PG path that CLAUDE.md flags as tech debt. Migrate to `POST /api/dcl/ingest/production` when DCL ships it.
- **#5:** Sustained Playwright load against the demo (~210k triples landed) intermittently times out the Supabase pooler. Run suites in smaller batches.
- **#6:** `controls-fixes F1` invariant relaxed — demo ingest writes under `source_system != 'AAM'`, so health's `source_system='AAM'` filter excludes them. Test now asserts only `health > 0`.

## Files

- Router: `app/routers/demo.py` (UI + answer + provenance), `app/routers/ingest_demo.py` (orchestrator)
- Mappings: `app/ingest/mappings.py:62-119`
- Fixtures: `tests/fixtures/harness/finops_saas_data/`
- Nav: `app/ui/styles.py:91`
- Playwright: `tests/playwright/aam-demo-experience.spec.js`
