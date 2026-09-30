// Mock-only UI regression: no engine, model, credentials or audio are accessed.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const waitFor = async predicate => {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await predicate()) return;
    await delay(30);
  }
  throw Error('Mock condition did not arrive');
};

(async () => {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || 'msedge', headless: true });
  try {
    for (const scenario of ['automatic', 'ambiguous', 'late']) {
      const page = await browser.newPage({ viewport: { width: 1180, height: 940 } });
      page.setDefaultTimeout(10000);
      const errors = [], unexpected = [], saved = [], gates = [];
      page.on('pageerror', error => errors.push(error.message));
      const providers = ['qwen3', 'voxcpm2'].map(provider_id => ({ provider_id,
        name: provider_id === 'qwen3' ? 'Qwen3 TTS' : 'VoxCPM2', remote: false, version: '1', connection_required: false,
        modes: [{ id: 'reference', variant_kinds: ['reference'], models: [provider_id === 'qwen3' ? 'qwen3-base' : 'voxcpm2'] }],
        options_schema: { properties: { schema_version: { type: 'integer', default: 1 } } }, capabilities: {} }));
      const existing = id => ({ id, name: id, provider_id: 'qwen3', deployment: 'local' });
      const asset = { id: 'reference', name: '测试参考素材', transcript: '测试原文', language: 'zh', confirmed: true, duration: 3 };
      const library = { voices: [], recipes: [], assets: [asset], experiments: [], takes: [], plans: [], selections: [], assemblies: [],
        connections: scenario === 'ambiguous' ? [existing('local-a'), existing('local-b')]
          : scenario === 'late' ? [{ ...existing('chosen-remote'), deployment: 'cloud' }] : [] };
      const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' };
      await page.route('**/api/v1/**', async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
        const key = request.method() + ' ' + path;
        let data;
        if (key === 'GET /api/v1/speech/providers') data = { providers };
        else if (key === 'GET /api/v1/speech/library') data = library;
        else if (key === 'GET /api/v1/speech/references') data = { assets: [asset] };
        else if (key === 'GET /api/v1/speech/rules') data = { recipes: library.recipes };
        else if (key === 'GET /api/v1/speech/connections') data = { connections: library.connections };
        else if (key === 'GET /api/v1/tasks') data = { tasks: [] };
        else if (key === 'POST /api/v1/speech/connections/local-default') {
          const body = request.postDataJSON();
          if (scenario === 'ambiguous') data = { connection: null, readiness: null, detail: '已有多个连接，请明确选择。' };
          else {
            const connection = { id: body.provider_id + '-default', name: body.provider_id + ' 默认', provider_id: body.provider_id, deployment: 'local' };
            data = { connection, readiness: { ready: false, verified: false, code: 'runtime_missing', detail: '本地引擎运行环境未安装' },
              detail: '保存音色只保存配置，不会启动或安装模型。' };
            if (scenario === 'late' && body.provider_id === 'qwen3') await new Promise(resolve => gates.push(resolve));
            if (!library.connections.some(item => item.id === connection.id)) library.connections.push(connection);
          }
        } else if (key === 'POST /api/v1/speech/rules') {
          const body = request.postDataJSON(); saved.push(body);
          data = { ...body, variant: { ...body.variant, style: 'normal' }, id: 'saved-rule', voice_id: 'voice', revision: 1 };
          library.recipes = [data];
        } else { unexpected.push(key); return route.abort('blockedbyclient'); }
        await route.fulfill({ json: data, headers });
      });
      await page.goto(`${process.env.FRONTEND_URL || 'http://127.0.0.1:5196'}/tests/fixtures/voice-local-connection.html`);
      await page.getByRole('tab', { name: '我的音色', exact: true }).click();
      const engine = page.getByRole('combobox', { name: /^引擎/ });
      await engine.selectOption('qwen3');
      const choice = page.getByRole('combobox', { name: /^连接/ });
      if (scenario === 'automatic') {
        await page.getByText(/尚未就绪：本地引擎运行环境未安装/).waitFor();
        assert.equal(await choice.count(), 0);
        await page.getByLabel('音色名称', { exact: true }).fill('TC1');
        await page.getByRole('combobox', { name: /^参考素材/ }).selectOption('reference');
        await page.getByRole('button', { name: '保存音色', exact: true }).click();
        await page.getByText('已保存音色修订 1', { exact: true }).waitFor();
        assert.equal(saved[0].connection_ref, 'qwen3-default');
        assert.equal(saved[0].name, 'TC1');
        assert.equal(await page.getByRole('button', { name: '高级连接设置', exact: true }).isEnabled(), true);
        if (process.env.UI_SCREENSHOT_DIR) await page.screenshot({ path: process.env.UI_SCREENSHOT_DIR + '/voice-local-connection.png', fullPage: true });
      } else if (scenario === 'ambiguous') {
        await choice.waitFor();
        assert.equal(await choice.inputValue(), '');
        await choice.selectOption('local-b');
        assert.equal(await choice.inputValue(), 'local-b');
        assert.equal(saved.length, 0);
      } else {
        await waitFor(() => gates.length === 1);
        await page.getByRole('button', { name: '高级连接设置', exact: true }).click();
        await choice.selectOption('chosen-remote');
        gates[0]();
        await delay(120);
        assert.equal(await choice.inputValue(), 'chosen-remote');
        await engine.selectOption('voxcpm2');
        await page.getByText('本机运行 · voxcpm2 默认', { exact: true }).waitFor();
        await engine.selectOption('qwen3');
        await waitFor(() => gates.length === 2);
        await engine.selectOption('voxcpm2');
        gates[1]();
        await page.getByText('本机运行 · voxcpm2 默认', { exact: true }).waitFor();
        await delay(120);
        assert.equal(await engine.inputValue(), 'voxcpm2');
        assert.equal(await choice.count(), 0);
      }
      assert.deepEqual(unexpected, []);
      assert.deepEqual(errors, []);
      console.log('PASS local connection ' + scenario);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
