import { test, expect } from '@playwright/test';

async function tabTo(page, target) {
  await expect(target).toBeVisible();
  for (let i = 0; i < 40; i++) {
    if (await target.evaluate(element => element === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  await expect(target).toBeFocused();
}

async function setup(page, model = 'test-model', { holdResponses = false, phoneEnabled = false, demoEnabled = false, phoneActions = [], responseDelayMs = 0 } = {}) {
  const calls = [], frames = [], sockets = [], pendingResults = [];
  let evidence = { state: 'monitoring', people: 0, tracks: [], tracking: 'insufficient_evidence' };
  await page.addInitScript(() => {
    window.testStreams = [];
    const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    window.testGetUserMedia = get;
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await get(constraints); window.testStreams.push(stream); return stream;
    };
  });
  await page.route(url => url.pathname.startsWith('/safety/'), async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    calls.push({ path, method: request.method(), body: request.postDataJSON(), headers: request.headers() });
    let body = {};
    const phoneStatus = { real_auto_calls_available: phoneEnabled, demo_auto_calls: demoEnabled, recipient: '•••• 7977', call_trigger_seconds: 1.5, call_grace_seconds: 10, call_max_per_hour: 3, call_cooldown_seconds: 300 };
    if (path.endsWith('/owner/status') && request.headers()['x-safety-owner'] !== 'owner-test-key') return route.fulfill({ status: 403, json: { detail: 'Owner call access code required' } });
    if (path.endsWith('/bootstrap')) body = { capability: 'test-local-capability' };
    else if (path.endsWith('/status')) body = { ...phoneStatus, ready: true, qualified: false, model, event_policy: { entry: .75, exit: .35, entry_seconds: .3, quiet_seconds: 2, cooldown: 30 } };
    else if (path.endsWith('/sessions') && request.method() === 'POST') body = { id: 'test-session', capability: 'test-session-capability', live_only: request.postDataJSON().live_only };
    else if (path.endsWith('/phone-actions')) body = { items: phoneActions, server_now: Date.now() / 1000 };
    else if (path.endsWith('/cancel')) { const action = phoneActions.find(a => path.includes(a.id)); if (action) action.state = 'cancelled'; }
    else if (path.endsWith('/arm')) body = { state: 'warming_up', generation: 1 };
    await route.fulfill({ json: body });
  });
  await page.routeWebSocket('**/safety/sessions/*/stream', socket => {
    sockets.push(socket);
    socket.onMessage(raw => {
      const message = JSON.parse(raw);
      if (message.capability) socket.send(JSON.stringify({ type: 'connected', state: 'disarmed' }));
      else if (message.jpeg) {
        frames.push(message);
        const response = JSON.stringify({ v: 1, frame_id: message.frame_id, captured_ms: message.captured_ms,
          frame_age_ms: 20, generation: 1, ...evidence });
        if (holdResponses) pendingResults.push({ socket, response });
        else if (responseDelayMs) setTimeout(() => socket.send(response), responseDelayMs);
        else socket.send(response);
      }
    });
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Start camera' })).toBeEnabled();
  return { calls, frames, sockets, setEvidence: value => { evidence = value; },
    releaseNext: () => { const next = pendingResults.shift(); next.socket.send(next.response); } };
}

const pair = [
  { id: 1, box: [.1, .15, .4, .9], points: Array.from({ length: 17 }, (_, i) => [.15 + (i % 2) * .2, .2 + i * .025, .95]) },
  { id: 2, box: [.6, .15, .9, .9], points: Array.from({ length: 17 }, (_, i) => [.65 + (i % 2) * .2, .2 + i * .025, .95]) },
];

test('slow tracking keeps the camera playing with at most four outstanding frames', async ({ page }) => {
  const { frames, releaseNext } = await setup(page, 'test-model', { holdResponses: true });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => frames.length).toBe(4);
  const before = await page.locator('video').evaluate(video => video.currentTime);
  await page.waitForTimeout(250);
  expect(frames).toHaveLength(4);
  expect(await page.locator('video').evaluate(video => video.currentTime)).toBeGreaterThan(before);
  releaseNext();
  await expect.poll(() => frames.length).toBe(5);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
});

async function stopped(page) {
  await expect.poll(() => page.evaluate(() => window.testStreams.flatMap(s => s.getTracks()).every(t => t.readyState === 'ended'))).toBe(true);
}

test('simple feed starts detection in one step, with no history or phone controls', async ({ page }) => {
  const { calls, frames } = await setup(page);
  await expect(page.getByText('Incident History', { exact: false })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Arm|Disarm|Test dry run|Send real/ })).toHaveCount(0);
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => frames.length).toBeGreaterThan(2);
  await expect(page.getByRole('status')).toContainText('Waiting for two people');
  expect(calls.find(c => c.path.endsWith('/sessions')).body).toEqual({ source: 'live', live_only: true });
  const arm = calls.find(c => c.path.endsWith('/arm'));
  expect(arm.body).toMatchObject({ phone_mode: 'off', clips: false });
  expect(arm.body.client_now_ms).toBeGreaterThan(0);
  expect(calls.some(c => /\/events|\/phone/.test(c.path))).toBe(false);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await stopped(page);
  await expect(page.getByRole('status')).toContainText('Camera off');
});

