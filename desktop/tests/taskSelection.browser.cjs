// Real Workbench + TaskCenter; every API is mocked and other network calls are refused.
// Run against an isolated Vite source copy with VITE_API_BASE=http://127.0.0.1:5200/api/v1.
// Set PLAYWRIGHT_MODULE to an existing installation; set ARTIFACT_DIR outside the repository.
// This script never starts the actual app and refuses API requests to its backend.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function gate() { let release; const promise = new Promise(resolve => { release = resolve; }); return { promise, release }; }
async function until(condition, label) {
  const deadline = Date.now() + 10000;
  while (!condition()) { if (Date.now() > deadline) throw new Error(`Timed out: ${label}`); await new Promise(resolve => setTimeout(resolve, 20)); }
}

(async () => {
  const startedAt = Date.now();
  const frontend = new URL(process.env.FRONTEND_URL || 'http://127.0.0.1:5200');
  assert.ok(frontend.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(frontend.hostname) && frontend.port !== '8000', 'Use a dedicated localhost fixture origin');
  const fixture = process.env.FIXTURE_PATH || [path.join(__dirname, 'fixtures/task-selection.html'), path.join(__dirname, 'task-selection.html')].find(fs.existsSync);
  assert.ok(fixture, 'Fixture HTML must exist');
  const artifacts = process.env.ARTIFACT_DIR || path.join(__dirname, 'artifacts');
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'zh-CN', timezoneId: 'UTC', serviceWorkers: 'block' });
  const page = await context.newPage(); page.setDefaultTimeout(10000);
  const errors = [], unexpected = [], requests = [], submissions = [], checks = [];
  const delayed = gate(); let oldSpecPending = false, oldResultPending = false;
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => { unexpected.push(`dialog:${dialog.type()}`); void dialog.dismiss(); });
  const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' };
  const history = { task_id: 'pipeline-1', task_type: 'pipeline', state: 'failed', stage: 'translate', progress: .4,
    message: 'Historical translation failed', detail: '', error: { code: 'TASK_EXECUTION_FAILED', message: 'HISTORICAL_TRANSLATION_ERROR' },
    input_asset_id: 'history-translation.wav', created_at: '2026-09-20T01:02:03Z', finished_at: '2026-09-20T01:04:05Z' };
  const remoteTasks = [history];
  const provider = { provider_id: 'mock_speech', name: 'Mock Speech', remote: false, version: '1', connection_required: false,
    options_schema: { properties: {} }, capabilities: {}, modes: [{ id: 'hosted', models: ['fixture'], variant_kinds: ['hosted'], capabilities: {},
      voice_sources: { kind: 'hosted', presets: [], default: null, required: true, allow_custom: true, description: 'Voice ID' } }] };

  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== frontend.origin) {
      unexpected.push(`${request.method()} ${url.origin}${url.pathname}`); return route.abort('blockedbyclient');
    }
    if (!url.pathname.startsWith('/api/v1/')) {
      if (['GET', 'HEAD'].includes(request.method()) && !['fetch', 'xhr', 'eventsource'].includes(request.resourceType())) return route.continue();
      unexpected.push(`${request.method()} ${url.pathname}`); return route.abort('blockedbyclient');
    }
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    const endpoint = url.pathname.slice('/api/v1'.length), key = `${request.method()} ${endpoint}`;
    requests.push(key);
    let data;
    if (key === 'GET /tasks') data = { tasks: structuredClone(remoteTasks) };
    else if (key === 'GET /capabilities') data = [];
    else if (key === 'GET /settings') data = { settings: { connection_profiles: { llm: [], active_llm: '' }, providers: { default_llm: 'deepseek', deepseek: {}, openai: {} } } };
    else if (key === 'GET /speech/providers') data = { providers: [provider] };
    else if (key === 'GET /speech/library') data = { assets: [], connections: [], voices: [], recipes: [], experiments: [], takes: [], plans: [], selections: [], assemblies: [] };
    else if (key === 'GET /speech/rules') data = { recipes: [] };
    else if (key === 'POST /runtime/check-task-readiness') { checks.push(request.postDataJSON()); data = { ready: true, issues: [], missing_requirements: [] }; }
    else if (key === 'POST /pipeline-runs') {
      submissions.push(request.postDataJSON());
      const number = submissions.length + 1;
      const task = { task_id: `pipeline-${number}`, task_type: 'pipeline', state: 'running', stage: 'tts', progress: .5,
        message: `NEW_TTS_TASK_${number}`, detail: '', error: null, input_asset_id: 'target.zh.vtt',
        created_at: new Date().toISOString(), started_at: new Date().toISOString(), finished_at: null };
      remoteTasks.push(task); data = { task };
    } else {
      const match = endpoint.match(/^\/tasks\/(pipeline-\d+)\/(spec|result|recovery|events)$/);
      if (!match || request.method() !== 'GET' || !remoteTasks.some(task => task.task_id === match[1])) {
        unexpected.push(key); return route.abort('blockedbyclient');
      }
      const [, id, action] = match;
      if (action === 'events') return route.fulfill({ status: 204, headers: { ...cors, 'Content-Type': 'text/event-stream' } });
      if (action === 'recovery') data = { can_resume: false, completed_stages: [], reason: 'Fixture history only' };
      else if (action === 'spec') {
        if (id === 'pipeline-1' && !oldSpecPending) { oldSpecPending = true; await delayed.promise; }
        data = { task_id: id, execution_profile: { marker: id === 'pipeline-1' ? 'OLD_SPEC_MARKER' : `NEW_SPEC_${id}` }, retry_of_task_id: null };
      } else if (action === 'result') {
        if (id === 'pipeline-1' && !oldResultPending) { oldResultPending = true; await delayed.promise; }
        data = { task_id: id, primary_artifact_id: null, warnings: [], artifacts: id === 'pipeline-1' ? [{ artifact_id: 'old-artifact',
          type: 'text.subtitle', path: 'D:/fixture/OLD_RESULT_MARKER.srt', stage: 'translate', label: 'OLD_RESULT_MARKER', primary: false, preview: false, metadata: {} }] : [] };
      }
    }
    try { await route.fulfill({ json: data, headers: cors }); }
    catch (error) { if (!page.isClosed() && !/closed|disposed|cancel/i.test(String(error))) throw error; }
  });

  const detail = () => page.locator('.task-center-detail');
  const list = () => page.locator('.task-center-list-panel');
  const errorCard = () => page.getByLabel('任务错误', { exact: true });
  const snapshot = () => page.evaluate(() => window.__taskDetail.snapshot());
  const selectHistory = async () => { await page.locator('.task-center-task-card').filter({ hasText: 'history-translation.wav' }).click(); await page.waitForFunction(() => window.__taskDetail.snapshot().selectedServerId === 'pipeline-1'); };
  const waitForTask = async id => {
    await page.waitForFunction(expected => window.__taskDetail.snapshot().page === 'task-center' && window.__taskDetail.snapshot().selectedServerId === expected, id);
    await detail().getByText(id, { exact: true }).waitFor();
  };
  const submit = async id => {
    await page.getByRole('button', { name: 'Fixture Workbench', exact: true }).click();
    await page.getByPlaceholder('Voice ID', { exact: true }).waitFor();
    await page.waitForFunction(() => !document.querySelector('.workbench-speech fieldset')?.disabled);
    const response = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/v1/pipeline-runs');
    await page.getByRole('button', { name: '创建并执行', exact: true }).click();
    await response; await waitForTask(id);
    assert.equal(await errorCard().count(), 0);
    assert.doesNotMatch(await detail().innerText(), /HISTORICAL_TRANSLATION_ERROR|OLD_SPEC_MARKER|OLD_RESULT_MARKER/);
  };
  const waitForPoll = async () => {
    const response = await page.waitForResponse(r => r.request().method() === 'GET' && new URL(r.url()).pathname === '/api/v1/tasks');
    await response.finished();
    // Let the existing store subscription/render settle; this is not a simulated polling call.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  };

  try {
    const fixtureUrl = fixture === path.join(__dirname, 'fixtures/task-selection.html')
      ? '/tests/fixtures/task-selection.html'
      : `/@fs/${fixture.replace(/\\/g, '/')}`;
    await page.goto(new URL(fixtureUrl, frontend).href);
    await errorCard().waitFor();
    await until(() => oldSpecPending && oldResultPending, 'historical spec and result are deliberately delayed');
    const finished = await page.evaluate(() => new Date('2026-09-20T01:04:05Z').toLocaleString());
    assert.ok((await errorCard().innerText()).includes('任务 pipeline-1'));
    assert.ok((await errorCard().innerText()).includes(`失败于 ${finished}`));
    await submit('pipeline-2');
    for (const body of [checks[0], submissions[0]]) {
      assert.deepEqual(Object.entries(body.execution_profile.stages).filter(([, value]) => value.enabled).map(([id]) => id), ['tts']);
    }
    await detail().getByText('NEW_SPEC_pipeline-2', { exact: true }).waitFor();
    delayed.release();
    await waitForPoll();
    assert.equal((await snapshot()).selectedServerId, 'pipeline-2');
    assert.doesNotMatch(await detail().innerText(), /HISTORICAL_TRANSLATION_ERROR|OLD_SPEC_MARKER|OLD_RESULT_MARKER/);
    console.log('PASS real Workbench submit selects new TTS-only task; delayed old spec/result never replace its detail');

    await selectHistory();
    await detail().getByText('OLD_SPEC_MARKER', { exact: true }).waitFor();
    await detail().getByText('OLD_RESULT_MARKER', { exact: true }).waitFor();
    await list().getByRole('button', { name: /^失败\s+\d+$/ }).click();
    await waitForPoll();
    assert.equal((await snapshot()).selectedServerId, 'pipeline-1');
    assert.equal(await page.locator('.task-center-task-card').count(), 1);
    assert.ok((await errorCard().innerText()).includes('HISTORICAL_TRANSLATION_ERROR'));
    // An explicit new selection, unlike polling, must reveal a task hidden by this failed filter.
    await page.evaluate(() => window.__taskDetail.selectServerTask('pipeline-2'));
    await waitForTask('pipeline-2');
    assert.equal(await page.locator('.task-center-task-card').count(), 2);
    assert.equal(await errorCard().count(), 0);
    console.log('PASS historical review and failed filter survive polling; explicit hidden-task selection clears conflicting filter');

    await selectHistory();
    await page.getByRole('button', { name: 'Fixture Workbench', exact: true }).click();
    await page.getByRole('button', { name: 'Fixture TaskCenter', exact: true }).click();
    await waitForTask('pipeline-1');
    await submit('pipeline-3');
    assert.equal(submissions.length, 2);
    assert.equal((await snapshot()).selectedServerId, 'pipeline-3');
    await page.getByRole('navigation', { name: '任务分类', exact: true }).getByRole('button', { name: /^模型下载\s/ }).click();
    await page.evaluate(() => window.__taskDetail.selectServerTask('pipeline-3'));
    await waitForTask('pipeline-3');
    await selectHistory();
    await list().getByRole('button', { name: /^失败\s+\d+$/ }).click();
    await page.evaluate(() => window.__taskDetail.seedLocalFailure());
    await errorCard().filter({ hasText: 'LOCAL_SUBMISSION_ERROR' }).waitFor();
    const created = await page.evaluate(() => new Date('2026-09-21T02:03:04Z').toLocaleString());
    const localError = await errorCard().innerText();
    assert.ok(localError.includes('任务 local-submit-failure'));
    assert.ok(localError.includes(`创建于 ${created}`));
    assert.ok(localError.includes('失败时间未记录'));
    assert.ok(!localError.includes('失败于'));
    await waitForPoll();
    assert.equal((await snapshot()).selectedId, 'local-submit-failure');
    assert.equal(await page.locator('.task-center-task-card').count(), 2); // Existing failed filter still applies.
    console.log('PASS return/repeat submit/category navigation; compatible failed filter preserved; local error ID and time fallback are truthful');

    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
    fs.mkdirSync(artifacts, { recursive: true });
    await page.screenshot({ path: path.join(artifacts, 'task-selection.png'), fullPage: true });
    fs.writeFileSync(path.join(artifacts, 'task-selection-evidence.json'), JSON.stringify({
      scope: 'Real Workbench/TaskCenter with intercepted API; no real backend/model execution',
      startedAt: new Date(startedAt).toISOString(), elapsedMs: Date.now() - startedAt,
      requests, checks, submissions, final: await snapshot(), errors, unexpected,
    }, null, 2));
  } catch (error) {
    fs.mkdirSync(artifacts, { recursive: true });
    await page.screenshot({ path: path.join(artifacts, 'task-selection-failure.png'), fullPage: true }).catch(() => {});
    fs.writeFileSync(path.join(artifacts, 'task-selection-failure.txt'), await page.locator('body').innerText().catch(() => 'page unavailable'));
    fs.writeFileSync(path.join(artifacts, 'task-selection-failure.json'), JSON.stringify({ errors, unexpected, requests, submissions }, null, 2));
    throw error;
  } finally { delayed.release(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
