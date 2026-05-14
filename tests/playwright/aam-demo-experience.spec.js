// Operator-visible outcome: a FinOps user opens /ask.html on port 3001, clicks Ask, and the FinOps page renders the SaaS-utilization answer with at least 10 ranked subscription rows, a non-zero total projected savings amount in $ and at least one pending-review match in the resolver HITL band [65%, 90%]. From AAM directly: /ui/demo/consumer-view renders the same answer with both NetSuite and Okta drill buttons that load triple-detail rows; /ui/demo/pipe-catalog lists 5 pipes (2 NetSuite + 3 Okta); /ui/demo/semantic-mapping shows the NetSuite AP-invoice "amount" field at 78% confidence that flips to 99% after Confirm; /ui/demo/identity-resolution shows one pending-review row whose confidence pill matches the live resolver score from /api/aam/demo/identity-matches and empties after Approve.
// @ts-check
const { test, expect } = require('@playwright/test');

const AAM_URL = process.env.AAM_URL || 'http://localhost:8002';
const FINOPS_URL = process.env.FINOPS_URL || 'http://localhost:3001';
const STUB_URL = process.env.STUB_URL || 'http://127.0.0.1:8902';
const Q = 'Show me SaaS subscriptions where actual utilization is below 50% of paid licenses, ranked by potential annual savings';

// One-shot setup: load the FinOps scenario in the ipaas_stub and drive the
// Demo Ingest button on /ui/controls so the resolver populates HITL rows +
// semantic_triples.canonical_id. The downstream specs read from those
// surfaces — no static fixtures, no test-only endpoints (B5).
test.beforeAll(async ({ browser, request }) => {
  await request.post(`${STUB_URL}/stub/load_scenario`, { data: { scenario: 'finops_saas_spending' } });
  const page = await browser.newPage();
  await page.goto(`${AAM_URL}/ui/controls`);
  await page.waitForLoadState('domcontentloaded');
  const button = page.locator('[data-testid="btn-run-demo-ingest"]');
  await button.click();
  await expect(page.locator('[data-testid="demo-ingest-status"]')).toHaveText('Complete', { timeout: 60000 });
  await page.close();
});

test.beforeEach(async ({ request }) => {
  await request.post(`${STUB_URL}/stub/load_scenario`, { data: { scenario: 'finops_saas_spending' } });
});

test('FinOps agent answers the SaaS utilization question with savings ranking', async ({ page }) => {
  await page.goto(`${FINOPS_URL}/ask.html?aos=${encodeURIComponent(AAM_URL)}`);
  await page.waitForLoadState('domcontentloaded');

  await expect(page.locator('[data-testid="finops-question-input"]')).toHaveValue(Q);
  await page.locator('[data-testid="finops-btn-ask"]').click();

  // At least 10 ranked subscription rows render (the dataset has 25 under-used).
  const rows = page.locator('[data-testid="finops-answer-row"]');
  await expect(rows.nth(9)).toBeAttached({ timeout: 20000 });

  // Top row shows non-trivial savings ($ + comma).
  await expect(rows.first().locator('[data-testid="finops-savings"]')).toContainText('$');
  await expect(rows.first().locator('[data-testid="finops-savings"]')).toContainText(',');

  // Total savings non-empty ($) — pulled from the totals bar.
  await expect(page.locator('[data-testid="finops-total-savings"]')).toContainText('$');
  const savingsText = await page.locator('[data-testid="finops-total-savings"]').textContent();
  expect(Number((savingsText || '').replace(/[^0-9.-]/g, ''))).toBeGreaterThan(100000);

  // Pending-review match — confidence pulled from the live resolver via
  // /api/aam/demo/identity-matches (B10 ground truth at runtime, not hardcoded).
  const matchesRes = await page.request.get(`${AAM_URL}/api/aam/demo/identity-matches`);
  const matchesBody = await matchesRes.json();
  const pendingItems = (matchesBody.matches || []).filter(m => m.review_status === 'pending_review');
  expect(pendingItems.length).toBeGreaterThan(0);
  const expectedPct = Math.round(pendingItems[0].confidence * 100);
  expect(expectedPct).toBeGreaterThanOrEqual(65);
  expect(expectedPct).toBeLessThan(90);
  await expect(page.locator('[data-testid="finops-review-confidence"]')).toContainText(`${expectedPct}%`);
});