test('two distinct people are labeled and possible hitting is displayed on the live feed', async ({ page }) => {
  const { setEvidence } = await setup(page);
  setEvidence({ state: 'monitoring', people: 2, tracks: pair, tracking: 'observed' });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByText('Person 1', { exact: true })).toBeVisible();
  await expect(page.getByText('Person 2', { exact: true })).toBeVisible();
  await expect(page.locator('svg rect[data-track-id]')).toHaveCount(2);
  await expect(page.getByRole('status')).toContainText('2 people tracked');
  await expect(page.getByRole('status')).toContainText('No hitting motion detected');
  setEvidence({ state: 'alert_active', people: 2, tracks: pair, tracking: 'observed', interaction_track_ids: [1, 2] });
  await expect(page.getByRole('status')).toContainText('Possible hit detected');
  await expect(page.locator('rect[data-track-id="1"]')).toHaveAttribute('stroke', '#f87171');
  await page.screenshot({ path: '../../data/ui-live-safety-simple.png', fullPage: true });
  setEvidence({ state: 'warming_up', people: 2, tracks: pair, tracking: 'insufficient_evidence' });
  await expect(page.getByRole('status')).toContainText('Getting a clear view');
  await expect(page.getByText('Possible hit detected', { exact: false })).toHaveCount(0);
});

test('a single pose explains framing instead of implying two people are tracked', async ({ page }) => {
  const { setEvidence } = await setup(page);
  setEvidence({ state: 'warming_up', people: 1, tracks: pair.slice(0, 1), tracking: 'insufficient_evidence',
    reason: 'Keep both shoulders, elbows and wrists visible; move farther from the camera' });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('status')).toContainText('Only one person tracked');
  await expect(page.getByRole('status')).toContainText('Move farther back so both people fit in the camera frame');
  await expect(page.locator('svg rect[data-track-id]')).toHaveCount(1);
  await expect(page.getByRole('status')).not.toContainText('No hitting motion detected');
  await expect(page.getByRole('status')).not.toContainText('Possible hit detected');
});

test('camera start, stop and view cleanup work by keyboard', async ({ page }) => {
  const { calls, frames } = await setup(page);
  await tabTo(page, page.getByRole('combobox', { name: 'Camera', exact: true }));
  await tabTo(page, page.getByRole('button', { name: 'Start camera' }));
  await page.keyboard.press('Enter');
  await expect.poll(() => frames.length).toBeGreaterThan(0);
  await tabTo(page, page.getByRole('button', { name: 'Stop', exact: true }));
  await page.keyboard.press('Enter');
  await stopped(page);
  await tabTo(page, page.getByRole('button', { name: 'Start camera' }));
  await page.keyboard.press('Enter');
  await expect.poll(() => calls.filter(c => c.path.endsWith('/arm')).length).toBe(2);
  await tabTo(page, page.getByRole('button', { name: /Upload Image/ }));
  await page.keyboard.press('Enter');
  await stopped(page);
});

