import { useEffect, useRef, useState } from 'react';
import useSafetySession from '../hooks/useSafetySession';
import { safetyRequest } from '../api/safety';
import IncidentHistory from '../components/safety/IncidentHistory';

export default function LiveSafety() {
  const session = useSafetySession();
  const [status, setStatus] = useState(null), [error, setError] = useState('');
  const [device, setDevice] = useState(''), [phone, setPhone] = useState('off');
  const preference = key => {
    try { return JSON.parse(localStorage.getItem('emotionlens-local-preferences') || '{}')[key] === true; }
    catch { return false; }
  };
  const [clips, setClips] = useState(() => preference('clips')), [sound, setSound] = useState(() => preference('sound'));
  useEffect(() => { try { localStorage.setItem('emotionlens-local-preferences', JSON.stringify({ clips, sound })); } catch { /* Preferences are optional. */ } }, [clips, sound]);
  useEffect(() => { if (status && !status.recording_available) setClips(false); }, [status]);
  const [ack, setAck] = useState(false), [actions, setActions] = useState([]), [now, setNow] = useState(Date.now());
  const audio = useRef(null), lastBeep = useRef(null);
  const [fresh, setFresh] = useState(false);
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try { const [s, a] = await Promise.all([safetyRequest('/status'), safetyRequest('/phone/actions')]); if (mounted) { setStatus(s); setActions(a.items); setError(''); setNow(Date.now()); } }
      catch (e) { if (mounted) { setError(e.message); setStatus(null); } }
    };
    load(); const timer = setInterval(load, 1000);
    return () => { mounted = false; clearInterval(timer); audio.current?.close(); };
  }, []);
  useEffect(() => {
    setFresh(true); const timer = setTimeout(() => setFresh(false), 500);
    return () => clearTimeout(timer);
  }, [session.result]);
  useEffect(() => {
    if (sound && session.result?.new_event && lastBeep.current !== session.result.event_id && audio.current) {
      lastBeep.current = session.result.event_id;
      const oscillator = audio.current.createOscillator(), gain = audio.current.createGain();
      oscillator.connect(gain); gain.connect(audio.current.destination); gain.gain.value = .08; oscillator.frequency.value = 660;
      oscillator.start(); oscillator.stop(audio.current.currentTime + .25);
    }
  }, [session.result, sound]);
  const enableSound = async value => {
    setSound(value);
    if (value) { audio.current ||= new AudioContext(); await audio.current.resume(); }
    else if (audio.current) { await audio.current.close(); audio.current = null; }
  };
  const arm = async () => {
    if (sound) { audio.current ||= new AudioContext(); await audio.current.resume(); }
    await session.arm({ phone_mode: phone, clips, recipient_acknowledged: false });
  };
  const testPhone = async mode => {
    try { await safetyRequest('/phone/test', { method: 'POST', body: { mode, recipient_acknowledged: ack, request_id: crypto.randomUUID() } }); setError(''); }
    catch (e) { setError(e.message); }
  };
  const current = session.result;
  const state = !status ? 'unavailable' : current?.state || 'disarmed';
  return <div className="space-y-5">
    <div><p className="text-xs uppercase tracking-widest text-zinc-500">Local webcam monitor</p><h1 className="mt-2 text-2xl font-semibold">Live Safety <span className="text-sm text-amber-300">Experimental</span></h1></div>
    <div className="safety-panel border-amber-900/60 text-sm text-amber-100"><strong>Detector qualification is unmet.</strong> This demo flags motion for review. Automatic real calls remain locked. Expression scores never trigger alerts.</div>
    {status?.storage_warning && <p role="alert" className="safety-error">{status.storage_warning}</p>}
    {(error || session.error) && <p role="alert" className="safety-error">{session.error || error}</p>}
    <div className="grid gap-5 lg:grid-cols-[1.6fr_1fr]">
      <section className="safety-panel">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">Camera · {state.replaceAll('_', ' ')}</h2><span className="text-xs text-zinc-400">Microphone off</span></div>
        <div className="relative mt-4 overflow-hidden rounded-xl bg-black" style={{ aspectRatio: session.aspect }}>
          <div className="absolute inset-0" style={{ transform: 'scaleX(-1)' }}>
            <video ref={session.videoRef} autoPlay muted playsInline className="h-full w-full object-contain" aria-label="Local camera preview" />
            <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">{fresh && current?.frame_age_ms < 500 && current?.tracks?.map(track => <g key={track.id}>
              <rect x={track.box[0]} y={track.box[1]} width={track.box[2] - track.box[0]} height={track.box[3] - track.box[1]} fill="none" stroke="#67e8f9" strokeWidth=".004" />
              {track.points.map((point, i) => point[2] > .55 && <circle key={i} cx={point[0]} cy={point[1]} r=".005" fill="#fbbf24" />)}
            </g>)}</svg>
          </div>
          {!session.camera && <div className="absolute inset-0 grid place-items-center text-sm text-zinc-500">{session.starting ? 'Opening camera…' : 'Camera off · click Start'}</div>}
        </div>
        <div role="status" aria-live="polite" className={`mt-4 rounded-lg p-3 text-sm ${state === 'alert_active' ? 'bg-amber-950 text-amber-100' : 'bg-zinc-900 text-zinc-300'}`}>
          {state === 'alert_active' ? '⚠ Possible striking motion — review footage.' : state === 'candidate' ? 'Checking movement…' : state === 'monitoring' ? 'No event detected' : state.replaceAll('_', ' ')}
          <p className="mt-1 text-xs text-zinc-400">{current?.reason || (session.camera ? 'Preview running. Arm to analyze motion.' : 'Start a camera session to preview.')}</p>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-zinc-400"><span>Capture: {session.fps.toFixed(1)} FPS</span><span>Inference: {current?.processing_ms ? (1000 / current.processing_ms).toFixed(1) : '—'} FPS capacity</span><span>Frame age: {session.armed && fresh ? `${current?.frame_age_ms ?? '—'} ms` : '—'}</span><span>Tracking: {current?.tracking?.replaceAll('_', ' ') || 'not analyzing'}</span><span>People: {current?.people ?? '—'}</span><span>Dropped: {current?.dropped_frames ?? 0}</span></div>
      </section>
      <section className="safety-panel space-y-4" aria-label="Monitoring controls">
        <label className="block text-sm">Camera<select className="mt-2 w-full" value={device} disabled={session.camera || session.starting} onChange={e => setDevice(e.target.value)}><option value="">Default camera</option>{session.devices.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}</select></label>
        <div className="flex flex-wrap gap-2"><button className="safety-button safety-primary" disabled={session.camera || session.starting || !status} onClick={() => session.start(device)}>Start camera</button><button className="safety-button" disabled={!session.camera && !session.starting} onClick={() => session.stop()}>Stop</button></div>
        <div className="border-t border-zinc-800 pt-4"><p className="text-xs text-zinc-400">Model: {status?.ready ? 'Ready · experimental' : 'Unavailable'}</p><p className="mt-1 text-xs text-zinc-500">{status?.model && <span className="mb-1 block">{status.model}</span>}{status?.reason || 'Checking local backend…'}</p></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={sound} onChange={e => enableSound(e.target.checked)} />Local alert sound</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={clips} disabled={session.armed || !status?.recording_available} onChange={e => setClips(e.target.checked)} />Save event clips (opt in)</label>
        <p className="text-xs text-zinc-500">Up to 5 seconds before and after an event, no audio. Clips remain on this computer for {status?.clip_retention_hours ?? 24} hours. {status?.recording_reason}</p>
        <label className="block text-sm">Phone mode<select className="mt-2 w-full" value={phone} disabled={session.armed} onChange={e => setPhone(e.target.value)}><option value="off">Off</option><option value="dry_run">Dry run · no provider request</option><option value="real" disabled>Real automatic calls · qualification required</option></select></label>
        <p className="text-xs text-zinc-400">Recipient: {status?.recipient || 'Not configured'} · {phone === 'dry_run' ? 'Local action record only' : 'Automatic calls off'}</p>
        <div className="flex flex-wrap gap-2"><button className="safety-button safety-primary" disabled={!session.camera || session.armed || !status?.ready} onClick={arm}>Arm monitoring</button><button className="safety-button" disabled={!session.armed} onClick={() => session.disarm()}>Disarm</button></div>
        <p className="text-xs text-zinc-500">Storage: {((status?.storage_bytes || 0) / 1048576).toFixed(1)} / {((status?.storage_quota_bytes || 524288000) / 1048576).toFixed(0)} MiB</p>
      </section>
    </div>
    <section className="safety-panel"><h2 className="font-semibold">Phone adapter test</h2><p className="mt-2 text-xs text-zinc-400">Dry run works without credentials. An explicit real test uses ElevenLabs and its connected phone provider, may cost money, and can only call the server-configured recipient. Submitted calls cannot be recalled.</p>
      <label className="my-4 flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />I own this number or have the recipient’s consent, and authorize a paid real test call.</label>
      <div className="flex flex-wrap gap-2"><button className="safety-button" disabled={!status} onClick={() => testPhone('dry_run')}>Test dry run</button><button className="safety-button" disabled={!ack || !status?.real_test_available} onClick={() => testPhone('real')}>Send real test call</button></div>
      <div className="mt-3 space-y-2 text-xs" aria-live="polite">{actions.filter(a => !['cancelled', 'dry_run'].includes(a.state)).slice(0, 5).map(a => <div key={a.id} className="flex flex-wrap items-center gap-3"><span>{a.mode}: {a.state === 'countdown' ? `countdown ${Math.max(0, Math.ceil(a.due_at - now / 1000))}s` : a.state} {a.error_category || ''}</span>{a.state === 'countdown' && <button className="safety-button" onClick={() => safetyRequest(`/phone/actions/${a.id}/cancel`, { method: 'POST' }).catch(e => setError(e.message))}>Cancel now</button>}</div>)}{actions[0]?.state === 'dry_run' && <div><p>✓ Dry run recorded. No provider contacted.</p>{actions[0].preview && <p className="mt-2 text-zinc-400">{actions[0].preview.summary} Recipient: {actions[0].preview.recipient}.</p>}</div>}</div>
    </section>
    <IncidentHistory compact />
  </div>;
}
