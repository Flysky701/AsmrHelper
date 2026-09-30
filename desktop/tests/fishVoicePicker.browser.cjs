// Run against Vite in an isolated source copy; all speech requests are mocked.
// PLAYWRIGHT_MODULE may point to an existing external Playwright installation.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 780 } });
    const errors = [], queries = [];
    page.on('pageerror', error => errors.push(error.message));
    let releaseOld;
    const response = (items, pageNumber = 1, hasMore = false) => ({ items, page: pageNumber, page_size: 20, has_more: hasMore, notice: '' });
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), url = new URL(request.url()), endpoint = url.pathname;
      assert.equal(request.method(), 'GET', 'UI lookup must never invoke synthesis or write APIs');
      let data;
      if (endpoint.endsWith('/providers')) data = { providers: [{ provider_id: 'fish_audio', name: 'Fish Audio',
        remote: true, version: '1', connection_required: true, options_schema: { properties: {} }, capabilities: {},
        modes: [{ id: 'hosted', models: ['s2-pro'], variant_kinds: ['hosted'], capabilities: {},
          voice_sources: { kind: 'hosted', presets: [], default: null, required: true, allow_custom: true, description: '填写服务端真实 Voice ID' } }] }] };
      else if (endpoint.endsWith('/library')) data = { assets: [], connections: ['a', 'b'].map(id => ({ id, name: `连接 ${id.toUpperCase()}`, provider_id: 'fish_audio', deployment: 'cloud' })) };
      else if (endpoint.endsWith('/rules')) data = { recipes: [] };
      else if (/\/connections\/[^/]+\/voices$/.test(endpoint)) {
        const query = { connection: endpoint.split('/').at(-2), title: url.searchParams.get('title'),
          page: Number(url.searchParams.get('page')), workspace: url.searchParams.get('workspace_only') };
        queries.push(query);
        if (query.title === 'late') {
          await new Promise(resolve => { releaseOld = resolve; });
          data = response([{ id: 'old-id', name: '旧连接声音' }]);
        } else if (query.title === 'network') return route.abort('failed');
        else if (query.title === 'denied' || query.title === 'unsupported') return route.fulfill({ status: 422,
          json: { detail: query.title === 'denied' ? '无权读取声音列表' : '当前代理不支持声音列表' }, headers: { 'Access-Control-Allow-Origin': '*' } });
        else if (query.title === 'empty') data = response([]);
        else data = response([{ id: `${query.connection}-${query.page}`, name: query.title || `声音 ${query.page}` }], query.page, query.page === 1);
      } else throw Error(`Unexpected API: ${endpoint}`);
      await route.fulfill({ json: data, headers: { 'Access-Control-Allow-Origin': '*' } });
    });
    await page.goto(`${process.env.FRONTEND_URL || 'http://127.0.0.1:5194'}/tests/fixtures/fish-voice-picker.html`);
    const manual = page.getByPlaceholder('填写服务端真实 Voice ID', { exact: true });
    const connections = page.getByRole('combobox', { name: '语音服务连接', exact: true });
    const search = page.getByRole('textbox', { name: '查找声音名称', exact: true });
    const choices = page.getByRole('combobox', { name: '可用声音', exact: true });
    await connections.waitFor();
    assert.equal(await manual.inputValue(), 'user-kept-id');
    assert.equal(queries.length, 0);
    await connections.selectOption('a');
    await choices.locator('option[value="a-1"]').waitFor({ state: 'attached' });
    assert.equal(await manual.inputValue(), 'user-kept-id', 'fetch must not choose a voice');
    await choices.selectOption('a-1');
    assert.equal(await manual.inputValue(), 'a-1');
    await manual.fill('handwritten');
    await search.fill('温柔');
    await choices.locator('option', { hasText: '温柔' }).waitFor({ state: 'attached' });
    assert.equal(queries.at(-1).title, '温柔');
    assert.equal(await manual.inputValue(), 'handwritten');
    await page.getByRole('button', { name: '下一页', exact: true }).click();
    await choices.locator('option[value="a-2"]').waitFor({ state: 'attached' });
    await choices.selectOption('a-2');
    assert.equal(await manual.inputValue(), 'a-2');
    await page.getByRole('combobox', { name: '声音范围', exact: true }).selectOption('public');
    await choices.locator('option[value="a-1"]').waitFor({ state: 'attached' });
    assert.equal(queries.at(-1).workspace, 'false');
    assert.equal(queries.at(-1).page, 1);
    console.log('PASS lookup, named search, explicit selection, manual ID, pagination and scope');

    await manual.fill('preserve-me');
    for (const title of ['empty', 'denied', 'unsupported', 'network']) {
      await search.fill(title);
      if (title === 'empty') await page.getByText('没有匹配的声音。', { exact: false }).waitFor();
      else await page.getByRole('alert').waitFor();
      assert.equal(await manual.inputValue(), 'preserve-me');
    }
    await search.fill('recovered');
    await choices.locator('option[value="a-1"]').waitFor({ state: 'attached' });
    console.log('PASS empty, unauthorized, unsupported proxy, network failure and recovery preserve ID');

    await search.fill('late');
    await page.waitForFunction(() => document.querySelector('[role=status]')?.textContent?.includes('正在获取'));
    for (let count = 0; !releaseOld && count < 60; count++) await page.waitForTimeout(50);
    assert.ok(releaseOld);
    await connections.selectOption('b');
    await choices.locator('option[value="b-1"]').waitFor({ state: 'attached' });
    releaseOld();
    await page.waitForTimeout(350);
    assert.equal(await choices.locator('option[value="old-id"]').count(), 0);
    assert.equal(await manual.inputValue(), 'preserve-me');
    await choices.selectOption('b-1');
    assert.equal(await manual.inputValue(), 'b-1');
    console.log('PASS connection switch ignores late response and never clears manual ID');

    releaseOld = undefined;
    await search.fill('late');
    for (let count = 0; !releaseOld && count < 60; count++) await page.waitForTimeout(50);
    assert.ok(releaseOld);
    await search.fill('新的搜索');
    await choices.locator('option', { hasText: '新的搜索' }).waitFor({ state: 'attached' });
    releaseOld();
    await page.waitForTimeout(350);
    assert.equal(await choices.locator('option[value="old-id"]').count(), 0);
    assert.equal(await manual.inputValue(), 'b-1');
    console.log('PASS late search response cannot replace newer candidates or chosen ID');

    if (process.env.SCREENSHOT_DIR) {
      fs.mkdirSync(process.env.SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({ path: path.join(process.env.SCREENSHOT_DIR, 'voice-id-desktop.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: path.join(process.env.SCREENSHOT_DIR, 'voice-id-narrow.png'), fullPage: true });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    }
    assert.deepEqual(errors, []);
    console.log('PASS no page errors or horizontal overflow');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