test('permission denial recovers on explicit retry', async ({ page }) => {
  const { frames } = await setup(page);
  await page.evaluate(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Denied', 'NotAllowedError')); });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('alert')).toContainText('Camera permission denied');
  await page.evaluate(() => { navigator.mediaDevices.getUserMedia = window.testGetUserMedia; });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => frames.length).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await stopped(page);
});

test('hidden tabs pause detection; visible tabs need Resume; disconnect releases camera', async ({ page }) => {
  const { frames, sockets, calls } = await setup(page);
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => frames.length).toBeGreaterThan(0);
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: true, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
  await expect(page.getByRole('button', { name: 'Resume detection' })).toBeVisible();
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: false, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
  expect(calls.filter(c => c.path.endsWith('/arm')).length).toBe(1);
  await page.getByRole('button', { name: 'Resume detection' }).click();
  await expect.poll(() => calls.filter(c => c.path.endsWith('/arm')).length).toBe(2);
  sockets[0].close();
  await expect(page.getByRole('alert')).toContainText('disconnected');
  await stopped(page);
});

test('stalled JPEG encoding pauses despite server heartbeats', async ({ page }) => {
  const { sockets, calls } = await setup(page);
  await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = () => {}; });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => calls.some(c => c.path.endsWith('/arm'))).toBe(true);
  const timer = setInterval(() => sockets[0].send(JSON.stringify({ type: 'heartbeat', state: 'monitoring', generation: 1 })), 200);
  try {
    await expect(page.getByRole('button', { name: 'Resume detection' })).toBeVisible();
    await expect(page.getByRole('status')).toContainText('Fresh inference stopped');
  } finally { clearInterval(timer); }
});

for (const interruption of ['stop', 'hide']) {
  test(`a delayed detection start cannot undo ${interruption}`, async ({ page }) => {
    const { frames, calls } = await setup(page);
    let release, arrived;
    const gate = new Promise(resolve => { release = resolve; });
    const requestArrived = new Promise(resolve => { arrived = resolve; });
    await page.route('**/safety/sessions/test-session/arm', async route => {
      arrived(); await gate; await route.fulfill({ json: { state: 'warming_up', generation: 1 } });
    });
    await page.getByRole('button', { name: 'Start camera' }).click();
    await requestArrived;
    if (interruption === 'stop') await page.getByRole('button', { name: 'Stop', exact: true }).click();
    else await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: true, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
    release();
    await expect.poll(() => calls.filter(c => c.path.endsWith('/disarm')).length).toBeGreaterThan(interruption === 'hide' ? 1 : 0);
    expect(frames.length).toBe(0);
    if (interruption === 'stop') await stopped(page);
    else await expect(page.getByRole('button', { name: 'Resume detection' })).toBeVisible();
  });
}

test('server pause clears live overlays without a new frame', async ({ page }) => {
  const { sockets, frames, setEvidence } = await setup(page);
  setEvidence({ state: 'monitoring', people: 2, tracks: pair, tracking: 'observed' });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => frames.length).toBeGreaterThan(0);
  sockets[0].send(JSON.stringify({ type: 'heartbeat', state: 'disarmed', generation: 100, reason: 'Fresh frames stopped' }));
  await expect(page.getByRole('button', { name: 'Resume detection' })).toBeVisible();
  await expect(page.locator('svg rect')).toHaveCount(0);
});

test('old capture timestamps hide tracks and hit warnings despite a low server age', async ({ page }) => {
  const { frames, setEvidence } = await setup(page);
  const captured = await page.evaluate(() => performance.now() - 1300);
  setEvidence({ state: 'alert_active', captured_ms: captured, frame_age_ms: 1,
    people: 2, tracks: pair, tracking: 'observed' });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => frames.length).toBeGreaterThan(0);
  await expect(page.getByRole('status')).toContainText('Waiting for fresh video');
  await expect(page.locator('svg rect')).toHaveCount(0);
  await expect(page.getByRole('status')).not.toContainText('Possible hit detected');
});

