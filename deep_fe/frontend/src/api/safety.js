const base = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');
let token;
let bootstrap;

async function capability() {
  if (token) return token;
  if (!bootstrap) bootstrap = fetch(`${base}/safety/bootstrap`, { headers: { 'X-EmotionLens-Client': 'local-ui' } })
    .then(async response => {
      if (!response.ok) throw new Error(['localhost', '127.0.0.1'].includes(window.location.hostname)
        ? 'Cannot connect to the local backend. Start FastAPI on 127.0.0.1:8000.'
        : 'Cannot connect to the detection service. Please try again shortly.');
      token = (await response.json()).capability;
      return token;
    }).finally(() => { bootstrap = null; });
  return bootstrap;
}

export async function safetyRequest(path, { method = 'GET', body, session, blob = false } = {}) {
  const headers = { 'X-Safety-Capability': await capability() };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (session) headers['X-Session-Capability'] = session.capability;
  let response;
  try { response = await fetch(`${base}/safety${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }); }
  catch { throw new Error('Backend disconnected. Monitoring is unavailable.'); }
  if (!response.ok) {
    if (response.status === 403) token = null;
    let data; try { data = await response.json(); } catch { data = {}; }
    throw new Error(typeof data.detail === 'string' ? data.detail : `Local API error (${response.status})`);
  }
  return blob ? response.blob() : response.json();
}

export function streamUrl(id) {
  const url = new URL(`${base}/safety/sessions/${id}/stream`, window.location.href);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.href;
}
