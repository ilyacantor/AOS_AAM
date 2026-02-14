| Category | Capability | AOD | AAM | DCL | AOA | FARM | Status | Architectural Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **MESH (AAM)** |  |  |  |  |  |  |  | *The Fabric* |
| **Fabric Mgmt** | **Fabric Plane Connection** (The Backbone) |  | **A/R** |  |  | I | FUNCTIONAL | *Connects to Planes, not Apps* |
|  | **Fabric Plane Inference Cascade** |  | **A/R** |  |  | I | FUNCTIONAL | *Evidence-based plane routing* |
|  | Routing Policy Enforcement |  | A/R |  |  | I | FUNCTIONAL | *Enforces "Block Direct Access"* |
| **Adapters** | Adapter Factory Resolution |  | A/R |  |  | I | FUNCTIONAL | *Instantiates Strategy (Gateway vs Bus)* |
|  | IPAAS Connection (Workato, MuleSoft) |  | A/R |  |  | I | FUNCTIONAL | *Webhooks/Signals modality* |
|  | API Gateway Connection (Kong, Apigee) |  | A/R |  |  | I | FUNCTIONAL | *Proxy/REST modality* |
|  | Event Bus Connection (Kafka, EventBridge) |  | A/R |  |  | I | FUNCTIONAL | *Streaming Consumer modality* |
|  | Data Warehouse Connection (Snowflake, BigQuery) |  | A/R |  |  | I | FUNCTIONAL | *JDBC/Bulk Read modality* |
|  | Pipe Discovery from Plane |  | A/R |  |  | I | FUNCTIONAL | *Inventory reusable data pipes* |
|  | Plane Health Check |  | A/R |  |  | I | FUNCTIONAL | *Monitor adapter connectivity* |
| **Self-Healing** | **Connection/Fabric Drift Detection** |  | **A/R** |  |  | I | FUNCTIONAL | *Detects lost connectivity to Plane* |
|  | Consumer Lag Detection |  | A/R |  |  | I | FUNCTIONAL | *Event Bus specific drift* |
|  | Warehouse Suspend Detection |  | A/R |  |  | I | FUNCTIONAL | *Warehouse specific drift* |
|  | **Execute Self-Heal** (Restart Consumers) |  | **A/R** |  |  | I | FUNCTIONAL | *Restarts Consumers/Reconnects* |
|  | Heal History Logging |  | A/R |  |  | I | FUNCTIONAL | *Audit trail of repairs* |
| **Governance** | **PII Redaction** (Edge) |  | **A/R** |  |  | I | FUNCTIONAL | *Redacts before data enters DCL* |
|  | Rate Limit Enforcement |  | A/R |  |  | I | FUNCTIONAL | *Plane-level rate limiting* |
|  | Auth Policy Enforcement |  | A/R |  |  | I | FUNCTIONAL | *Plane-level auth validation* |
|  | Block Direct App Access |  | A/R |  |  | I | FUNCTIONAL | *Enforced via fabric plane routing* |
| **Pipe Inference** | Fabric Plane Inference |  | A/R |  |  | I | FUNCTIONAL | *WHERE pipes live* |
|  | Modality Inference |  | A/R |  |  | I | FUNCTIONAL | *HOW pipes are accessed* |
|  | Transport Kind Inference |  | A/R |  |  | I | FUNCTIONAL | *API, EVENT_STREAM, TABLE, FILE* |
|  | DeclaredPipe Creation |  | A/R | I |  | I | FUNCTIONAL | *Publish to DCL* |
| **Candidate Intake** | Candidate Ingestion | R | A |  |  | I | FUNCTIONAL | *Receives from AOD* |
|  | Candidate Triage |  | A/R |  |  | I | FUNCTIONAL | *Status management* |
|  | Candidate Match to Pipe |  | A/R |  |  | I | FUNCTIONAL | *Link candidate to existing pipe* |
|  | Candidate Defer |  | A/R |  |  | I | FUNCTIONAL | *Defer with reason* |
| **Drift Detection** | Schema Hash Computation |  | A/R |  |  | C | FUNCTIONAL | *Data structure drift* |
|  | Schema Drift Detection |  | A/R |  |  | C | FUNCTIONAL | *Field changes (not connection)* |
|  | Fabric Drift Detection |  | A/R |  |  | I | FUNCTIONAL | *Connectivity drift* |
|  | Drift Acknowledgement |  | A/R |  |  | I | FUNCTIONAL | *Operator action* |
| **Verification** | Ground Truth Validation | C | C | C |  | **A/R** | FUNCTIONAL | *FARM is Test Oracle* |
|  | End-to-End Injection Tests |  | I | I |  | A/R | FUNCTIONAL | *Injects at AAM, verifies at DCL* |
| **Export** | DCL Pipe Export |  | A/R | I |  | I | FUNCTIONAL | *DeclaredPipes for DCL consumption* |
|  | Pipe Snapshot Export |  | A/R |  |  | I | FUNCTIONAL | *Point-in-time export* |
| **Collector Operations** | Collector Registration |  | A/R |  |  | I | FUNCTIONAL | *Register collection strategies* |
|  | Collector Run Execution |  | A/R |  |  | I | FUNCTIONAL | *Execute with tracking* |
|  | Adapter Collector (Fabric Discovery) |  | A/R |  |  | I | FUNCTIONAL | *Discover from connected adapters* |
|  | Observation Storage |  | A/R |  |  | I | FUNCTIONAL | *Raw collector output* |
