-- Migration: WP12b — fabric_webhook_log
-- Purpose: per-receipt observability for the WP12a' webhook receivers
--          (/api/aam/webhooks/workato, /api/aam/webhooks/boomi).
--          One row per inbound webhook; updated when DCL push completes.
-- Date:    2026-05-15
--
-- Drill-down join keys:
--   - aam_inference_id → semantic_triples.run_id (per-batch triples)
--   - aam_inference_id → resolver_hitl_queue (resolver decisions audit)
--
-- Retention is operator-managed; an out-of-band cleanup job can delete
-- rows older than N days. No automatic TTL in this migration.

CREATE TABLE IF NOT EXISTS fabric_webhook_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    received_utc        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_utc       TIMESTAMPTZ,
    vendor              VARCHAR(32) NOT NULL,
    event_type          VARCHAR(128),
    payload_bytes       INTEGER NOT NULL,
    signature_verified  BOOLEAN NOT NULL,
    signature_truncated VARCHAR(24),
    aam_inference_id    UUID,
    dcl_ingest_id       UUID,
    rows_seen           INTEGER,
    triples_built       INTEGER,
    triples_pushed      INTEGER,
    push_status_code    INTEGER,
    error               TEXT,
    payload_jsonb       JSONB,
    source              VARCHAR(16) NOT NULL DEFAULT 'webhook'
        CHECK (source IN ('webhook', 'manual'))
);

CREATE INDEX IF NOT EXISTS idx_fabric_webhook_log_received
    ON fabric_webhook_log (received_utc DESC);

CREATE INDEX IF NOT EXISTS idx_fabric_webhook_log_vendor_received
    ON fabric_webhook_log (vendor, received_utc DESC);

CREATE INDEX IF NOT EXISTS idx_fabric_webhook_log_aam_inference
    ON fabric_webhook_log (aam_inference_id)
    WHERE aam_inference_id IS NOT NULL;

COMMENT ON TABLE fabric_webhook_log IS
    'WP12b: per-receipt audit for fabric webhook receivers. One row per inbound webhook (or manual entry). Updated when DCL push finalizes. Drill-down joins on aam_inference_id to semantic_triples + resolver_hitl_queue.';

COMMENT ON COLUMN fabric_webhook_log.source IS
    'webhook = received over /api/aam/webhooks/<vendor>; manual = injected via /api/aam/manual-entry';

COMMENT ON COLUMN fabric_webhook_log.signature_truncated IS
    'First 16 chars of the vendor signature header (display only; never the secret).';
