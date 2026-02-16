"""
AAM (Adaptive API Mesh) - Pydantic Models

Defines the contracts for:
- ConnectionCandidate (input from AOD)
- DeclaredPipe (output to DCL)
- Supporting models and enums
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum
from datetime import datetime
import uuid


# ============================================================================
# ENUMS
# ============================================================================

class FabricPlane(str, Enum):
    """Integration fabric control plane"""
    IPAAS = "IPAAS"
    API_GATEWAY = "API_GATEWAY"
    EVENT_BUS = "EVENT_BUS"
    DATA_WAREHOUSE = "DATA_WAREHOUSE"


class Modality(str, Enum):
    """How AAM interacts with the data source"""
    CONTROL_PLANE = "CONTROL_PLANE"
    DECLARED_INTERFACE = "DECLARED_INTERFACE"
    PASSIVE_SUBSCRIPTION = "PASSIVE_SUBSCRIPTION"
    MINIMAL_TEE = "MINIMAL_TEE"


class TransportKind(str, Enum):
    """Type of data transport"""
    API = "API"
    EVENT_STREAM = "EVENT_STREAM"
    TABLE = "TABLE"
    FILE = "FILE"
    WEBHOOK = "WEBHOOK"


class ChangeSemantics(str, Enum):
    """How data changes over time"""
    SNAPSHOT = "SNAPSHOT"
    APPEND_ONLY = "APPEND_ONLY"
    CDC_UPSERT = "CDC_UPSERT"
    UNKNOWN = "UNKNOWN"


class CandidateStatus(str, Enum):
    """Status of a ConnectionCandidate"""
    NEW = "new"
    TRIAGED = "triaged"
    CONNECTED = "connected"
    DEFERRED = "deferred"


class TeeRequestStatus(str, Enum):
    """Status of a TeeRequest"""
    REQUESTED = "requested"
    APPROVED = "approved"
    VERIFIED = "verified"


class AODActionType(str, Enum):
    """Action type from AOD governance decision"""
    INVENTORY_ONLY = "inventory_only"  # Human review required - blocking findings exist
    PROVISION = "provision"  # Safe for auto-connection


# ============================================================================
# INPUT CONTRACT (FROM AOD)
# ============================================================================

class Finding(BaseModel):
    """A finding from AOD discovery"""
    finding_type: str
    description: str
    severity: Optional[str] = None
    evidence: Optional[str] = None
    is_blocking: bool = Field(default=False, description="Whether this finding blocks auto-provisioning")


class ConnectionCandidate(BaseModel):
    """
    Input from AOD - represents intent + context for a potential connection.
    AAM decides how (or whether) connectivity exists.

    AOD Handoff Fields:
    - execution_allowed: AOD governance decision on whether execution is permitted
    - action_type: "inventory_only" (human review) or "provision" (auto-connect)
    - blocking_findings: List of finding IDs that prevent auto-provisioning
    - connected_via_plane: Fabric plane detected by AOD (routing optimization)
    - aod_run_id: Link back to the discovery run for traceability
    - aod_asset_id: Original AOD asset identifier
    """
    # Core identification
    asset_key: str = Field(..., description="Unique identifier for the asset")
    vendor_name: str = Field(..., description="Vendor/provider name")
    display_name: str = Field(..., description="Human-readable name")
    category: str = Field(..., description="Asset category (CRM, ERP, etc.)")

    # Governance and findings
    governance_status: Optional[str] = Field(None, description="Governance classification (governed, shadow_it, zombie)")
    findings: list[Finding] = Field(default_factory=list, description="Discovery findings")
    sor_tagging: Optional[str] = Field(None, description="System of Record tagging")
    evidence_refs: list[str] = Field(default_factory=list, description="References to evidence")
    signals_summary: Optional[str] = Field(None, description="Summary of discovery signals")

    # Connection hints
    known_endpoints: list[str] = Field(default_factory=list, description="Known API endpoints")
    preferred_modality: Optional[Modality] = Field(None, description="Preferred connection modality")
    priority_score: Optional[float] = Field(None, ge=0, le=100, description="Priority score 0-100")

    # === AOD HANDOFF FIELDS ===
    execution_allowed: bool = Field(
        default=True,
        description="AOD governance decision - False if blocking findings exist"
    )
    action_type: AODActionType = Field(
        default=AODActionType.PROVISION,
        description="AOD action type: inventory_only (human review) or provision (auto-connect)"
    )
    blocking_findings: list[str] = Field(
        default_factory=list,
        description="List of finding IDs/types that block auto-provisioning"
    )
    connected_via_plane: Optional[FabricPlane] = Field(
        None,
        description="Fabric plane detected by AOD (routing hint for AAM)"
    )
    aod_run_id: Optional[str] = Field(
        None,
        description="AOD discovery run ID for traceability"
    )
    aod_asset_id: Optional[str] = Field(
        None,
        description="Original AOD asset identifier"
    )


class ConnectionCandidateCreate(ConnectionCandidate):
    """Request model for creating a new candidate"""
    pass


class ConnectionCandidateResponse(ConnectionCandidate):
    """Response model with database fields"""
    candidate_id: str
    status: CandidateStatus
    matched_pipe_id: Optional[str] = None
    match_score: Optional[float] = None
    match_reason: Optional[str] = None
    deferred_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ============================================================================
# AOD HANDOFF MODELS
# ============================================================================

class AODHandoffCandidate(ConnectionCandidate):
    """
    Candidate format specifically from AOD handoff.
    Includes all AOD-specific fields with stricter validation.
    """
    # AOD fields are required in handoff context
    aod_run_id: str = Field(..., description="AOD discovery run ID (required for handoff)")
    aod_asset_id: str = Field(..., description="Original AOD asset ID (required for handoff)")


class FabricPlaneSummary(BaseModel):
    """Summary of a fabric plane from AOD"""
    plane_type: str
    vendor: str
    is_healthy: bool = True
    source: str = "aod"


class SORDeclaration(BaseModel):
    """System of Record declaration from Farm via AOD.

    Farm declares which applications are the authoritative data source
    for specific business domains.  AOD passes these through so AAM
    knows which endpoints are SORs and can treat their data as
    authoritative.
    """
    domain: str = Field(..., description="Business domain (CRM, ERP, HR, FINANCE, IDENTITY, CMDB, etc.)")
    vendor: str = Field(..., description="Vendor name (e.g., Salesforce, SAP)")
    category: str = Field("", description="Asset category mapping (e.g., saas, erp, idp, itsm)")
    confidence: str = Field("high", description="Confidence level: high, medium, low")
    source: str = Field("farm", description="Who declared this SOR (farm, computed, manual)")


class AODHandoffRequest(BaseModel):
    """Batch handoff request from AOD"""
    run_id: str = Field(..., description="AOD discovery run ID")
    snapshot_name: Optional[str] = Field(None, description="Human-readable snapshot name (e.g., Networks-5OS6)")
    candidates: list[AODHandoffCandidate] = Field(..., description="Candidates to hand off")
    fabric_planes: list[FabricPlaneSummary] = Field(default_factory=list, description="Detected fabric planes")
    sors: list[SORDeclaration] = Field(default_factory=list, description="Authoritative SOR declarations from Farm")
    policy_version: Optional[str] = Field(None, description="Version of governance policy applied")
    handoff_timestamp: datetime = Field(default_factory=datetime.utcnow)


class AODHandoffResponse(BaseModel):
    """Response to AOD handoff request"""
    run_id: str
    candidates_received: int
    candidates_accepted: int
    candidates_rejected: int
    rejected_reasons: list[dict] = Field(default_factory=list)
    handoff_id: str
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    plane_store_errors: list = Field(default_factory=list)
    sor_store_errors: list = Field(default_factory=list)


class AODPolicyManifest(BaseModel):
    """Governance policy manifest from AOD"""
    policy_version: str = Field(..., description="Version identifier for the policy")
    governance_rules: list[dict] = Field(default_factory=list, description="Governance rules to apply")
    blocking_finding_types: list[str] = Field(
        default_factory=list,
        description="Finding types that should block auto-provisioning"
    )
    fabric_plane_routing: dict = Field(
        default_factory=dict,
        description="Category -> FabricPlane routing rules"
    )
    auto_provision_categories: list[str] = Field(
        default_factory=list,
        description="Categories allowed for auto-provisioning"
    )
    require_human_review: list[str] = Field(
        default_factory=list,
        description="Categories requiring human review"
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# OUTPUT CONTRACT (TO DCL)
# ============================================================================

class Provenance(BaseModel):
    """Origin and lineage information for a pipe"""
    discovered_by: str = Field(..., description="Collector that discovered this pipe")
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    lineage_hints: list[str] = Field(default_factory=list, description="Hints about data lineage")


class SchemaInfo(BaseModel):
    """Schema information for a pipe (optional)"""
    schema_hash: str = Field(..., description="Hash of the normalized schema")
    schema_ref: Optional[str] = Field(None, description="Reference to schema definition")
    schema_version: Optional[str] = Field(None, description="Schema version identifier")


class AccessInfo(BaseModel):
    """Access information for a pipe (optional, NO SECRETS)"""
    auth_ref: Optional[str] = Field(None, description="Reference to auth config (NO SECRETS)")
    access_level: Optional[str] = Field(None, description="Access level description")


class DeclaredPipe(BaseModel):
    """
    AAM's ONLY product - a registry of declared data pipes.
    DCL consumes these to unify meaning.
    """
    pipe_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique pipe identifier")
    display_name: str = Field(..., description="Human-readable pipe name")
    fabric_plane: FabricPlane = Field(..., description="Integration fabric control plane")
    modality: Modality = Field(..., description="How AAM interacts with this pipe")
    source_system: str = Field(..., description="Source system identifier")
    transport_kind: TransportKind = Field(..., description="Type of data transport")
    endpoint_ref: dict = Field(default_factory=dict, description="Opaque reference to endpoint")
    entity_scope: list[str] = Field(default_factory=list, description="Entities covered by this pipe")
    identity_keys: list[str] = Field(default_factory=list, description="Keys that identify records")
    change_semantics: ChangeSemantics = Field(ChangeSemantics.UNKNOWN, description="How data changes")
    provenance: Provenance = Field(..., description="Origin and lineage")
    owner_signals: list[str] = Field(default_factory=list, description="Ownership signals")
    trust_labels: list[str] = Field(default_factory=list, description="Trust and quality labels")
    schema_info: Optional[SchemaInfo] = Field(None, description="Schema information")
    freshness: Optional[str] = Field(None, description="Data freshness indicator")
    access: Optional[AccessInfo] = Field(None, description="Access information (NO SECRETS)")


class DeclaredPipeCreate(BaseModel):
    """Request model for manually declaring a pipe"""
    display_name: str
    fabric_plane: FabricPlane
    modality: Modality
    source_system: str
    transport_kind: TransportKind
    endpoint_ref: dict = Field(default_factory=dict)
    entity_scope: list[str] = Field(default_factory=list)
    identity_keys: list[str] = Field(default_factory=list)
    change_semantics: ChangeSemantics = ChangeSemantics.UNKNOWN
    owner_signals: list[str] = Field(default_factory=list)
    trust_labels: list[str] = Field(default_factory=list)


class DeclaredPipeResponse(DeclaredPipe):
    """Response model with version info"""
    version: int
    created_at: datetime
    updated_at: datetime


# ============================================================================
# PIPE VERSIONING AND DRIFT
# ============================================================================

class PipeVersion(BaseModel):
    """A version of a declared pipe"""
    version_id: str
    pipe_id: str
    version: int
    schema_hash: Optional[str]
    payload: dict  # Full DeclaredPipe as dict
    created_at: datetime


class DriftEvent(BaseModel):
    """Records when a pipe's schema or behavior drifts"""
    drift_id: str
    pipe_id: str
    drift_type: Literal["schema", "freshness", "contract"]
    old_value: Optional[str]
    new_value: Optional[str]
    details: Optional[dict] = None
    detected_at: datetime


