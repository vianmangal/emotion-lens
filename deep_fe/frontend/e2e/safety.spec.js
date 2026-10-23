import { test, expect } from '@playwright/test';

async function tabTo(page, target) {
  await expect(target).toBeVisible();
  for (let i = 0; i < 40; i++) {
    if (await target.evaluate(element => element === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  await expect(target).toBeFocused();
}

async function setup(page) {
  const calls = [], frames = [], sockets = [];
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
    calls.push({ path, method: request.method(), body: request.postDataJSON() });
    let body = {};
    if (path.endsWith('/bootstrap')) body = { capability: 'test-local-capability' };
    else if (path.endsWith('/status')) body = { ready: true, qualified: false, model: 'test-model', event_policy: { entry: .75, exit: .35, entry_seconds: .3, quiet_seconds: 2, cooldown: 30 } };
    else if (path.endsWith('/sessions') && request.method() === 'POST') body = { id: 'test-session', capability: 'test-session-capability', live_only: true };
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
        socket.send(JSON.stringify({ v: 1, frame_id: message.frame_id, captured_ms: message.captured_ms,
          frame_age_ms: 20, generation: 1, ...evidence }));
      }
    });
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Start camera' })).toBeEnabled();
  return { calls, frames, sockets, setEvidence: value => { evidence = value; } };
}

const pair = [
  { id: 1, box: [.1, .15, .4, .9], points: Array.from({ length: 17 }, (_, i) => [.15 + (i % 2) * .2, .2 + i * .025, .95]) },
  { id: 2, box: [.6, .15, .9, .9], points: Array.from({ length: 17 }, (_, i) => [.65 + (i % 2) * .2, .2 + i * .025, .95]) },
];

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
  const captured = await page.evaluate(() => performance.now() - 800);
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
