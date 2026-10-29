import { useEffect, useState } from 'react';
import useSafetySession from '../hooks/useSafetySession';
import { safetyRequest } from '../api/safety';
import LiveAccuracyTest from '../components/safety/LiveAccuracyTest';
import PhoneAlerts from '../components/safety/PhoneAlerts';

const DETECTION_OPTIONS = { phone_mode: 'off', clips: false };
const MAX_VIDEO_AGE_MS = 1000;
const captureAge = result => Number.isFinite(result?.captured_ms)
  ? Math.max(0, performance.now() - result.captured_ms)
  : Infinity;
const BONES = [[0, 1], [0, 2], [1, 3], [2, 4], [5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];

export default function LiveSafety() {
  const session = useSafetySession();
  const [status, setStatus] = useState(null), [error, setError] = useState('');
  const [device, setDevice] = useState(''), [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState(false);
  const [overlayFresh, setOverlayFresh] = useState(false);
  const [testCue, setTestCue] = useState(null);
  const [ownerKey, setOwnerKey] = useState('');
  const [demoCallsDisabled, setDemoCallsDisabled] = useState(false);
  const callsEnabled = Boolean(ownerKey || (status?.demo_auto_calls && !demoCallsDisabled));
  const detectionOptions = callsEnabled ? { phone_mode: 'real', clips: false, recipient_acknowledged: true } : DETECTION_OPTIONS;
  const recoverablePause = Boolean(status?.demo_auto_calls && session.camera && !session.armed &&
    /stale|inconsistent capture|capture clock|frame gap|fresh frames stopped|fresh inference stopped/i.test(session.result?.reason || ''));
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const result = await safetyRequest('/status');
        if (mounted) { setStatus(result); setError(''); }
      } catch (e) { if (mounted) { setStatus(null); setError(e.message); } }
    };
    load(); const timer = setInterval(load, 1000);
    return () => { mounted = false; clearInterval(timer); };
  }, []);
  useEffect(() => {
    const age = captureAge(session.result);
    const remaining = MAX_VIDEO_AGE_MS - age;
    const overlayRemaining = (status?.demo_auto_calls ? 2000 : MAX_VIDEO_AGE_MS) - age;
    setFresh(remaining > 0);
    setOverlayFresh(overlayRemaining > 0);
    const timer = setTimeout(() => setFresh(false), Math.max(0, remaining));
    const overlayTimer = setTimeout(() => setOverlayFresh(false), Math.max(0, overlayRemaining));
    return () => { clearTimeout(timer); clearTimeout(overlayTimer); };
  }, [session.result, status?.demo_auto_calls]);

  const start = async () => {
    setBusy(true);
    try { if (await session.start(device, !callsEnabled, Boolean(status?.demo_auto_calls))) await session.arm(detectionOptions, ownerKey); }
    finally { setBusy(false); }
  };
  const resume = async () => {
    setBusy(true);
    try { await session.arm(detectionOptions, ownerKey); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    if (!recoverablePause || busy || document.hidden) return;
    const timer = setTimeout(() => { if (!document.hidden) resume(); }, 500);
    return () => clearTimeout(timer);
  }, [recoverablePause, busy, session.result?.reason, callsEnabled, ownerKey]);
  const current = session.result;
  const isFresh = session.armed && fresh && captureAge(current) < MAX_VIDEO_AGE_MS;
  const showTracking = session.armed && overlayFresh && captureAge(current) < (status?.demo_auto_calls ? 2000 : MAX_VIDEO_AGE_MS);
  const tracks = showTracking ? current.tracks || [] : [];
  const detected = isFresh && tracks.length >= 2 && current.tracking === 'observed' && current.state === 'alert_active';
  const paused = session.camera && !session.armed && !busy;
  let message = 'Camera off';
  if (busy || session.starting) message = 'Starting detection…';
  else if (paused) message = recoverablePause ? 'Recovering video…' : 'Detection paused';
  else if (session.armed && !isFresh) message = showTracking ? 'Video delayed; showing latest tracking…' : 'Waiting for fresh video…';
  else if (session.armed && tracks.length < 2) message = tracks.length === 1 ? 'Only one person tracked' : 'Waiting for two people';
  else if (session.armed && current.tracking !== 'observed') message = current.reason?.startsWith('Warming up action analysis') ? 'Warming up action analysis…' : current.reason?.startsWith('Video arriving too slowly') ? 'Video connection too slow' : current.reason?.startsWith('Waiting for fresh action analysis') ? 'Analyzing movement…' : 'Getting a clear view…';
  else if (detected) message = '⚠ Possible hit detected';
  else if (session.armed && current.state === 'candidate') message = 'Checking movement…';
  else if (session.armed) message = 'No hitting motion detected';

  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-2xl font-semibold">Live Safety</h1><p className="mt-1 text-sm text-zinc-400">Live tracking and hit detection for two people.</p></div>
      <span className="rounded-full border border-zinc-800 px-3 py-1 text-xs text-zinc-500">Experimental</span>
    </div>
    {(session.error || error) && <p role="alert" className="safety-error">{session.error || error}</p>}
    {status && !status.ready && <p role="alert" className="safety-error">Detection unavailable. Check the local model setup.</p>}
    <section className="overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950" aria-label="Live camera and detection">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 p-3 sm:px-4">
        <label className="flex items-center gap-2 text-xs text-zinc-400">Camera
          <select aria-label="Camera" value={device} disabled={session.camera || session.starting || busy} onChange={e => setDevice(e.target.value)}>
            <option value="">Default camera</option>{session.devices.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
          </select>
        </label>
        <div className="flex gap-2">
          {!session.camera && <button className="safety-button safety-primary" disabled={busy || session.starting || !status?.ready} onClick={start}>{busy || session.starting ? 'Starting…' : 'Start camera'}</button>}
          {paused && <button className="safety-button safety-primary" disabled={!status?.ready} onClick={resume}>Resume detection</button>}
          <button className="safety-button" disabled={!session.camera && !session.starting && !busy} onClick={() => session.stop()}>Stop</button>
        </div>
      </div>
      <div className="flex justify-center bg-black"><div className="relative w-full" style={{ aspectRatio: session.aspect, maxWidth: `${60 * session.aspect}vh` }}>
        <video ref={session.videoRef} autoPlay muted playsInline className="h-full w-full object-contain" style={{ transform: 'scaleX(-1)' }} aria-label="Local camera preview" />
        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none" role="img" aria-label="Tracked people">
          {tracks.map(track => {
            const involved = detected && current.interaction_track_ids?.includes(track.id);
            const color = involved ? '#f87171' : track.id % 2 ? '#67e8f9' : '#86efac';
            return <g key={track.id}>
              <g transform="translate(1 0) scale(-1 1)">
                <rect data-track-id={track.id} x={track.box[0]} y={track.box[1]} width={track.box[2] - track.box[0]} height={track.box[3] - track.box[1]} rx=".012" fill="none" stroke={color} strokeWidth=".004" />
                {BONES.map(([a, b]) => track.points[a]?.[2] > .55 && track.points[b]?.[2] > .55 && <line key={`${a}-${b}`} x1={track.points[a][0]} y1={track.points[a][1]} x2={track.points[b][0]} y2={track.points[b][1]} stroke={color} strokeWidth=".003" />)}
                {track.points.map((point, i) => point[2] > .55 && <circle key={i} cx={point[0]} cy={point[1]} r=".005" fill={color} />)}
              </g>
              <text x={1 - track.box[2] + .008} y={Math.max(.035, track.box[1] - .014)} fill={color} stroke="#09090b" strokeWidth=".007" paintOrder="stroke" fontSize=".026" fontWeight="600">Person {track.id}</text>
            </g>;
          })}
        </svg>
        {testCue && <div className="pointer-events-none absolute inset-x-0 top-3 text-center"><span className="inline-block rounded-xl bg-black/85 px-4 py-2 text-lg font-bold text-cyan-200" aria-live="polite">{testCue}</span></div>}
        {!session.camera && <div className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-zinc-500">{busy || session.starting ? 'Opening camera…' : 'Start the camera to track both people.'}</div>}
      </div></div>
      <div role="status" aria-live="polite" className={`flex flex-wrap items-center justify-between gap-2 border-t p-4 ${detected ? 'border-red-900 bg-red-950/60 text-red-200' : 'border-zinc-800 text-zinc-300'}`}>
        <div><p className="font-semibold">{message}</p>{paused && <p className="mt-1 text-xs text-zinc-400">{current?.reason?.replaceAll('re-arm', 'resume detection') || 'Click Resume detection to continue.'}</p>}{session.armed && isFresh && tracks.length < 2 ? <p className="mt-1 text-xs text-zinc-400">Move farther back so both people fit in the camera frame. Keep both shoulders, elbows and wrists visible.</p> : session.armed && isFresh && current?.tracking !== 'observed' && <p className="mt-1 text-xs text-zinc-400">{current?.reason}</p>}</div>
        <span className="text-xs text-zinc-400">{tracks.length} {tracks.length === 1 ? 'person' : 'people'} tracked{session.camera && session.previewFps > 0 ? ` · Camera ${session.previewFps.toFixed(0)} FPS` : ''}{session.armed && isFresh ? ` · Tracking ${session.inferenceFps.toFixed(0)} FPS` : ''}</span>
      </div>
    </section>
    <p className="text-xs text-zinc-500">Keep both people’s upper bodies and arms visible. Allow a few seconds of clear video for detection to warm up.</p>
    {!['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname) && <p className="text-xs text-zinc-500">Camera frames are sent securely to the demo server for processing. Video is not saved. {status?.demo_auto_calls ? 'Demo phone alerts activate when the camera starts.' : 'Calls require owner access and explicit activation.'}</p>}
    <PhoneAlerts status={status} ownerKey={ownerKey} enabled={callsEnabled}
      onEnable={key => { setOwnerKey(key); setDemoCallsDisabled(false); }}
      onDisable={async () => { await session.stop(); setOwnerKey(''); setDemoCallsDisabled(true); }}
      session={session.activeSession} armed={session.armed} locked={session.camera || session.starting || busy}
      result={current} onUnavailable={session.disarm} />
    {!callsEnabled && <LiveAccuracyTest armed={session.armed} result={current} status={status} onCue={setTestCue} />}
  </div>;
}