class DriftEventResponse(DriftEvent):
    """Response model for drift events"""
    pass


# ============================================================================
# COLLECTOR MODELS
# ============================================================================

class CollectorInfo(BaseModel):
    """Information about a collector"""
    collector_id: str
    name: str
    collector_type: str  # mock, ipaas, api_gateway, data_warehouse
    description: Optional[str] = None
    enabled: bool = True
    last_run: Optional[datetime] = None


class Observation(BaseModel):
    """
    Raw observation from a collector.
    Gets processed by inference engine into DeclaredPipes.
    """
    observation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    collector_id: str
    candidate_id: Optional[str] = None
    observed_at: datetime = Field(default_factory=datetime.utcnow)
    source_system: str
    endpoint_info: dict
    entity_hints: list[str] = Field(default_factory=list)
    schema_sample: Optional[dict] = None
    metadata: dict = Field(default_factory=dict)


# ============================================================================
# TEE REQUEST (MINIMAL TEE)
# ============================================================================

class TeeRequest(BaseModel):
    """
    Request to create a minimal tee for data observation.
    AAM generates these artifacts ONLY - does NOT modify client systems.
    """
    tee_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pipe_id: str
    target_system: str
    tee_type: str  # e.g., "api_proxy", "event_tap", "query_log"
    configuration: dict = Field(default_factory=dict)
    status: TeeRequestStatus = TeeRequestStatus.REQUESTED
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    approved_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None