test('live accuracy trials score detected hits and false alerts, then export operator-confirmed results', async ({ page }) => {
  test.setTimeout(35000);
  const { calls, setEvidence } = await setup(page);
  setEvidence({ state: 'monitoring', people: 2, tracks: pair, tracking: 'observed' });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('status')).toContainText('No hitting motion detected');
  await page.getByRole('button', { name: 'Test detection accuracy' }).click();
  const panel = page.getByRole('region', { name: 'Live accuracy test' });
  await expect(panel.getByTestId('trial-accuracy')).toHaveText('—');
  await panel.getByRole('button', { name: 'Start trial', exact: true }).click();
  await expect(page.getByText(/^MOVE NOW ·/)).toBeVisible();
  setEvidence({ state: 'alert_active', people: 2, tracks: pair, tracking: 'observed' });
  await expect(panel.getByText('Detector result: alert observed')).toBeVisible({ timeout: 10000 });
  // An automatic observation cannot become human ground truth until confirmed.
  await expect(panel.getByTestId('hit-recall')).toHaveText('—');
  await panel.getByRole('button', { name: 'Confirm action & save' }).click();
  await expect(panel.getByTestId('hit-recall')).toHaveText('100%');
  await expect(panel.getByTestId('trial-accuracy')).toHaveText('—');
  setEvidence({ state: 'monitoring', people: 2, tracks: pair, tracking: 'observed' });
  await expect(page.getByRole('status')).toContainText('No hitting motion detected');
  await panel.getByRole('combobox', { name: 'Trial action' }).selectOption('normal');
  await panel.getByRole('button', { name: 'Start trial', exact: true }).click();
  await expect(page.getByText(/^MOVE NOW ·/)).toBeVisible();
  setEvidence({ state: 'alert_active', people: 2, tracks: pair, tracking: 'observed' });
  await expect(panel.getByText('Detector result: alert observed')).toBeVisible({ timeout: 10000 });
  await panel.getByRole('button', { name: 'Confirm action & save' }).click();
  await expect(panel.getByTestId('alert-precision')).toHaveText('50%');
  await expect(panel.getByTestId('trial-accuracy')).toHaveText('50%');
  await expect(panel.getByTestId('accuracy-counts')).toContainText('False alerts: 1');
  const downloadPromise = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Export test results' }).click();
  const download = await downloadPromise;
  const { readFile } = await import('node:fs/promises');
  const report = JSON.parse(await readFile(await download.path(), 'utf8'));
  expect(report.summary).toMatchObject({ true_positive: 1, false_positive: 1, scored_trials: 2, accuracy: .5 });
  expect(report.detector).toMatchObject({ model: 'test-model', event_policy: { cooldown: 0 } });
  expect(report.trials).toHaveLength(2);
  expect(report.trials.every(t => t.inference_frames > 0 && t.tracking_coverage > .5)).toBe(true);
  expect(calls.some(c => /\/events|\/phone/.test(c.path))).toBe(false);
});

test('stopped accuracy trials are unscored and cannot inflate accuracy', async ({ page }) => {
  const { setEvidence } = await setup(page);
  setEvidence({ state: 'monitoring', people: 2, tracks: pair, tracking: 'observed' });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('status')).toContainText('No hitting motion detected');
  await page.getByRole('button', { name: 'Test detection accuracy' }).click();
  const panel = page.getByRole('region', { name: 'Live accuracy test' });
  await panel.getByRole('button', { name: 'Start trial', exact: true }).click();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(panel.getByText('Trial not scored', { exact: true })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Confirm action & save' })).toHaveCount(0);
  await panel.getByRole('button', { name: 'Dismiss & retry' }).click();
  await expect(panel.getByTestId('accuracy-counts')).toContainText('Unscored: 1');
  await expect(panel.getByTestId('trial-accuracy')).toHaveText('—');
});

