// Operator-visible outcome: clicking "trigger demo run" on the workato (then boomi) vendor card on /ui/fabrics produces a new receipt row within 10s with signature_verified=ok and push HTTP 201; clicking that row opens /ui/fabrics/receipt/<id> with four sections — webhook payload, resolver decisions, triples built, DCL push outcome — and at least one triple row that displays all five provenance fields (source_system, source_field, pipe_id, fabric_plane, confidence_score).

import { test, expect, Page } from '@playwright/test';

async function receiptCount(page: Page) {
  return page.locator('[data-testid="receipts-table"] tbody tr').count();
}

async function triggerAndDrill(page: Page, vendor: 'workato' | 'boomi') {
  await page.goto('/ui/fabrics');
  // Wait until the vendor card has rendered (auto-loaded via fetch on mount).
  await expect(page.locator(`[data-testid="vendor-card-${vendor}"]`)).toHaveText(new RegExp(vendor));

  const beforeCount = await receiptCount(page);

  await page.locator(`[data-testid="trigger-${vendor}"]`).click();

  // New row appears within 10s — count must strictly increase relative to before.
  await expect.poll(
    async () => await receiptCount(page),
    { timeout: 15_000, intervals: [1000, 1500, 2000] },
  ).toBeGreaterThan(beforeCount);

  // Top row is the most recent; assert it's a sig-ok / push-201 / vendor row.
  const topRow = page.locator('[data-testid="receipts-table"] tbody tr').first();
  await expect(topRow).toHaveText(new RegExp(vendor));
  // sig ok badge
  await expect(topRow.locator('.badge', { hasText: 'ok' })).toHaveText('ok');
  // push status badge text contains 201
  await expect(topRow.locator('.badge', { hasText: '201' })).toHaveText('201');

  // Click the row — that's the operator action that opens the drill page.
  await topRow.click();
  await expect(page).toHaveURL(/\/ui\/fabrics\/receipt\//);

  // Section presence: all four data-testids.
  await expect(page.locator('[data-testid="section-payload"]')).toHaveText(/Webhook payload/);
  await expect(page.locator('[data-testid="section-resolver"]')).toHaveText(/Resolver decisions/);
  await expect(page.locator('[data-testid="section-triples"]')).toHaveText(/Triples built/);
  await expect(page.locator('[data-testid="section-push"]')).toHaveText(/DCL push outcome/);

  // DCL push outcome shows HTTP 201.
  await expect(page.locator('[data-testid="push-status"]')).toHaveText('201');

  // Wait for the triples panel to populate from the async API call.
  const tripleRows = page.locator('[data-testid="triple-row"]');
  await expect.poll(async () => await tripleRows.count(), { timeout: 10_000 }).toBeGreaterThan(0);

  // First triple row carries all 5 provenance fields as non-empty cells.
  const firstTriple = tripleRows.first();
  for (const prov of ['source-system', 'source-field', 'pipe-id', 'fabric-plane', 'confidence-score']) {
    const cell = firstTriple.locator(`[data-testid="prov-${prov}"]`);
    const text = (await cell.innerText()).trim();
    expect(text.length).toBeGreaterThan(0);
    expect(text).not.toBe('null');
    expect(text).not.toBe('undefined');
  }
}

test('workato trigger → drill — 4 sections + 5 provenance fields visible', async ({ page }) => {
  await triggerAndDrill(page, 'workato');
  await page.screenshot({ path: 'screenshots/aam-fabrics-drill-workato.png' });
});

test('boomi trigger → drill — 4 sections + 5 provenance fields visible', async ({ page }) => {
  await triggerAndDrill(page, 'boomi');
  await page.screenshot({ path: 'screenshots/aam-fabrics-drill-boomi.png' });
});