# ============================================================================
# API RESPONSE WRAPPERS
# ============================================================================

class CandidateIntakeResponse(BaseModel):
    """Response from candidate intake"""
    candidate_id: str
    status: CandidateStatus
    message: str


class InferenceResult(BaseModel):
    """Result of running inference on a candidate"""
    candidate_id: str
    pipes_created: int
    pipes: list[DeclaredPipeResponse]
    observations_processed: int


class ExportResponse(BaseModel):
    """Export format for DCL consumption"""
    export_version: str = "1.0"
    exported_at: datetime = Field(default_factory=datetime.utcnow)
    pipe_count: int
    pipes: list[DeclaredPipe]


# ============================================================================
# TOPOLOGY / GRAPH MODELS
# ============================================================================

class NodeType(str, Enum):
    """Types of nodes in the topology graph"""
    FABRIC_PLANE = "fabric_plane"
    SOURCE_SYSTEM = "source_system"
    PIPE = "pipe"
    CANDIDATE = "candidate"


class EdgeType(str, Enum):
    """Types of edges in the topology graph"""
    PIPE_IN_PLANE = "pipe_in_plane"           # Pipe belongs to fabric plane
    PIPE_FROM_SOURCE = "pipe_from_source"     # Pipe originates from source
    CANDIDATE_TO_PIPE = "candidate_to_pipe"   # Candidate matched to pipe
    CANDIDATE_FOR_SOURCE = "candidate_for_source"  # Candidate targets source


