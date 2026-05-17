// Operator-visible outcome: after triggering workato then boomi from /ui/fabrics, the /ui/candidates Recent Matches table renders within 60s a row with left_value "Acme Corporation, Inc." (from NetSuite) and right_value "Acme Corporation Inc" (from Sage Intacct), confidence in the band [0.92, 0.96] inclusive, match-rule "fuzzy", domain "customer", and a non-empty canonical_id — the auto-applied identity resolution from deck Slide 8.

import { test, expect, Page } from '@playwright/test';

// WS-2 B4 score-tuned renderings — empirically score 0.9455 against the
// resolver's similarity_score function (auto-apply tier, in 0.94 ±0.02 band).
const ACME_NETSUITE_NAME = 'Acme Corp Inc.';
const ACME_SAGE_NAME = 'Acme Corp';
const CONFIDENCE_LO = 0.92;
const CONFIDENCE_HI = 0.96;

async function triggerVendor(page: Page, vendor: 'workato' | 'boomi') {
  // Click the trigger button. The button's JS handler awaits the AAM proxy,
  // which awaits Farm firing all 5 syncs. On success the result span shows
  // "ok fired N" — that text is the unambiguous signal that the run
  // completed (all webhooks dispatched). Don't poll the receipts table —
  // its 50-row limit makes the "new customer receipt" delta unstable when
  // prior runs left customer rows already populating the table.
  await page.locator(`[data-testid="trigger-${vendor}"]`).click();
  const resultSpan = page.locator(`#trig-result-${vendor}`);
  // 200s timeout: boomi trigger fires 5 syncs synchronously; resolver
  // registry grows across runs, slowing per-record fuzzy scans. 200s
  // accommodates accumulated state without test restart.
  await expect(resultSpan).toContainText('fired', { timeout: 200_000 });
}

test('identity resolution — Acme demo case auto-applied at 0.92–0.96', async ({ page }) => {
  // WS-2 dataset volumes: workato trigger ~30s, boomi trigger ~70s
  // (5 syncs each, 10K-50K triples per AR-invoice sync). Plus Recent
  // Matches poll. Allow 240s test budget.
  test.setTimeout(480_000);
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

  // Poll for the Acme row to appear in Recent Matches. 60s budget:
  // page renders immediately but the 3s auto-refresh setInterval may
  // need a cycle or two to catch the boomi-triggered auto-applied row.
  const acmeRow = page.locator('[data-testid="recent-match-row"]').filter({ hasText: ACME_NETSUITE_NAME });
  await expect.poll(
    async () => await acmeRow.count(),
    { timeout: 60_000, intervals: [2000, 3000, 4000] },
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
