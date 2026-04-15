// @ts-check
const { test, expect } = require('@playwright/test');

const AAM_URL = process.env.AAM_URL || 'http://localhost:8002';

// T1 — Action buttons render with correct disabled/enabled state on page load
test('T1: New-architecture action buttons render with correct gating', async ({ page, request }) => {
  await page.goto(`${AAM_URL}/ui/topology`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2000);

  // Run Inference: primary action, always enabled
  const runInference = page.locator('[data-testid="btn-run-inference"]');
  await expect(runInference).toHaveCount(1);
  await expect(runInference).toBeEnabled();

  // Run Discovery, Validate Credentials, Start Ingest: greyed out (disabled)
  const runDiscovery = page.locator('[data-testid="btn-run-discovery"]');
  await expect(runDiscovery).toHaveCount(1);
  await expect(runDiscovery).toBeDisabled();

  const validateCreds = page.locator('[data-testid="btn-validate-credentials"]');
  await expect(validateCreds).toHaveCount(1);
  await expect(validateCreds).toBeDisabled();

  const startIngest = page.locator('[data-testid="btn-start-ingest"]');
  await expect(startIngest).toHaveCount(1);
  await expect(startIngest).toBeDisabled();

  // Old pipeline buttons MUST NOT exist
  await expect(page.locator('#fetch-aod-btn')).toHaveCount(0);
  await expect(page.locator('#btn-full-pipeline')).toHaveCount(0);
  await expect(page.locator('#btn-export-dcl')).toHaveCount(0);
  await expect(page.locator('#btn-dispatch-all')).toHaveCount(0);
  await expect(page.locator('#btn-stop-all')).toHaveCount(0);
  await expect(page.locator('#btn-view-dispatch')).toHaveCount(0);
});

