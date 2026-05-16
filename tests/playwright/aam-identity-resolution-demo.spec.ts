// Operator-visible outcome: after triggering workato then boomi from /ui/fabrics, the /ui/candidates Recent Matches table renders within 60s a row with left_value "Acme Corporation, Inc." (from NetSuite) and right_value "Acme Corporation Inc" (from Sage Intacct), confidence in the band [0.92, 0.96] inclusive, match-rule "fuzzy", domain "customer", and a non-empty canonical_id — the auto-applied identity resolution from deck Slide 8.

import { test, expect, Page } from '@playwright/test';

const ACME_NETSUITE_NAME = 'Acme Corporation, Inc.';
const ACME_SAGE_NAME = 'Acme Corporation Inc';
const CONFIDENCE_LO = 0.92;
const CONFIDENCE_HI = 0.96;

async function triggerVendor(page: Page, vendor: 'workato' | 'boomi') {
  await page.locator(`[data-testid="trigger-${vendor}"]`).click();
  // The trigger now fires multiple sync processes; wait for the customer-sync
  // receipt to land (event_type contains "customers"). Up to 30s per vendor
  // because the new dataset volume (~500 customers + ~5K invoices + chart +
  // ~3K AP invoices + ~200 vendors) lengthens the round trip.
  await expect.poll(
    async () => {
      const rows = await page.locator('[data-testid="receipts-table"] tbody tr').filter({ hasText: vendor }).filter({ hasText: 'customers' }).count();
      return rows;
    },
    { timeout: 60_000, intervals: [1500, 2500, 4000] },
  ).toBeGreaterThan(0);
}

test('identity resolution — Acme demo case auto-applied at 0.92–0.96', async ({ page }) => {
  await page.goto('/ui/fabrics');

  // First trigger: workato seeds the resolver registry with the 500 NetSuite
  // customer canonicals — including Customer #12345 / "Acme Corporation, Inc.".
  await triggerVendor(page, 'workato');

  // Second trigger: boomi pushes 500 Sage Intacct customer rows; the
  // "ACME-Corp" / "Acme Corporation Inc" row fuzzy-matches against the
  // registry's NetSuite entry and auto-applies at ~0.96.
  await triggerVendor(page, 'boomi');

  // Navigate to Candidates — Recent Matches section auto-loads on mount.
  await page.goto('/ui/candidates');

  // Poll for the Acme row to appear in Recent Matches.
  const acmeRow = page.locator('[data-testid="recent-match-row"]').filter({ hasText: ACME_NETSUITE_NAME });
  await expect.poll(
    async () => await acmeRow.count(),
    { timeout: 30_000, intervals: [1000, 2000, 3000] },
  ).toBeGreaterThan(0);

  const row = acmeRow.first();

  // The right side carries the Sage Intacct rendering exactly.
  await expect(row).toContainText(ACME_SAGE_NAME);

  // Confidence in the documented band.
  const confText = (await row.locator('[data-testid="match-confidence"]').innerText()).trim();
  const conf = Number(confText);
  expect(Number.isFinite(conf)).toBe(true);
  expect(conf).toBeGreaterThanOrEqual(CONFIDENCE_LO);
  expect(conf).toBeLessThanOrEqual(CONFIDENCE_HI);

  // Match rule must be "fuzzy" — the auto-apply tier of the four-tier
  // resolver. Anything else (exact, alias, pattern, hitl_pending) means
  // either the seed data drifted or the resolver picked a different tier.
  await expect(row.locator('[data-testid="match-rule"]')).toHaveText(/fuzzy/);

  // Domain must be "customer" — the resolver was invoked on the customer
  // domain (not vendor / employee / etc.).
  await expect(row.locator('[data-testid="match-domain"]')).toHaveText('customer');

  // canonical_id is a non-empty 8-char prefix + ellipsis.
  const canon = (await row.locator('[data-testid="match-canonical-id"]').innerText()).trim();
  expect(canon.length).toBeGreaterThan(0);
  expect(canon).not.toBe('—');

  // Timestamp is present and parses as ISO; rendered as "YYYY-MM-DD HH:MM:SS".
  const when = (await row.locator('[data-testid="match-when"]').innerText()).trim();
  expect(when).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);

  await page.screenshot({ path: 'screenshots/aam-identity-resolution-acme.png' });
});
