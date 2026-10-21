import { test, expect } from '@playwright/test';
import fs from 'node:fs';

async function tabTo(page, target) {
  await expect(target).toBeVisible();
  for (let i = 0; i < 80; i++) {
    if (await target.evaluate(element => element === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  await expect(target).toBeFocused();
}

async function setup(page, { keyboard = false } = {}) {
  const calls = [], frames = [], sockets = [];
  let actions = [];
  await page.addInitScript(() => {
    window.testStreams = [];
    const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    window.testGetUserMedia = get;
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await get(constraints); window.testStreams.push(stream); return stream;
    };
  });
  await page.route(url => url.pathname.startsWith('/safety/'), async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    calls.push({ path, method: request.method(), body: request.postDataJSON() });
    let body = {};
    if (path.endsWith('/bootstrap')) body = { capability: 'test-only-local-capability' };
    else if (path.endsWith('/status')) body = { ready: true, qualified: false, recording_available: true, recording_reason: 'VP8/WebM', recipient: 'Not configured', real_auto_calls_available: false, real_test_available: false };
    else if (path.endsWith('/events')) body = { items: [], total: 0 };
    else if (path.endsWith('/phone/actions')) body = { items: actions };
    else if (path.endsWith('/sessions') && request.method() === 'POST') body = { id: 'test-session', capability: 'test-session-capability' };
    else if (path.endsWith('/phone/test')) {
      actions = [{ id: 'test-action', mode: 'dry_run', state: 'countdown', due_at: Date.now()/1000 + 10 }];
      body = { action_id: 'test-action' };
    } else if (path.endsWith('/cancel')) { actions = []; }
    await route.fulfill({ json: body });
  });
  await page.routeWebSocket('**/safety/sessions/*/stream', socket => {
    sockets.push(socket);
    socket.onMessage(raw => {
      const message = JSON.parse(raw);
      if (message.capability) socket.send(JSON.stringify({ type: 'connected', state: 'disarmed' }));
      else if (message.jpeg) {
        frames.push(message);
        socket.send(JSON.stringify({ v: 1, state: 'monitoring', reason: 'No event detected', frame_id: message.frame_id,
          frame_age_ms: 20, processing_ms: 10, people: 0, tracks: [], dropped_frames: 0, tracking: 'insufficient_evidence' }));
      }
    });
  });
  await page.goto('/');
  const live = page.getByRole('button', { name: /Live Safety/ });
  if (keyboard) { await tabTo(page, live); await page.keyboard.press('Enter'); }
  else await live.click();
  return { calls, frames, sockets };
}

test('live frames, explicit arm, stop and tab cleanup', async ({ page }) => {
  const { calls, frames } = await setup(page);
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeDisabled();
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  expect(frames.length).toBe(0);
  await page.getByRole('button', { name: 'Arm monitoring' }).click();
  await expect.poll(() => frames.length).toBeGreaterThan(2);
  await expect(page.getByRole('button', { name: 'Disarm', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Disarm', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  await page.screenshot({ path: '../../data/ui-live-safety.png', fullPage: true });
  await page.getByRole('button', { name: /Incident History/ }).click();
  await expect.poll(() => page.evaluate(() => window.testStreams.flatMap(s => s.getTracks()).every(t => t.readyState === 'ended'))).toBe(true);
  await expect.poll(() => calls.some(c => c.method === 'DELETE' && c.path.endsWith('/test-session'))).toBe(true);
});

test('keyboard-only live controls, dry-run cancellation and incident review', async ({ page }) => {
  test.setTimeout(45000);
  const { calls, frames } = await setup(page, { keyboard: true });
  let events = [{ id: 'keyboard-event', created_at: Date.now() / 1000, source: 'live', status: 'closed',
    model_version: 'keyboard-fixture', score: .9, clip_status: 'ready', review_label: 'unreviewed', actions: [] }];
  await page.route(url => url.pathname.startsWith('/safety/events'), async route => {
    const request = route.request();
    if (new URL(request.url()).pathname.endsWith('/clip')) {
      await route.fulfill({ body: fs.readFileSync(new URL('../../../backend/tests/fixtures/black.webm', import.meta.url)), contentType: 'video/webm' });
    } else if (request.method() === 'PATCH') {
      events[0].review_label = request.postDataJSON().label;
      await route.fulfill({ json: events[0] });
    } else if (request.method() === 'DELETE') {
      events = [];
      await route.fulfill({ json: { deleted: true } });
    } else await route.fulfill({ json: { items: events, total: events.length } });
  });
  await tabTo(page, page.getByRole('combobox', { name: 'Camera', exact: true }));
  await page.keyboard.press('Home');
  const sound = page.getByLabel('Local alert sound');
  await tabTo(page, sound); await page.keyboard.press('Space');
  await expect(sound).toBeChecked();
  await page.keyboard.press('Space');
  const clips = page.getByLabel('Save event clips (opt in)');
  await tabTo(page, clips); await page.keyboard.press('Space');
  await expect(clips).toBeChecked();
  await tabTo(page, page.getByRole('combobox', { name: 'Phone mode', exact: true }));
  // Native select type-ahead works in macOS headless Chromium, where popup arrow keys do not.
  await page.keyboard.press('d'); await page.keyboard.press('Tab');
  await expect(page.getByRole('combobox', { name: 'Phone mode', exact: true })).toHaveValue('dry_run');
  await tabTo(page, page.getByRole('button', { name: 'Start camera' }));
  await page.keyboard.press('Enter');
  const arm = page.getByRole('button', { name: 'Arm monitoring' });
  await expect(arm).toBeEnabled();
  await tabTo(page, arm); await page.keyboard.press('Enter');
  await expect.poll(() => frames.length).toBeGreaterThan(2);
  await tabTo(page, page.getByRole('button', { name: 'Disarm', exact: true }));
  await page.keyboard.press('Enter');
  await expect(arm).toBeEnabled();
  await tabTo(page, page.getByRole('button', { name: 'Stop', exact: true }));
  await page.keyboard.press('Enter');
  await expect.poll(() => page.evaluate(() => window.testStreams.flatMap(s => s.getTracks()).every(t => t.readyState === 'ended'))).toBe(true);
  await tabTo(page, page.getByRole('button', { name: 'Test dry run' }));
  await page.keyboard.press('Enter');
  await tabTo(page, page.getByRole('button', { name: 'Cancel now', exact: true }));
  await page.keyboard.press('Enter');
  await expect.poll(() => calls.some(c => c.path.endsWith('/test-action/cancel'))).toBe(true);
  await expect(page.getByRole('button', { name: 'Send real test call' })).toBeDisabled();
  await tabTo(page, page.getByRole('button', { name: /Incident History/ }));
  await page.keyboard.press('Enter');
  const review = page.getByLabel('Review incident keyboard-event');
  await tabTo(page, review);
  await page.keyboard.press('r'); await page.keyboard.press('Tab');
  await expect(review).toHaveValue('relevant');
  await tabTo(page, page.getByRole('button', { name: 'Play clip' }));
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Incident clip')).toBeVisible();
  await tabTo(page, page.getByRole('button', { name: 'Close clip' }));
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Incident clip')).toHaveCount(0);
  await tabTo(page, page.getByRole('button', { name: 'Delete event and clip' }));
  await page.keyboard.press('Enter');
  await expect(page.getByText('No incidents recorded.')).toBeVisible();
  expect(calls.filter(c => c.path.endsWith('/phone/test')).every(c => c.body.mode === 'dry_run')).toBe(true);
});

test('permission denial recovers on explicit retry', async ({ page }) => {
  await setup(page);
  await page.evaluate(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Denied', 'NotAllowedError')); });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('alert')).toContainText('Camera permission denied');
  await page.evaluate(() => { navigator.mediaDevices.getUserMedia = window.testGetUserMedia; });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
});

test('hidden tab disarms and requires explicit rearming; disconnect releases camera', async ({ page }) => {
  const { frames, sockets } = await setup(page);
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  await page.getByRole('button', { name: 'Arm monitoring' }).click();
  await expect.poll(() => frames.length).toBeGreaterThan(0);
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: true, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: false, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
  await expect(page.getByRole('button', { name: 'Disarm', exact: true })).toBeDisabled();
  sockets[0].close();
  await expect(page.getByRole('alert')).toContainText('disconnected');
  await expect.poll(() => page.evaluate(() => window.testStreams.flatMap(s => s.getTracks()).every(t => t.readyState === 'ended'))).toBe(true);
});

test('phone dry-run countdown can be cancelled; real test stays unavailable', async ({ page }) => {
  const { calls } = await setup(page);
  await expect(page.getByRole('button', { name: 'Send real test call' })).toBeDisabled();
  await page.getByRole('button', { name: 'Test dry run' }).click();
  await expect(page.getByRole('button', { name: 'Cancel now' })).toBeVisible();
  await page.getByRole('button', { name: 'Cancel now' }).click();
  expect(calls.some(c => c.path.endsWith('/test-action/cancel'))).toBe(true);
  expect(calls.find(c => c.path.endsWith('/phone/test')).body.mode).toBe('dry_run');
});

test('OpenCV VP8 clip plays in Chromium', async ({ page }) => {
  const clip = fs.readFileSync(new URL('../../../backend/tests/fixtures/black.webm', import.meta.url));
  await page.route('**/fixture.webm', r => r.fulfill({ body: clip, contentType: 'video/webm' }));
  await page.goto('/');
  await page.evaluate(() => { const v = document.createElement('video'); v.id = 'codec-test'; v.src = '/fixture.webm'; v.muted = true; document.body.append(v); v.play(); });
  await expect.poll(() => page.locator('#codec-test').evaluate(v => v.currentTime)).toBeGreaterThan(.1);
});

test('stalled JPEG encoding disarms even while server heartbeats continue', async ({ page }) => {
  const { sockets, calls } = await setup(page);
  await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = () => {}; });
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  await page.getByRole('button', { name: 'Arm monitoring' }).click();
  const timer = setInterval(() => sockets[0].send(JSON.stringify({ type: 'heartbeat', state: 'monitoring', generation: 1 })), 200);
  try {
    await expect(page.getByRole('button', { name: 'Disarm', exact: true })).toBeDisabled();
    await expect(page.getByRole('status')).toContainText('Fresh inference stopped');
    await expect.poll(() => calls.some(c => c.path.endsWith('/disarm'))).toBe(true);
  } finally { clearInterval(timer); }
});

for (const interruption of ['stop', 'hide']) {
  test(`a delayed arm response cannot undo ${interruption}`, async ({ page }) => {
    const { frames, calls } = await setup(page);
    let release, arrived;
    const gate = new Promise(resolve => { release = resolve; });
    const requestArrived = new Promise(resolve => { arrived = resolve; });
    await page.route('**/safety/sessions/test-session/arm', async route => {
      arrived(); await gate; await route.fulfill({ json: { state: 'warming_up', generation: 1 } });
    });
    await page.getByRole('button', { name: 'Start camera' }).click();
    await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
    await page.getByRole('button', { name: 'Arm monitoring' }).click();
    await requestArrived;
    if (interruption === 'stop') await page.getByRole('button', { name: 'Stop', exact: true }).click();
    else await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { value: true, configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    release();
    await expect.poll(() => calls.filter(c => c.path.endsWith('/disarm')).length).toBeGreaterThan(interruption === 'hide' ? 1 : 0);
    await expect(page.getByRole('button', { name: 'Disarm', exact: true })).toBeDisabled();
    expect(frames.length).toBe(0);
    if (interruption === 'stop') {
      await expect.poll(() => page.evaluate(() => window.testStreams.flatMap(s => s.getTracks()).every(t => t.readyState === 'ended'))).toBe(true);
    }
  });
}

test('server disarm heartbeat clears active monitoring without a frame result', async ({ page }) => {
  const { sockets, frames } = await setup(page);
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  await page.getByRole('button', { name: 'Arm monitoring' }).click();
  await expect.poll(() => frames.length).toBeGreaterThan(0);
  sockets[0].send(JSON.stringify({ type: 'heartbeat', state: 'disarmed', generation: 100, reason: 'Fresh frames stopped; explicitly re-arm' }));
  await expect(page.getByRole('button', { name: 'Disarm', exact: true })).toBeDisabled();
  await expect(page.getByRole('status')).toContainText('Fresh frames stopped');
});

test('capture timestamp suppresses stale overlays despite a low server age', async ({ page }) => {
  const { sockets } = await setup(page);
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = () => {}; });
  await page.getByRole('button', { name: 'Arm monitoring' }).click();
  const captured = await page.evaluate(() => performance.now() - 800);
  sockets[0].send(JSON.stringify({ state: 'monitoring', captured_ms: captured, frame_age_ms: 1,
    tracks: [{ id: 1, box: [.1,.1,.5,.5], points: [[.2,.2,.9]] }] }));
  await expect(page.locator('svg rect')).toHaveCount(0);
});

test('incident storage failure does not hide a live local warning', async ({ page }) => {
  const { sockets } = await setup(page);
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  await page.getByRole('button', { name: 'Arm monitoring' }).click();
  await expect(page.getByRole('button', { name: 'Disarm', exact: true })).toBeEnabled();
  await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = () => {}; });
  await page.route('**/safety/phone/actions', route => route.fulfill({ status: 503, json: { detail: 'Local storage unavailable' } }));
  const timer = setInterval(() => sockets[0].send(JSON.stringify({ state: 'alert_active', reason: 'Incident storage failed', frame_age_ms: 10, tracks: [] })), 200);
  try {
    await expect(page.getByRole('alert')).toContainText('Local storage unavailable');
    await expect(page.getByRole('status')).toContainText('Possible striking motion');
  } finally { clearInterval(timer); }
});