class TopologyNode(BaseModel):
    """A node in the topology graph"""
    id: str = Field(..., description="Unique node identifier")
    type: NodeType = Field(..., description="Node type")
    label: str = Field(..., description="Display label")
    metadata: dict = Field(default_factory=dict, description="Additional node properties")


class TopologyEdge(BaseModel):
    """An edge connecting two nodes in the topology"""
    id: str = Field(..., description="Unique edge identifier")
    source: str = Field(..., description="Source node ID")
    target: str = Field(..., description="Target node ID")
    type: EdgeType = Field(..., description="Edge type")
    metadata: dict = Field(default_factory=dict, description="Additional edge properties")


class TopologyGraph(BaseModel):
    """Complete topology graph for visualization"""
    nodes: list[TopologyNode] = Field(default_factory=list)
    edges: list[TopologyEdge] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict, description="Graph statistics")
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class TopologyStats(BaseModel):
    """Statistics about the topology"""
    total_nodes: int = 0
    total_edges: int = 0
    nodes_by_type: dict = Field(default_factory=dict)
    edges_by_type: dict = Field(default_factory=dict)
    fabric_planes: list[str] = Field(default_factory=list)
    source_systems: list[str] = Field(default_factory=list)
    connected_candidates: int = 0
    unconnected_candidates: int = 0
    pipes_with_drift: int = 0


