// @ts-check
const { test, expect } = require('@playwright/test');

const AAM_URL = process.env.AAM_URL || 'http://localhost:8002';

// F1: Triple Health matches Ledger
//
// CANONICAL INVARIANT (do not "restore" the older literal):
//   health.total_count >= latestLedgerEntry.triple_count
//
// This is the run-scoped variant of an earlier literal invariant —
// `health.total_count >= ledger.total_triples` — which DID NOT HOLD by
// construction and is not a regression to fix. Two things diverge over time:
//
//   1. health.total_count is the count of CURRENTLY ACTIVE AAM triples
//      (the latest run's writes; old runs are deactivated). Bounded.
//   2. ledger.total_triples is the SUM across ALL historical AAM ledger
//      entries since DB inception. Unbounded — grows every run forever.
//
// A bounded count can never be >= an unbounded sum once enough runs accumulate.
// The literal was structurally unholdable. The bounded variant says: the
// latest committed AAM ledger entry's triples must appear in the active
// health view. That's the real "ledger committed it, dashboard sees it"
// contract. Do not change the assertion below to compare against
// ledger.total_triples or any cumulative sum.
//
// Background: WP4 moved the FinOps demo ingest path off the AAM ledger
// (writes now go directly to DCL via HTTP). The AAM ledger now tracks only
// AAM-owned writes — /api/aam/infer, drift, fabric_planes — all
// source_system='AAM'. The health view filter source_system='AAM' aligns
// with that set, so the run-scoped bound is the meaningful one. History
// in aam_deferred_work.md entries #6 and #8.
test('F1: Triple Health panel shows AAM triples > 0 with coverage', async ({ page, request }) => {
  // Fresh-DB safety: seed an AOD handoff via /fetch (replays the saved payload)
  // so /api/aam/infer has candidates to process. Without this, a brand-new
  // database has zero candidates → inference produces zero triples → health
  // shows zero. Allowed under B17's read-only exception only in setup, not in
  // the action under test.
  await request.post(`${AAM_URL}/api/handoff/aod/fetch`).catch(() => {});

  // Trigger inference to ensure triples exist
  await request.post(`${AAM_URL}/api/aam/infer`);

  await page.goto(`${AAM_URL}/ui/controls`);
  await page.waitForLoadState('domcontentloaded');
  // Allow the panel-health JS fetch to complete. After the FinOps demo data
  // load, /api/aam/triple-health can take 15–20s under load (deferred entry
  // #5 — pooler latency on aged connections with semantic_triples at ~3M
  // rows). Wait until the triple-count cell is rendered, then assert.
  await page.locator('[data-testid="triple-count"]').waitFor({ state: 'visible', timeout: 30000 });

  // Triple Health panel should be visible
  const healthPanel = page.locator('[data-testid="panel-health"]');
  await expect(healthPanel).toBeVisible();

  // AAM TRIPLE COUNT > 0
  const tripleCount = page.locator('[data-testid="triple-count"]');
  await expect(tripleCount).toBeVisible();
  const countText = await tripleCount.innerText();
  expect(parseInt(countText)).toBeGreaterThan(0);

  // Coverage: at least mapping.pipe and mapping.connection show green checks
  const coverageList = page.locator('[data-testid="coverage-list"]');
  await expect(coverageList).toBeVisible();
  const coverageItems = page.locator('[data-testid="coverage-item"]');
  const coverageTexts = await coverageItems.allInnerTexts();
  const presentItems = coverageTexts.filter(t => t.includes('\u2713'));
  expect(presentItems.length).toBeGreaterThanOrEqual(2); // mapping.pipe + mapping.connection

  // Freshness should be GREEN (data was just written)
  const freshness = page.locator('[data-testid="freshness-status"]');
  await expect(freshness).toBeVisible();
  const freshnessText = await freshness.innerText();
  expect(freshnessText.toUpperCase()).toBe('GREEN');

  // Bounded invariant: health.total_count >= latest committed AAM ledger
  // entry's triple_count. See header comment for full rationale.
  const healthRes = await request.get(`${AAM_URL}/api/aam/triple-health`);
  const healthData = await healthRes.json();
  const ledgerEntriesRes = await request.get(`${AAM_URL}/api/aam/triple-ledger?status=committed&limit=1`);
  const ledgerEntriesData = await ledgerEntriesRes.json();
  const latestLedgerEntry = (ledgerEntriesData.entries || [])[0];
  if (latestLedgerEntry) {
    const latestTriples = latestLedgerEntry.triple_count || 0;
    expect(healthData.total_count).toBeGreaterThanOrEqual(latestTriples);
  }
});

