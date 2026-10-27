import { useEffect, useState } from 'react';
import useSafetySession from '../hooks/useSafetySession';
import { safetyRequest } from '../api/safety';
import LiveAccuracyTest from '../components/safety/LiveAccuracyTest';

const DETECTION_OPTIONS = { phone_mode: 'off', clips: false };
const BONES = [[0, 1], [0, 2], [1, 3], [2, 4], [5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];

export default function LiveSafety() {
  const session = useSafetySession();
  const [status, setStatus] = useState(null), [error, setError] = useState('');
  const [device, setDevice] = useState(''), [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState(false);
  const [testCue, setTestCue] = useState(null);
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
    setFresh(true); const timer = setTimeout(() => setFresh(false), 500);
    return () => clearTimeout(timer);
  }, [session.result]);

  const start = async () => {
    setBusy(true);
    try { if (await session.start(device)) await session.arm(DETECTION_OPTIONS); }
    finally { setBusy(false); }
  };
  const resume = async () => {
    setBusy(true);
    try { await session.arm(DETECTION_OPTIONS); }
    finally { setBusy(false); }
  };
  const current = session.result;
  const isFresh = session.armed && fresh && current?.frame_age_ms < 500;
  const tracks = isFresh ? current.tracks || [] : [];
  const detected = isFresh && tracks.length >= 2 && current.tracking === 'observed' && current.state === 'alert_active';
  const paused = session.camera && !session.armed && !busy;
  let message = 'Camera off';
  if (busy || session.starting) message = 'Starting detection…';
  else if (paused) message = 'Detection paused';
  else if (session.armed && !isFresh) message = 'Waiting for fresh video…';
  else if (session.armed && tracks.length < 2) message = tracks.length === 1 ? 'Only one person tracked' : 'Waiting for two people';
  else if (session.armed && current.tracking !== 'observed') message = 'Getting a clear view…';
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
    <LiveAccuracyTest armed={session.armed} result={current} status={status} onCue={setTestCue} />
  </div>;
}