// T2 — Pipes tab plane filter consistency
test('T2: /ui/pipes plane filter accepts new lowercase canonical values', async ({ page }) => {
  const expected = {
    ipaas: 'IPAAS',
    api_gateway: 'API_GATEWAY',
    event_bus: 'EVENT_BUS',
    warehouse: 'DATA_WAREHOUSE',
  };

  for (const [filterValue, badgeText] of Object.entries(expected)) {
    await page.goto(`${AAM_URL}/ui/pipes?filter=${filterValue}`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(800);

    // The select should have the chosen value selected (if the dropdown exists)
    const filterSelect = page.locator('select[name="filter"], select#filter, select[data-testid="filter"]');
    if (await filterSelect.count() > 0) {
      const sel = filterSelect.first();
      const val = await sel.inputValue();
      expect(val).toBe(filterValue);
    }

    // Every visible row's fabric column must normalize to the expected canonical badge
    const rowFabricCells = page.locator('table tr td.fabric, table tr td[data-col="fabric"]');
    const count = await rowFabricCells.count();
    if (count > 0) {
      for (let i = 0; i < count; i++) {
        const text = (await rowFabricCells.nth(i).innerText()).trim().toUpperCase();
        // Allow either canonical (DATA_WAREHOUSE) or its short alias (WAREHOUSE)
        const acceptable = filterValue === 'warehouse'
          ? ['DATA_WAREHOUSE', 'WAREHOUSE']
          : [badgeText];
        expect(acceptable).toContain(text);
      }
    }
  }
});

// T3 — All Assets toggle persists after topology re-fetch and navigation
test('T3: View state persists across re-fetch and navigation', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/topology?view=api_gateway&detail=summary`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2000);

  // Dropdown should reflect URL state
  let assetFilter = await page.locator('#asset-filter').inputValue();
  expect(assetFilter).toBe('api_gateway');

  // Trigger a re-fetch by calling refreshSidebarRun (silent background refresh path)
  await page.evaluate(() => {
    if (typeof refreshSidebarRun === 'function') return refreshSidebarRun();
  });
  await page.waitForTimeout(1000);

  // Filter should still be selected
  assetFilter = await page.locator('#asset-filter').inputValue();
  expect(assetFilter).toBe('api_gateway');
  expect(page.url()).toContain('view=api_gateway');

  // Navigate away and back
  await page.goto(`${AAM_URL}/ui/pipes`);
  await page.waitForLoadState('domcontentloaded');
  await page.goto(`${AAM_URL}/ui/topology?view=api_gateway&detail=summary`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1500);

  assetFilter = await page.locator('#asset-filter').inputValue();
  expect(assetFilter).toBe('api_gateway');
});

// T4 — Instrumentation tiles
test('T4: Instrumentation panel renders new tiles, no Exported tile', async ({ page }) => {
  await page.goto(`${AAM_URL}/ui/topology`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2000);

  // New tiles must exist
  await expect(page.locator('[data-testid="stat-planes"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="stat-sors"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="stat-pipes"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="stat-drift"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="stat-health"]')).toHaveCount(1);

  // Health sub-tiles
  await expect(page.locator('[data-testid="health-reachable"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="health-degraded"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="health-unreachable"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="health-auth-expired"]')).toHaveCount(1);

  // Old "Exported" tile must be gone
  await expect(page.locator('[data-testid="stat-exported"]')).toHaveCount(0);
  await expect(page.locator('#stat-exported')).toHaveCount(0);

  // The literal "Exported" word must not appear in the sidebar instrumentation block
  const sidebar = page.locator('.topo-sidebar, aside.topo-sidebar');
  const sidebarText = await sidebar.first().innerText();
  expect(sidebarText).not.toContain('Exported');
});

// T5 — Backend stub routes return 200 OK
test('T5: Backend stub routes for new actions respond 200', async ({ request }) => {
  const ms = await request.get(`${AAM_URL}/api/aam/discovery/manifest-status`);
  expect(ms.ok()).toBeTruthy();
  const msData = await ms.json();
  expect(msData).toHaveProperty('manifest_loaded');
  expect(msData).toHaveProperty('plane_count');

  const dr = await request.post(`${AAM_URL}/api/aam/discovery/run`);
  expect(dr.ok()).toBeTruthy();
  const drData = await dr.json();
  expect(drData.status).toBe('ok');

  const cv = await request.post(`${AAM_URL}/api/aam/credentials/validate`);
  expect(cv.ok()).toBeTruthy();
  const cvData = await cv.json();
  expect(cvData.status).toBe('ok');
  expect(Array.isArray(cvData.results)).toBeTruthy();
  expect(cvData.results.length).toBe(4);
  // Each result row uses a lowercase canonical plane name
  for (const r of cvData.results) {
    expect(['ipaas', 'api_gateway', 'event_bus', 'warehouse']).toContain(r.plane);
  }

  const ing = await request.post(`${AAM_URL}/api/aam/ingest/start`);
  expect(ing.ok()).toBeTruthy();
  const ingData = await ing.json();
  expect(ingData.status).toBe('ok');
  expect(ingData.ingest_state).toBe('active');

  const hs = await request.get(`${AAM_URL}/api/aam/health/summary`);
  expect(hs.ok()).toBeTruthy();
  const hsData = await hs.json();
  expect(hsData).toHaveProperty('reachable');
  expect(hsData).toHaveProperty('degraded');
  expect(hsData).toHaveProperty('unreachable');
  expect(hsData).toHaveProperty('auth_expired');

  const pc = await request.get(`${AAM_URL}/api/aam/pipes/count`);
  expect(pc.ok()).toBeTruthy();
  const pcData = await pc.json();
  expect(pcData).toHaveProperty('count');
});

// T6 — /api/topology/plane endpoint accepts lowercase aliases
test('T6: /api/topology/plane accepts lowercase aliases', async ({ request }) => {
  for (const alias of ['ipaas', 'api_gateway', 'event_bus', 'warehouse']) {
    const res = await request.get(`${AAM_URL}/api/topology/plane/${alias}`);
    expect(res.ok()).toBeTruthy();
    const data = await res.json();
    expect(data).toHaveProperty('nodes');
    expect(data).toHaveProperty('edges');
  }
});

// T7 — Auto-fetch of latest AOD handoff: 10s interval picks up new handoffs without manual refresh
test('T7: Sidebar auto-updates when a new AOD handoff appears', async ({ page }) => {
  let callCount = 0;
  const firstRun = {
    aod_run_id: 'run_first_test',
    snapshot_name: 'FirstSnap',
    entity_id: 'FirstSnap',
    candidates_received: 10,
    candidates_accepted: 10,
    handoff_timestamp: '2026-04-15T10:00:00Z',
  };
  const secondRun = {
    aod_run_id: 'run_second_test',
    snapshot_name: 'SecondSnap',
    entity_id: 'SecondSnap',
    candidates_received: 42,
    candidates_accepted: 42,
    handoff_timestamp: '2026-04-15T11:00:00Z',
  };

  await page.route('**/api/handoff/aod/latest', async (route) => {
    callCount += 1;
    const body = callCount === 1 ? firstRun : secondRun;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await page.goto(`${AAM_URL}/ui/topology`);
  await page.waitForLoadState('domcontentloaded');

  // First fetch should populate with FirstSnap
  await expect(page.locator('#sb-run-info')).toContainText('FirstSnap', { timeout: 5000 });

  // Confirm the 10-second interval is configured (regression guard against future slowdowns)
  const html = await page.content();
  expect(html).toContain('setInterval(refreshSidebarRun, 10000)');

  // Manually trigger the poll (faster than waiting 10s) — simulates the next tick
  await page.evaluate(() => refreshSidebarRun());

  // Sidebar should now reflect the second handoff without any page reload
  await expect(page.locator('#sb-run-info')).toContainText('SecondSnap', { timeout: 5000 });
  expect(callCount).toBeGreaterThanOrEqual(2);
});

// T8 — Handoff endpoint failure surfaces visibly instead of silently going stale
test('T8: Sidebar shows a visible error when /api/handoff/aod/latest fails', async ({ page }) => {
  await page.route('**/api/handoff/aod/latest', async (route) => {
    await route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":"boom"}' });
  });

  await page.goto(`${AAM_URL}/ui/topology`);
  await page.waitForLoadState('domcontentloaded');

  // The sidebar must show a user-visible failure message — not the old silent stale state
  await expect(page.locator('#sb-run-info')).toContainText('handoff fetch failed', { timeout: 5000 });
  await expect(page.locator('#sb-run-info')).toContainText('500');
});