test('Consumer View on AAM renders the same answer with drill-through to source triples', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/demo/consumer-view`);
  await page.waitForLoadState('domcontentloaded');

  // Answer table renders at least 10 rows.
  await expect(page.locator('[data-testid="answer-table"]')).toBeAttached({ timeout: 20000 });
  await expect(page.locator('[data-testid="answer-row"]').nth(9)).toBeAttached();

  // Answer text mentions SaaS.
  await expect(page.locator('[data-testid="answer-text"]')).toContainText('SaaS');

  // Drill table renders both NetSuite and Okta buttons per subscription row.
  const netsuiteButtons = page.locator('[data-testid="btn-drill-netsuite"]');
  const oktaButtons = page.locator('[data-testid="btn-drill-okta"]');
  await expect(netsuiteButtons.first()).toBeAttached({ timeout: 10000 });
  await expect(oktaButtons.first()).toBeAttached({ timeout: 10000 });

  // Operator clicks the NetSuite drill on the top row — triple detail renders.
  // Use waitForResponse to wait for the actual provenance fetch to complete.
  const provenancePromise = page.waitForResponse(r => r.url().includes('/api/aam/demo/provenance'));
  await netsuiteButtons.first().click();
  const resp = await provenancePromise;
  expect(resp.status()).toBe(200);
  await expect(page.locator('[data-testid="triple-detail-table"]')).toBeAttached({ timeout: 15000 });
  await expect(page.locator('[data-testid="triple-detail-row"]').first()).toBeAttached();
  await expect(page.locator('[data-testid="triple-detail-title"]')).toContainText('NetSuite');
});

test('Pipe Catalog lists 5 demo pipes across NetSuite + Okta', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/demo/pipe-catalog`);
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('[data-testid="pipe-catalog-table"]')).toBeAttached();
  await expect(page.locator('[data-testid="pipe-count"]')).toContainText('5 pipes discovered', { timeout: 10000 });
});

test('Semantic Mapping surfaces 78% mid-confidence field; click promotes it to 99%', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/demo/semantic-mapping`);
  await page.waitForLoadState('domcontentloaded');

  await expect(page.locator('[data-testid="mapping-pipe"]').first()).toBeAttached({ timeout: 10000 });

  // The mid-confidence row is on the NetSuite AP-invoice "amount" field.
  const midRow = page.locator('[data-testid="mapping-field-amount"]');
  await expect(midRow.locator('[data-testid="confidence-pill"]').first()).toContainText('78%');

  await midRow.locator('[data-testid="btn-approve-mapping"]').first().click();
  await expect(midRow.locator('[data-testid="confidence-pill"]').first()).toContainText('99%', { timeout: 10000 });
});

test('Identity Resolution shows the live resolver HITL row; click empties the queue', async ({ page }) => {
  // Ground truth from /api/aam/demo/identity-matches at test time — the
  // resolver writes the pending row during the prior ingest run, and the
  // confidence is whatever the algorithm actually scored.
  const matchesRes = await page.request.get(`${AAM_URL}/api/aam/demo/identity-matches`);
  const matchesBody = await matchesRes.json();
  const pending = (matchesBody.matches || []).filter(m => m.review_status === 'pending_review');
  expect(pending.length).toBeGreaterThan(0);
  const expectedConfidence = pending[0].confidence;
  const expectedPct = Math.round(expectedConfidence * 100);

  await page.goto(`${AAM_URL}/ui/demo/identity-resolution`);
  await page.waitForLoadState('domcontentloaded');

  const reviewRows = page.locator('[data-testid="review-row"]');
  await expect(reviewRows.first()).toBeAttached({ timeout: 10000 });
  await expect(reviewRows.first().locator('[data-testid="review-confidence"]')).toContainText(`${expectedPct}%`);
  await expect(reviewRows.first().locator('[data-testid="review-domain"]')).toContainText('saas_subscription');

  await reviewRows.first().locator('[data-testid="btn-approve-match"]').click();
  // The row disappears (or the empty marker appears if it was the last one).
  await expect(async () => {
    const after = await page.request.get(`${AAM_URL}/api/aam/demo/identity-matches`);
    const body = await after.json();
    const stillPending = (body.matches || []).filter(m => m.review_status === 'pending_review');
    expect(stillPending.length).toBeLessThan(pending.length);
  }).toPass({ timeout: 10000 });
});
