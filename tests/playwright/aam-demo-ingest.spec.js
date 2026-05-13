// Operator-visible outcome: on /ui/controls after clicking [Run Demo Ingest], the Demo Ingest panel shows 3 pipes total, 5 records total, 19 triples total, a Workato row with pipes=2 records=3 triples=11, a Boomi row with pipes=1 records=2 triples=8, and an aam_inference_id UUID line.
// @ts-check
const { test, expect } = require('@playwright/test');

const AAM_URL = process.env.AAM_URL || 'http://localhost:8002';

test('Demo Ingest: real click drives Workato + Boomi through ipaas_stub into triples', async ({ page }) => {
  // Sanity (read-only, page.request.get is allowed): factory must be in stub mode.
  const modeRes = await page.request.get(`${AAM_URL}/api/aam/ingest/demo/vendors`);
  const modeBody = await modeRes.json();
  expect(modeBody.harness_mode).toBe('stub');
  expect(modeBody.vendors).toEqual(['boomi', 'workato']);

  await page.goto(`${AAM_URL}/ui/controls`);
  await page.waitForLoadState('domcontentloaded');

  // The Demo Ingest panel is rendered with the button enabled.
  const button = page.locator('[data-testid="btn-run-demo-ingest"]');
  await expect(button).toHaveText('Run Demo Ingest');
  await expect(button).toBeEnabled();

  // Real operator gesture: click the button. No page.request.post anywhere.
  await button.click();

  // The status flips to 'Complete' once the chain finishes.
  await expect(page.locator('[data-testid="demo-ingest-status"]')).toHaveText('Complete', { timeout: 30000 });

  // Healthy-scenario ground truth (fixed by tests/fixtures/harness/scenarios/healthy.json):
  // Workato: wk-recipe-101 (2 records) + wk-recipe-102 (1 record). 2 pipes, 3 records, 11 triples.
  // Boomi:   bm-proc-201   (2 records).                            1 pipe,  2 records,  8 triples.
  // Total: 3 pipes, 5 records, 19 triples.
  await expect(page.locator('[data-testid="demo-total-pipes"]')).toHaveText('3');
  await expect(page.locator('[data-testid="demo-total-records"]')).toHaveText('5');
  await expect(page.locator('[data-testid="demo-total-triples"]')).toHaveText('19');

  const wkRow = page.locator('[data-testid="demo-vendor-row-workato"]');
  await expect(wkRow.locator('[data-testid="demo-vendor-name"]')).toHaveText('workato');
  await expect(wkRow.locator('[data-testid="demo-vendor-pipes"]')).toHaveText('2');
  await expect(wkRow.locator('[data-testid="demo-vendor-records"]')).toHaveText('3');
  await expect(wkRow.locator('[data-testid="demo-vendor-triples"]')).toHaveText('11');

  const bmRow = page.locator('[data-testid="demo-vendor-row-boomi"]');
  await expect(bmRow.locator('[data-testid="demo-vendor-name"]')).toHaveText('boomi');
  await expect(bmRow.locator('[data-testid="demo-vendor-pipes"]')).toHaveText('1');
  await expect(bmRow.locator('[data-testid="demo-vendor-records"]')).toHaveText('2');
  await expect(bmRow.locator('[data-testid="demo-vendor-triples"]')).toHaveText('8');

  // Inference id is rendered (provenance evidence visible to the operator).
  await expect(page.locator('[data-testid="demo-inference-id"]')).toHaveText(
    /aam_inference_id: [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/
  );

  // Screenshot for the completion handoff
  await page.screenshot({ path: 'test-results/aam-demo-ingest.png', fullPage: true });
});