test('Stop and Disarm close alert audio while preserving the sound preference', async ({ page }) => {
  await page.addInitScript(() => {
    const Native = window.AudioContext;
    window.testAudio = [];
    window.AudioContext = class extends Native {
      constructor(...args) { super(...args); window.testAudio.push(this); }
    };
  });
  await setup(page);
  await page.getByLabel('Local alert sound').check();
  expect(await page.evaluate(() => window.testAudio.length)).toBe(0);
  await page.getByRole('button', { name: 'Start camera' }).click();
  await expect(page.getByRole('button', { name: 'Arm monitoring' })).toBeEnabled();
  await page.getByRole('button', { name: 'Arm monitoring' }).click();
  await expect(page.getByRole('button', { name: 'Disarm', exact: true })).toBeEnabled();
  await expect.poll(() => page.evaluate(() => window.testAudio[0]?.state)).toBe('running');
  await page.getByRole('button', { name: 'Disarm', exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.testAudio[0]?.state)).toBe('closed');
  await page.getByRole('button', { name: 'Arm monitoring' }).click();
  await expect(page.getByRole('button', { name: 'Disarm', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.testAudio.every(c => c.state === 'closed'))).toBe(true);
  await expect(page.getByLabel('Local alert sound')).toBeChecked();
});
