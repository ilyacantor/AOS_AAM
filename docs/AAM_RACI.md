| Category | Capability | AOD | AAM | DCL | AOA | FARM | Architectural Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **MESH (AAM)** |  |  |  |  |  |  | *The Fabric* |
| **Fabric Mgmt** | **Fabric Plane Connection** (The Backbone) |  | **A/R** |  |  | I | *Connects to Planes, not Apps* |
|  | **Preset Config Loading** (6, 8, 9, 11) |  | **A/R** |  |  | I | *Configures Mesh behavior* |
|  | Routing Policy Enforcement |  | A/R |  |  | I | *Enforces "Block Direct Access"* |
| **Adapters** | Adapter Factory Resolution |  | A/R |  |  | I | *Instantiates Strategy (Gateway vs Bus)* |
|  | IPAAS Connection (Workato, MuleSoft) |  | A/R |  |  | I | *Webhooks/Signals modality* |
|  | API Gateway Connection (Kong, Apigee) |  | A/R |  |  | I | *Proxy/REST modality* |
|  | Event Bus Connection (Kafka, EventBridge) |  | A/R |  |  | I | *Streaming Consumer modality* |
|  | Data Warehouse Connection (Snowflake, BigQuery) |  | A/R |  |  | I | *JDBC/Bulk Read modality* |
|  | Pipe Discovery from Plane |  | A/R |  |  | I | *Inventory reusable data pipes* |
|  | Plane Health Check |  | A/R |  |  | I | *Monitor adapter connectivity* |
| **Self-Healing** | **Connection/Fabric Drift Detection** |  | **A/R** |  |  | I | *Detects lost connectivity to Plane* |
|  | Consumer Lag Detection |  | A/R |  |  | I | *Event Bus specific drift* |
|  | Warehouse Suspend Detection |  | A/R |  |  | I | *Warehouse specific drift* |
|  | **Execute Self-Heal** (Restart Consumers) |  | **A/R** |  |  | I | *Restarts Consumers/Reconnects* |
|  | Heal History Logging |  | A/R |  |  | I | *Audit trail of repairs* |
| **Governance** | **PII Redaction** (Edge) |  | **A/R** |  |  | I | *Redacts before data enters DCL* |
|  | Rate Limit Enforcement |  | A/R |  |  | I | *Plane-level rate limiting* |
|  | Auth Policy Enforcement |  | A/R |  |  | I | *Plane-level auth validation* |
|  | Block Direct App Access |  | A/R |  |  | I | *Enforced for non-Scrappy presets* |
| **Pipe Inference** | Fabric Plane Inference |  | A/R |  |  | I | *WHERE pipes live* |
|  | Modality Inference |  | A/R |  |  | I | *HOW pipes are accessed* |
|  | Transport Kind Inference |  | A/R |  |  | I | *API, EVENT_STREAM, TABLE, FILE* |
|  | DeclaredPipe Creation |  | A/R | I |  | I | *Publish to DCL* |
| **Candidate Intake** | Candidate Ingestion | R | A |  |  | I | *Receives from AOD* |
|  | Candidate Triage |  | A/R |  |  | I | *Status management* |
|  | Candidate Match to Pipe |  | A/R |  |  | I | *Link candidate to existing pipe* |
|  | Candidate Defer |  | A/R |  |  | I | *Defer with reason* |
| **Drift Detection** | Schema Hash Computation |  | A/R |  |  | C | *Data structure drift* |
|  | Schema Drift Detection |  | A/R |  |  | C | *Field changes (not connection)* |
|  | Fabric Drift Detection |  | A/R |  |  | I | *Connectivity drift* |
|  | Drift Acknowledgement |  | A/R |  |  | I | *Operator action* |
| **Verification** | Ground Truth Validation | C | C | C |  | **A/R** | *FARM is Test Oracle* |
|  | End-to-End Injection Tests |  | I | I |  | A/R | *Injects at AAM, verifies at DCL* |
| **Export** | DCL Pipe Export |  | A/R | I |  | I | *DeclaredPipes for DCL consumption* |
|  | Pipe Snapshot Export |  | A/R |  |  | I | *Point-in-time export* |
| **Collector Operations** | Collector Registration |  | A/R |  |  | I | *Register collection strategies* |
|  | Collector Run Execution |  | A/R |  |  | I | *Execute with tracking* |
|  | Observation Storage |  | A/R |  |  | I | *Raw collector output* |