test('stale or insufficient tracking cannot start an accuracy trial', async ({ page }) => {
  await setup(page);
  await page.getByRole('button', { name: 'Start camera' }).click();
  await page.getByRole('button', { name: 'Test detection accuracy' }).click();
  const panel = page.getByRole('region', { name: 'Live accuracy test' });
  await panel.getByRole('button', { name: 'Start trial', exact: true }).click();
  await expect(panel.getByText('Wait for exactly two clearly tracked people and let the previous alert clear.')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Cancel trial' })).toHaveCount(0);
});

test('visual trials show hold-still timing and score a delayed model response', async ({ page }) => {
  test.setTimeout(30000);
  const { calls, setEvidence } = await setup(page, 'learned-video-s3d-strike-v1 (experimental)');
  setEvidence({ state: 'monitoring', people: 2, tracks: pair, tracking: 'observed' });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('status')).toContainText('No hitting motion detected');
  await page.getByRole('button', { name: 'Test detection accuracy' }).click();
  const panel = page.getByRole('region', { name: 'Live accuracy test' });
  await expect(panel.getByText(/4-second countdown/)).toBeVisible();
  await panel.getByRole('button', { name: 'Start trial', exact: true }).click();
  await expect(page.getByText(/^Get ready · 4$/)).toBeVisible();
  await expect(page.getByText(/^MOVE NOW ·/)).toBeVisible({ timeout: 6000 });
  await expect(page.getByText(/^Hold still ·/)).toBeVisible({ timeout: 8000 });
  setEvidence({ state: 'alert_active', people: 2, tracks: pair, tracking: 'observed' });
  await expect(panel.getByText('Detector result: alert observed')).toBeVisible({ timeout: 4000 });
  await panel.getByRole('button', { name: 'Confirm action & save' }).click();
  await expect(panel.getByTestId('hit-recall')).toHaveText('100%');
  expect(calls.some(c => /\/events|\/phone/.test(c.path))).toBe(false);
});


test('owner enables calls, sees countdown and cancels without exposing the access code in payloads', async ({ page }) => {
  const phoneActions = [];
  const { calls, setEvidence } = await setup(page, 'test-model', { phoneEnabled: true, phoneActions });
  const panel = page.getByRole('region', { name: 'Phone alerts', exact: true });
  await panel.getByLabel('Owner call access code').fill('wrong');
  await panel.getByRole('button', { name: /Enable calls to/ }).click();
  await expect(panel.getByRole('alert')).toContainText('Owner call access code required');
  await panel.getByLabel('Owner call access code').fill('owner-test-key');
  await panel.getByRole('button', { name: /Enable calls to/ }).click();
  await expect(panel.getByRole('heading')).toHaveText('Phone alerts enabled');
  await expect(page.getByRole('button', { name: 'Test detection accuracy' })).toHaveCount(0);
  setEvidence({ state: 'candidate', people: 2, tracks: pair, tracking: 'observed', candidate_seconds: .3, call_candidate_seconds: .8 });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(panel.getByText(/Sustained detection: 0.8/)).toBeVisible();
  expect(calls.find(c => c.path.endsWith('/sessions')).body.live_only).toBe(false);
  const arm = calls.find(c => c.path.endsWith('/arm'));
  expect(arm.body).toMatchObject({ phone_mode: 'real', clips: false, recipient_acknowledged: true });
  expect(arm.headers['x-safety-owner']).toBe('owner-test-key');
  expect(JSON.stringify(arm.body)).not.toContain('owner-test-key');
  phoneActions.push({ id: 'owner-action', state: 'countdown', due_at: Date.now() / 1000 + 10 });
  await expect(panel.getByText(/Calling in/)).toBeVisible();
  await panel.getByRole('button', { name: 'Cancel call' }).click();
  await expect(panel.getByText(/Call cancelled/)).toBeVisible();
  expect(calls.some(c => c.path.endsWith('/phone-actions/owner-action/cancel'))).toBe(true);
  await panel.getByRole('button', { name: 'Disable calls and stop camera' }).click();
  await stopped(page);
  await expect(panel.getByLabel('Owner call access code')).toHaveValue('');
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => calls.filter(c => c.path.endsWith('/arm')).length).toBe(2);
  expect(calls.filter(c => c.path.endsWith('/arm'))[1].body.phone_mode).toBe('off');
});