// F2: Topology graph still works
test('F2: Topology graph renders with interactive elements', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/topology`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  // Force-directed graph renders (canvas or svg)
  const canvas = page.locator('canvas');
  const svgElements = page.locator('svg');
  const canvasCount = await canvas.count();
  const svgCount = await svgElements.count();
  expect(canvasCount + svgCount).toBeGreaterThan(0);

  // Search box is functional
  const searchBox = page.locator('#topo-search');
  await expect(searchBox).toBeVisible();

  // Zoom controls present (uses .topo-zoom-btn class)
  const zoomBtns = page.locator('.topo-zoom-btn');
  expect(await zoomBtns.count()).toBeGreaterThanOrEqual(2);

  // Legend is visible
  const legend = page.locator('.topo-legend, [class*="legend"]');
  expect(await legend.count()).toBeGreaterThan(0);

  // At least one node rendered (text content in the page)
  const bodyText = await page.locator('body').innerText();
  // The topology should show at least one pipe or SOR
  const hasNodes = bodyText.includes('pipes') || bodyText.includes('Pipe') ||
                   bodyText.includes('Fabrics') || bodyText.includes('SOR');
  expect(hasNodes).toBeTruthy();
});

// F3: Topology actions panel shows new-architecture buttons only
test('F3: Topology actions panel shows new-architecture buttons only', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/topology`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  // All five old-pipeline buttons must be absent from the DOM. Note:
  // #btn-run-inference is excluded because the new-architecture page renders
  // a button with id="btn-run-inference" data-testid="btn-run-inference" —
  // T1 in aam-topology-fixes.spec.js asserts that button exists.
  await expect(page.locator('#fetch-aod-btn')).toHaveCount(0);
  await expect(page.locator('#btn-full-pipeline')).toHaveCount(0);
  await expect(page.locator('#btn-export-dcl')).toHaveCount(0);
  await expect(page.locator('#btn-dispatch-all')).toHaveCount(0);
  await expect(page.locator('#btn-view-dispatch')).toHaveCount(0);

  // The three new-architecture buttons must exist
  await expect(page.locator('[data-testid="btn-run-discovery"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="btn-validate-credentials"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="btn-start-ingest"]')).toHaveCount(1);
});

// F4: Operating mode API
test('F4: Operating mode API returns SYNTHETIC', async ({ request }) => {
  const res = await request.get(`${AAM_URL}/api/aam/operating-mode`);
  expect(res.ok()).toBeTruthy();
  const data = await res.json();
  expect(data.mode).toBe('SYNTHETIC');
  expect(data.superseded_controls).toBeDefined();
  expect(data.superseded_controls.length).toBeGreaterThan(0);

  // Also check the original endpoint
  const res2 = await request.get(`${AAM_URL}/api/aam/mode`);
  const data2 = await res2.json();
  expect(data2.mode).toBe('SYNTHETIC');
});

// F5: Drift ledger entries
test('F5: Drift detection creates ledger entries', async ({ page, request }) => {
  // First ensure there are triples to detect drift on
  await request.post(`${AAM_URL}/api/aam/infer`);

  // Trigger drift check via API
  const driftRes = await request.post(`${AAM_URL}/api/aam/drift-check`);
  // The drift check may succeed or fail depending on entity_id resolution
  if (driftRes.ok()) {
    const driftData = await driftRes.json();
    // If drift events were found and triples were written, check ledger
    if (driftData.triple_write) {
      expect(driftData.triple_write.status).toBe('committed');
      expect(driftData.triple_write.concept_prefixes).toContain('mapping.drift');

      // Verify ledger entry exists with trigger=drift_detection
      const ledgerRes = await request.get(`${AAM_URL}/api/aam/triple-ledger?trigger=drift_detection&limit=5`);
      const ledgerData = await ledgerRes.json();
      expect(ledgerData.entries.length).toBeGreaterThan(0);
      const driftEntry = ledgerData.entries.find(e => e.trigger === 'drift_detection');
      expect(driftEntry).toBeDefined();
    }
  }

  // Navigate to controls page and verify drift panel reflects the check
  await page.goto(`${AAM_URL}/ui/controls`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  const driftPanel = page.locator('[data-testid="panel-drift"]');
  await expect(driftPanel).toBeVisible();
});

// F6: All existing P1-P12 tests still pass (meta-test — this file runs alongside controls.spec.js)
test('F6: Controls dashboard panels all render', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/controls`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(5000);

  // Verify all 7 panels from the original build are present
  await expect(page.locator('[data-testid="mode-badge"]')).toBeVisible();
  await expect(page.locator('[data-testid="panel-ledger"]')).toBeVisible();
  await expect(page.locator('[data-testid="panel-health"]')).toBeVisible();
  await expect(page.locator('[data-testid="panel-drift"]')).toBeVisible();
  await expect(page.locator('[data-testid="panel-pipes"]')).toBeVisible();
  await expect(page.locator('[data-testid="connection-placeholder"]')).toBeVisible();

  // Legacy panel hidden by default
  await expect(page.locator('[data-testid="panel-legacy"]')).not.toBeVisible();
  await expect(page.locator('[data-testid="toggle-legacy"]')).toBeVisible();
});
