// Operator-visible outcome: AAM /ui/topology renders an 8-tab dark-theme nav strip in this exact order — Topology, Pipes, Candidates, Drift & Health, Fabrics, Reconcile, Controls, Guide — and clicking "Fabrics" navigates to /ui/fabrics where two vendor cards render for workato and boomi, each carrying a health-state badge whose text is one of {reachable, degraded, unreachable, auth_expired} matching the live /api/aam/fabrics/list response.

import { test, expect } from '@playwright/test';

const HEALTH_STATES = ['reachable', 'degraded', 'unreachable', 'auth_expired'];
const EXPECTED_TABS = [
  'Topology', 'Pipes', 'Candidates', 'Drift & Health',
  'Fabrics', 'Reconcile', 'Controls', 'Guide',
];

test('nav strip — 8 tabs in dispatch order, Fabrics highlighted on /ui/fabrics', async ({ page }) => {
  await page.goto('/ui/topology');
  const navLinks = page.locator('.nav-links .nav-link');
  await expect(navLinks).toHaveCount(EXPECTED_TABS.length);
  for (let i = 0; i < EXPECTED_TABS.length; i++) {
    await expect(navLinks.nth(i)).toHaveText(EXPECTED_TABS[i]);
  }

  await page.locator('[data-testid="nav-fabrics"]').click();
  await expect(page).toHaveURL(/\/ui\/fabrics$/);
  await expect(page.locator('[data-testid="nav-fabrics"]')).toHaveClass(/active/);

  await page.screenshot({ path: 'screenshots/aam-fabrics-nav.png' });
});

test('fabrics page — dark theme + two vendor cards matching /api/aam/fabrics/list', async ({ page, request }) => {
  const gt = await request.get('/api/aam/fabrics/list');
  const { vendors } = await gt.json();
  const expectedNames = vendors.map((v: { vendor: string }) => v.vendor).sort();
  const expectedStateByVendor = new Map(
    vendors.map((v: { vendor: string; health: { health_state: string } }) => [v.vendor, v.health.health_state]),
  );

  await page.goto('/ui/fabrics');

  // Dark theme — body background must be the AOS slate-900 (#0f172a → rgb(15, 23, 42)).
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(15, 23, 42)');

  // Cards count and per-vendor presence (count matches the API response, no literal).
  const cards = page.locator('[data-testid="vendor-cards"] [data-testid^="vendor-card-"]');
  await expect(cards).toHaveCount(expectedNames.length);

  for (const vendor of expectedNames) {
    const card = page.locator(`[data-testid="vendor-card-${vendor}"]`);
    await expect(card.locator('[data-testid="vendor-name"]')).toHaveText(vendor);
    // Health badge text must equal the live API value, which itself must be in the 4-state set.
    const expectedState = expectedStateByVendor.get(vendor) as string;
    expect(HEALTH_STATES).toContain(expectedState);
    const badgeText = await card.locator('[data-testid="vendor-health-badge"]').innerText();
    expect(badgeText.startsWith(expectedState)).toBe(true);
    // env-vars status indicator and aggregates section must render.
    await expect(card.locator('[data-testid="vendor-env-status"]')).toHaveText(/env:/);
    await expect(card.locator('[data-testid="vendor-aggregates"]')).toHaveText(/received·24h/);
    await expect(card.locator(`[data-testid="trigger-${vendor}"]`)).toHaveText(/trigger demo run/);
  }

  await page.screenshot({ path: 'screenshots/aam-fabrics-cards.png' });
});