test('phone-status failure pauses monitoring and pending calls', async ({ page }) => {
  await setup(page, 'test-model', { phoneEnabled: true });
  await page.getByLabel('Owner call access code').fill('owner-test-key');
  await page.getByRole('button', { name: /Enable calls to/ }).click();
  await expect(page.getByRole('heading', { name: 'Phone alerts enabled' })).toBeVisible();
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('status')).toContainText('Waiting for two people');
  await page.route('**/safety/sessions/test-session/phone-actions', route => route.fulfill({ status: 503, json: { detail: 'Phone status unavailable' } }));
  await expect(page.getByRole('button', { name: 'Resume detection' })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('Phone status unavailable');
});


test('demo starts with real calls enabled and no code or extra activation', async ({ page }) => {
  const phoneActions = [];
  const { calls } = await setup(page, 'test-model', { phoneEnabled: true, demoEnabled: true, phoneActions });
  const panel = page.getByRole('region', { name: 'Phone alerts', exact: true });
  await expect(panel.getByRole('heading')).toHaveText('Phone alerts enabled');
  await expect(page.getByLabel('Owner call access code')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Enable calls to/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => calls.some(c => c.path.endsWith('/arm'))).toBe(true);
  expect(calls.find(c => c.path.endsWith('/sessions')).body.live_only).toBe(false);
  const arm = calls.find(c => c.path.endsWith('/arm'));
  expect(arm.body).toMatchObject({ phone_mode: 'real', recipient_acknowledged: true, clips: false });
  expect(arm.headers['x-safety-owner']).toBeUndefined();
  expect(calls.some(c => c.path.endsWith('/owner/status'))).toBe(false);
  phoneActions.push({ id: 'demo-action', state: 'countdown', due_at: Date.now() / 1000 + 10 });
  await expect(panel.getByText(/Calling in/)).toBeVisible();
  await panel.getByRole('button', { name: 'Cancel call' }).click();
  await expect(panel.getByText(/Call cancelled/)).toBeVisible();
  await panel.getByRole('button', { name: 'Disable calls and stop camera' }).click();
  await stopped(page);
  await expect(panel.getByRole('button', { name: 'Enable demo calls' })).toBeVisible();
  await panel.getByRole('button', { name: 'Enable demo calls' }).click();
  await expect(panel.getByRole('heading')).toHaveText('Phone alerts enabled');
});


test('cloud results taking 650 ms still display tracks and alerts', async ({ page }) => {
  const { frames, setEvidence } = await setup(page, 'test-model', { responseDelayMs: 650 });
  setEvidence({ state: 'alert_active', people: 2, tracks: pair, tracking: 'observed', interaction_track_ids: [1, 2] });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('status')).toContainText('Possible hit detected');
  await expect(page.locator('svg rect[data-track-id]')).toHaveCount(2);
  await expect.poll(() => frames.length).toBeGreaterThan(5);
  await expect(page.getByRole('status')).toContainText('Possible hit detected');
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
});


test('a result expires one second after capture even when results keep arriving', async ({ page }) => {
  const { frames, setEvidence } = await setup(page);
  const captured = await page.evaluate(() => performance.now());
  setEvidence({ state: 'alert_active', captured_ms: captured, people: 2, tracks: pair, tracking: 'observed' });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('status')).toContainText('Possible hit detected');
  await expect.poll(() => frames.length).toBeGreaterThan(5);
  await expect(page.getByRole('status')).toContainText('Waiting for fresh video');
  await expect(page.locator('svg rect')).toHaveCount(0);
});


test('demo automatically recovers a timestamp pause without a resume click', async ({ page }) => {
  const { sockets, calls, frames, setEvidence } = await setup(page, 'test-model', { phoneEnabled: true, demoEnabled: true });
  setEvidence({ state: 'monitoring', people: 2, tracks: pair, tracking: 'observed' });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('status')).toContainText('No hitting motion detected');
  sockets[0].send(JSON.stringify({ type: 'heartbeat', state: 'disarmed', generation: 100, reason: 'Stale or inconsistent capture timestamps; explicitly re-arm' }));
  await expect.poll(() => calls.filter(c => c.path.endsWith('/arm')).length).toBe(2);
  await expect(page.getByRole('status')).toContainText('No hitting motion detected');
  expect(calls.filter(c => c.path.endsWith('/arm'))[1].body.phone_mode).toBe('real');
  await expect.poll(() => frames.length).toBeGreaterThan(5);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await stopped(page);
});


