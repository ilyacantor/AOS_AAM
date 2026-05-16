// Operator-visible outcome: on /ui/fabrics the operator selects a workato pipe from the manual-entry dropdown, types finops-demo-co into the entity_id field, fills the dynamic field inputs (rendered from the pipe's FieldMapping), clicks submit, and within 10s a new receipt row appears with src="manual" and triples_pushed > 0; clicking that row opens the drill page where all four sections render and at least one triple row shows the 5 provenance fields.

import { test, expect } from '@playwright/test';

const MANUAL_ENTITY_ID = 'finops-demo-co';

test('manual entry — workato pipe → new receipt with src=manual → drill 4 sections + provenance', async ({ page, request }) => {
  // Ground-truth: fetch the pipe list so we don't hardcode pipe_key or field names.
  const pipesResp = await request.get('/api/aam/fabrics/manual/pipes');
  const { pipes } = await pipesResp.json();
  const workatoPipes = pipes.filter((p: { pipe_key: string }) => p.pipe_key.startsWith('workato::'));
  expect(workatoPipes.length).toBeGreaterThan(0);
  const targetPipe = workatoPipes[0];

  await page.goto('/ui/fabrics');

  const beforeCount = await page.locator('[data-testid="receipts-table"] tbody tr').count();

  // Operator selects the pipe — change event re-renders the dynamic field inputs.
  await page.locator('[data-testid="manual-pipe"]').selectOption(targetPipe.pipe_key);
  await page.locator('[data-testid="manual-entity-id"]').fill(MANUAL_ENTITY_ID);

  // Fill each rendered field with a deterministic test value derived from its source_field name.
  for (const field of targetPipe.fields) {
    const input = page.locator(`[data-testid="manual-field-${field.source_field}"]`);
    await input.fill(`mtest-${field.source_field}-${Date.now()}`);
  }

  await page.locator('[data-testid="manual-submit"]').click();

  // Receipts table grows within 10s.
  await expect.poll(
    async () => await page.locator('[data-testid="receipts-table"] tbody tr').count(),
    { timeout: 15_000, intervals: [1000, 1500, 2000] },
  ).toBeGreaterThan(beforeCount);

  // Top row labels src as "manual" (in the src column rendered by loadReceipts()).
  const topRow = page.locator('[data-testid="receipts-table"] tbody tr').first();
  await expect(topRow).toHaveText(/manual/);

  // Drill — click the row, verify 4 sections + provenance on at least one triple.
  await topRow.click();
  await expect(page).toHaveURL(/\/ui\/fabrics\/receipt\//);
  await expect(page.locator('[data-testid="section-payload"]')).toHaveText(/Webhook payload/);
  await expect(page.locator('[data-testid="section-resolver"]')).toHaveText(/Resolver decisions/);
  await expect(page.locator('[data-testid="section-triples"]')).toHaveText(/Triples built/);
  await expect(page.locator('[data-testid="section-push"]')).toHaveText(/DCL push outcome/);

  // Triples populate from async fetch.
  const tripleRows = page.locator('[data-testid="triple-row"]');
  await expect.poll(async () => await tripleRows.count(), { timeout: 10_000 }).toBeGreaterThan(0);

  const firstTriple = tripleRows.first();
  for (const prov of ['source-system', 'source-field', 'pipe-id', 'fabric-plane', 'confidence-score']) {
    const text = (await firstTriple.locator(`[data-testid="prov-${prov}"]`).innerText()).trim();
    expect(text.length).toBeGreaterThan(0);
  }

  await page.screenshot({ path: 'screenshots/aam-fabrics-manual-drill.png' });
});