# ============================================================================
# RUNNER / JOB MANIFEST MODELS
# ============================================================================

class RunnerJobStatus(str, Enum):
    """State machine for runner jobs"""
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    PUSHING = "pushing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class SourceSpec(BaseModel):
    """What the Runner should extract — connection info + query"""
    pipe_id: str
    system: str                                         # vendor name
    adapter: str                                        # rest_api | jdbc | kafka | ipaas | webhook
    category: Optional[str] = None                      # crm | erp | itsm | support | etc.
    endpoint_ref: dict = Field(default_factory=dict)    # opaque connection info
    credentials_ref: Optional[str] = None               # vault://aam/secrets/xxx — reference only, NEVER plaintext
    query: Optional[str] = None                         # extraction query/filter


class TransformSpec(BaseModel):
    """How to normalize source fields → DCL semantic fields (Option A)"""
    schema_map: dict = Field(default_factory=dict)      # source_field → {target, unit, scale, dimension}
    grain: Optional[str] = None                         # quarter | month | day
    period_field: Optional[str] = None
    period_format: Optional[str] = None                 # YYYY-Qq, YYYY-MM, etc.


class TargetSpec(BaseModel):
    """Where the Runner should push — DCL ingestion endpoint"""
    dcl_url: str = "/api/dcl/ingest"                    # POST endpoint
    auth_token_ref: Optional[str] = None                # vault reference — NEVER plaintext
    tenant_id: Optional[str] = None
    snapshot_name: Optional[str] = None


class RunLimits(BaseModel):
    """Safety rails so a bad source can't blow up the Runner or flood DCL"""
    max_rows: int = 100_000
    timeout_seconds: int = 300
    retry_count: int = 2


class JobManifest(BaseModel):
    """Immutable instruction packet dispatched from AAM to a Runner.

    The manifest is frozen in the runner_jobs table on dispatch.
    Credentials are vault references only — the Runner resolves at runtime.
    """
    manifest_version: str = "1.0"
    run_id: str                                         # generated by AAM
    source: SourceSpec
    transform: Optional[TransformSpec] = None
    target: TargetSpec = TargetSpec()
    provenance: dict = Field(default_factory=dict)      # run_timestamp, triggered_by
    limits: RunLimits = RunLimits()
    farm_verification: bool = False


# ============================================================================
# DCL INGESTION MODELS
# ============================================================================

class DCLIngestRequest(BaseModel):
    """Payload shape for POST /api/dcl/ingest — flat body per DCL contract.

    Headers carry provenance (x-run-id, x-pipe-id, x-schema-hash, x-api-key).
    Body carries the data + context needed for storage.
    """
    source_system: str
    tenant_id: Optional[str] = None
    snapshot_name: Optional[str] = None
    run_timestamp: str
    rows: list[dict] = Field(default_factory=list)


class DCLIngestResponse(BaseModel):
    """Response from DCL after ingesting a payload"""
    status: str = "ingested"
    ingest_id: str
    run_id: str
    rows_stored: int
    schema_hash: Optional[str] = None
    schema_drift_detected: bool = False


class RunnerDispatchRequest(BaseModel):
    """Request body for POST /api/runners/dispatch"""
    pipe_id: str
    trigger: str = "manual"


class RunnerBatchDispatchRequest(BaseModel):
    """Request body for POST /api/runners/dispatch-batch"""
    pipe_ids: list[str] = Field(default_factory=list)
    trigger: str = "manual"


class RunnerCallbackRequest(BaseModel):
    """Request body for PUT /api/runners/callback/{run_id} — Runner reports status"""
    status: RunnerJobStatus
    rows_transferred: Optional[int] = None
    error_message: Optional[str] = None