test('stopping the demo cancels automatic timestamp recovery', async ({ page }) => {
  const { sockets, calls } = await setup(page, 'test-model', { phoneEnabled: true, demoEnabled: true });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => calls.filter(c => c.path.endsWith('/arm')).length).toBe(1);
  sockets[0].send(JSON.stringify({ type: 'heartbeat', state: 'disarmed', generation: 100, reason: 'Stale or inconsistent capture timestamps' }));
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await page.waitForTimeout(700);
  expect(calls.filter(c => c.path.endsWith('/arm'))).toHaveLength(1);
  await stopped(page);
});


test('a newer server result releases skipped frames instead of stalling capture', async ({ page }) => {
  const { frames, sockets } = await setup(page, 'test-model', { holdResponses: true });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => frames.length).toBe(4);
  const latest = frames[3];
  sockets[0].send(JSON.stringify({ v: 1, frame_id: latest.frame_id, captured_ms: latest.captured_ms, generation: 1,
    state: 'monitoring', tracking: 'observed', people: 2, tracks: pair }));
  await expect.poll(() => frames.length).toBe(8);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
});


test('demo tolerates delayed first cloud results while the local camera keeps playing', async ({ page }) => {
  const { frames } = await setup(page, 'test-model', { holdResponses: true, phoneEnabled: true, demoEnabled: true });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect.poll(() => frames.length).toBe(4);
  await page.waitForTimeout(1800);
  await expect(page.getByRole('button', { name: 'Resume detection' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await stopped(page);
});


test('Start camera in demo mode replaces an abandoned session without a stop prompt', async ({ page }) => {
  const { calls,frames }=await setup(page,'test-model',{phoneEnabled:true,demoEnabled:true});
  await page.route('**/safety/sessions',async route=>{
    if (!route.request().postDataJSON().replace_existing) return route.fulfill({status:409,json:{detail:'A camera session is already active. Stop it first.'}});
    await route.fulfill({status:201,json:{id:'test-session',capability:'test-session-capability',live_only:false}});
  });
  await page.getByRole('button',{name:'Start camera'}).click();
  await expect.poll(()=>frames.length).toBeGreaterThan(0);
  expect(calls.find(c=>c.path.endsWith('/arm')).body.phone_mode).toBe('real');
  await expect(page.getByText('A camera session is already active. Stop it first.')).toHaveCount(0);
  await page.getByRole('button',{name:'Stop',exact:true}).click();
});


test('demo keeps recent observed boxes through cloud latency without showing a stale hit alert', async ({ page }) => {
  const {setEvidence}=await setup(page,'test-model',{phoneEnabled:true,demoEnabled:true,responseDelayMs:1200});
  setEvidence({state:'alert_active',people:2,tracks:pair,tracking:'observed',interaction_track_ids:[1,2]});
  await page.getByRole('button',{name:'Start camera'}).click();
  await expect(page.getByRole('status')).toContainText('Video delayed; showing latest tracking');
  await expect(page.locator('svg rect[data-track-id]')).toHaveCount(2);
  await expect(page.getByRole('status')).not.toContainText('Possible hit detected');
  await page.getByRole('button',{name:'Stop',exact:true}).click();
});


test('demo uses smaller JPEG frames and a steady upload rate', async ({ page }) => {
  const {frames}=await setup(page,'test-model',{phoneEnabled:true,demoEnabled:true});
  await page.getByRole('button',{name:'Start camera'}).click();
  await expect.poll(()=>frames.length).toBeGreaterThan(3);
  const size=await page.evaluate(async jpeg=>{
    const image=await createImageBitmap(await (await fetch('data:image/jpeg;base64,'+jpeg)).blob());
    return {width:image.width,height:image.height};
  },frames[0].jpeg);
  expect(size.width).toBeLessThanOrEqual(384);
  expect(size.height).toBeLessThanOrEqual(288);
  for (let i=1;i<4;i++) expect(frames[i].captured_ms-frames[i-1].captured_ms).toBeGreaterThanOrEqual(120);
  await page.getByRole('button',{name:'Stop',exact:true}).click();
});
