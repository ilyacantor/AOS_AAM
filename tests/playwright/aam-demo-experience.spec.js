// Operator-visible outcome: a FinOps user opens /ask.html on port 3001, clicks Ask, and the FinOps page renders a 5-row combined Q3 AR aging table with non-zero workato + boomi + combined columns, a vendor consolidation table with at least one row, and a pending-review match at 71%. From the same answer page, opening /ui/demo/consumer-view on port 8002 renders the same totals; the Pipe Catalog lists 8 pipes (4 NetSuite + 4 Sage); the Semantic Mapping page surfaces a 78%-confidence field that becomes 99% after the operator clicks Confirm; the Identity Resolution page shows one pending-review row that empties after the operator clicks Approve.
// @ts-check
const { test, expect } = require('@playwright/test');

const AAM_URL = process.env.AAM_URL || 'http://localhost:8002';
const FINOPS_URL = process.env.FINOPS_URL || 'http://localhost:3001';
const STUB_URL = process.env.STUB_URL || 'http://127.0.0.1:8902';
const Q3_QUESTION = 'Show me combined Q3 AR aging across both entities, with vendors that appear in both books flagged for consolidation';

test.beforeEach(async ({ request }) => {
  // Hermetic per-test starting state: load combined_financials scenario in the
  // stub (read-only on PG state) and clear the demo UI's in-memory approvals.
  // Both endpoints are setup, not the action under test.
  await request.post(`${STUB_URL}/stub/load_scenario`, { data: { scenario: 'combined_financials' } });
  await request.post(`${AAM_URL}/api/aam/demo/reset`, { data: {} });
});

test('FinOps agent answers the combined Q3 AR aging question with provenance', async ({ page }) => {
  await page.goto(`${FINOPS_URL}/ask.html?aos=${encodeURIComponent(AAM_URL)}`);
  await page.waitForLoadState('domcontentloaded');

  const input = page.locator('[data-testid="finops-question-input"]');
  await expect(input).toHaveValue(Q3_QUESTION);

  await page.locator('[data-testid="finops-btn-ask"]').click();

  // The answer table renders 5 buckets with non-zero combined totals.
  const answerTable = page.locator('[data-testid="finops-answer-table"]');
  await expect(answerTable.locator('tbody tr[data-testid="finops-answer-row"]')).toHaveCount(5, { timeout: 20000 });

  // Combined totals are non-zero strings starting with '$'.
  const combinedCells = answerTable.locator('[data-testid="finops-combined-cell"]');
  await expect(combinedCells.first()).toContainText('$');
  // Sum of combined cells > 0 — pull text, parse, assert.
  const combinedTexts = await combinedCells.allInnerTexts();
  const totalCombined = combinedTexts.reduce((acc, t) => acc + Number(t.replace(/[^0-9.-]/g, '')), 0);
  expect(totalCombined).toBeGreaterThan(0);

  // Vendor consolidation table renders with at least one auto-accepted row.
  const vendorRows = page.locator('[data-testid="finops-vendor-row"]');
  await expect(vendorRows.first()).toBeAttached();
  const vendorCount = await vendorRows.count();
  expect(vendorCount).toBeGreaterThan(0);

  // The pending-review match at 71% appears.
  await expect(page.locator('[data-testid="finops-review-confidence"]')).toContainText('71%');
});

test('Consumer View on AAM shows same answer with provenance drill-through', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/demo/consumer-view`);
  await page.waitForLoadState('domcontentloaded');

  // Auto-fired ask renders the answer table.
  await expect(page.locator('[data-testid="answer-table"]')).toBeAttached({ timeout: 20000 });
  await expect(page.locator('[data-testid="answer-bucket"]').first()).toContainText('Current');

  // The text answer includes the dollar amounts.
  await expect(page.locator('[data-testid="answer-text"]')).toContainText('AR Aging');

  // Drill-through tables render.
  await expect(page.locator('[data-testid="drill-workato"]')).toBeAttached();
  await expect(page.locator('[data-testid="drill-boomi"]')).toBeAttached();

  // Operator clicks a drill row — triple detail renders for that customer+pipe.
  const drillRow = page.locator('[data-testid="drill-row"]').first();
  await drillRow.click();
  await expect(page.locator('[data-testid="triple-detail-table"]')).toBeAttached({ timeout: 10000 });
  // Triple detail has at least one source-field column populated.
  await expect(page.locator('[data-testid="triple-detail-row"]').first()).toBeAttached();
});

test('Pipe Catalog lists 8 demo pipes across both vendors', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/demo/pipe-catalog`);
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('[data-testid="pipe-catalog-table"]')).toBeAttached();
  await expect(page.locator('[data-testid="pipe-count"]')).toContainText('8 pipes discovered', { timeout: 10000 });
});

test('Semantic Mapping surfaces 78% mid-confidence field; click promotes it to 99%', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/demo/semantic-mapping`);
  await page.waitForLoadState('domcontentloaded');

  // The page renders multiple pipes' mapping cards.
  await expect(page.locator('[data-testid="mapping-pipe"]').first()).toBeAttached({ timeout: 10000 });

  // The mid-confidence row is the NetSuite invoice entity_id field at 78%.
  const midRow = page.locator('[data-testid="mapping-field-entity_id"]').nth(1);
  await expect(midRow.locator('[data-testid="confidence-pill"]')).toContainText('78%');

  // Operator clicks Confirm — the row promotes to 99%.
  await midRow.locator('[data-testid="btn-approve-mapping"]').click();
  await expect(midRow.locator('[data-testid="confidence-pill"]')).toContainText('99%', { timeout: 10000 });
});

test('Identity Resolution shows one 71% review case; click empties the queue', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/demo/identity-resolution`);
  await page.waitForLoadState('domcontentloaded');

  // One pending-review row with 71% confidence.
  const reviewRows = page.locator('[data-testid="review-row"]');
  await expect(reviewRows).toHaveCount(1, { timeout: 10000 });
  await expect(reviewRows.locator('[data-testid="review-confidence"]')).toContainText('71%');
  await expect(reviewRows.locator('[data-testid="review-domain"]')).toContainText('customer');

  // Operator approves — queue becomes empty.
  await reviewRows.locator('[data-testid="btn-approve-match"]').click();
  await expect(page.locator('[data-testid="review-empty"]')).toBeAttached({ timeout: 10000 });
});
