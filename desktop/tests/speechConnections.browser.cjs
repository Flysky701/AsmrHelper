// Run against Vite in an isolated source copy; every API request is intercepted.
// Reuses the installed Playwright tooling via PLAYWRIGHT_MODULE, without new dependencies.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 780 } });
    page.setDefaultTimeout(10000);
    const errors = [], requests = [], unexpected = [], saves = [];
    page.on('pageerror', error => errors.push(error.message));
    let imported = false;
    let existing = { id: 'existing', name: '现有连接', provider_id: 'fish_audio', deployment: 'cloud',
      base_url: 'https://speech.invalid/v1', credential_configured: true };
    const added = { id: 'imported', name: '导入连接', provider_id: 'fish_audio', deployment: 'cloud',
      base_url: 'https://legacy.invalid/v1', credential_configured: false };
    const report = () => ({ entries: [{ source: 'profile:test', name: '旧连接条目', provider_id: 'fish_audio',
      status: imported ? 'imported' : 'ready', connection_id: imported ? 'imported' : '',
      credential_configured: false, reason: '', retained_fields: [] }], legacy_local_settings_retained: true, note: '' });
    const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS' };
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), endpoint = new URL(request.url()).pathname;
      if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
      const key = `${request.method()} ${endpoint}`;
      requests.push(key);
      let data;
      if (key === 'GET /api/v1/speech/providers') data = { providers: [{ provider_id: 'fish_audio', name: 'Fish Audio',
        remote: true, version: '1', connection_required: true, modes: [], options_schema: { properties: {} }, capabilities: {} }] };
      else if (key === 'GET /api/v1/speech/connections') data = { connections: imported ? [existing, added] : [existing] };
      else if (key === 'GET /api/v1/speech/legacy-import') data = report();
      else if (key === 'POST /api/v1/speech/legacy-import') {
        assert.deepEqual(request.postDataJSON(), {});
        imported = true;
        data = report();
      } else if (key === 'POST /api/v1/speech/connections') {
        const body = request.postDataJSON();
        saves.push(body);
        existing = { ...existing, ...body };
        data = existing;
      } else {
        unexpected.push(key);
        return route.abort('blockedbyclient');
      }
      await route.fulfill({ json: data, headers });
    });
    await page.goto(`${process.env.FRONTEND_URL || 'http://127.0.0.1:5194'}/tests/fixtures/speech-connections.html`);
    await page.getByRole('heading', { name: '现有连接', exact: true }).waitFor();
    assert.equal(requests.filter(key => key === 'GET /api/v1/speech/connections').length, 1);
    await page.getByRole('button', { name: '编辑', exact: true }).click();
    const name = page.getByLabel('连接名称', { exact: true });
    const key = page.getByLabel('API 密钥', { exact: true });
    assert.equal(await key.inputValue(), '');
    await name.fill('保留的编辑草稿');
    await page.locator('summary').click();
    await page.getByRole('button', { name: '导入可转换的服务', exact: true }).click();
    await page.getByRole('heading', { name: '导入连接', exact: true }).waitFor();
    assert.equal(await name.inputValue(), '保留的编辑草稿');
    assert.equal(await key.inputValue(), '');
    assert.equal(await page.getByLabel('API 地址', { exact: true }).inputValue(), 'https://speech.invalid/v1');
    assert.equal(requests.filter(item => item === 'GET /api/v1/speech/connections').length, 2);
    assert.equal(requests.filter(item => item === 'GET /api/v1/speech/providers').length, 1);
    await page.getByRole('button', { name: '保存服务', exact: true }).click();
    await page.getByRole('heading', { name: '保留的编辑草稿', exact: true }).waitFor();
    assert.deepEqual(saves, [{ id: 'existing', name: '保留的编辑草稿', provider_id: 'fish_audio',
      deployment: 'cloud', base_url: 'https://speech.invalid/v1' }]);
    assert.ok(requests.every(item => !item.includes('/speech/library')));
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    console.log('PASS initial load and import refresh use connections only; draft and blank-key save are preserved');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
