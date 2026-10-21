import { useCallback, useEffect, useRef, useState } from 'react';
import { safetyRequest, streamUrl } from '../api/safety';

export default function useSafetySession() {
  const videoRef = useRef(null);
  const resources = useRef({ stream: null, ws: null, session: null, timer: null, cancelConnect: null, armed: false, epoch: 0, control: 0, lastResult: 0 });
  const [camera, setCamera] = useState(false);
  const [starting, setStarting] = useState(false);
  const [armed, setArmed] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [devices, setDevices] = useState([]);
  const [aspect, setAspect] = useState(4 / 3);
  const [fps, setFps] = useState(0);
  const [inferenceFps, setInferenceFps] = useState(0);

  const stop = useCallback(async (update = true) => {
    const r = resources.current;
    const epoch = ++r.epoch;
    r.control += 1;
    r.armed = false;
    clearInterval(r.timer);
    r.timer = null;
    r.cancelConnect?.();
    const session = r.session;
    r.session = null;
    if (r.ws) { r.ws.onopen = r.ws.onmessage = r.ws.onerror = r.ws.onclose = null; r.ws.close(); r.ws = null; }
    r.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    r.stream = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    if (update) { setCamera(false); setStarting(false); setArmed(false); setResult(null); setFps(0); setInferenceFps(0); }
    if (session) {
      try { await safetyRequest(`/sessions/${session.id}`, { method: 'DELETE', session }); } catch { /* Backend disconnect also expires session. */ }
    }
    return epoch;
  }, []);

  const disarm = useCallback(async (reason = 'Disarmed') => {
    const r = resources.current;
    const control = ++r.control;
    const session = r.session;
    r.armed = false;
    setArmed(false);
    setInferenceFps(0);
    setResult({ state: reason === 'Disarmed' ? 'disarmed' : 'unavailable', reason, tracks: [] });
    if (r.ws?.readyState === WebSocket.OPEN) r.ws.send(JSON.stringify({ v: 1, type: 'pause' }));
    if (session) {
      try { await safetyRequest(`/sessions/${session.id}/disarm`, { method: 'POST', session }); }
      catch (e) { if (r.control === control) setError(e.message); }
    }
  }, []);

  const start = useCallback(async deviceId => {
    const epoch = await stop();
    const r = resources.current;
    if (r.epoch !== epoch) return false;
    setError(''); setStarting(true);
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access needs a supported browser on localhost.');
      const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { width: { ideal: 640 }, height: { ideal: 480 }, ...(deviceId ? { deviceId: { exact: deviceId } } : {}) } });
      if (r.epoch !== epoch) { stream.getTracks().forEach(t => t.stop()); return false; }
      r.stream = stream;
      stream.getVideoTracks().forEach(t => { t.onended = () => { setError('Camera disconnected. Start again to recover.'); stop(); }; });
      if (videoRef.current) { videoRef.current.srcObject = stream; await videoRef.current.play(); }
      const session = await safetyRequest('/sessions', { method: 'POST', body: { source: 'live', live_only: true } });
      if (r.epoch !== epoch) { await safetyRequest(`/sessions/${session.id}`, { method: 'DELETE', session }); return false; }
      r.session = session;
      const ws = new WebSocket(streamUrl(session.id));
      r.ws = ws;
      await new Promise((resolve, reject) => {
        const complete = (error) => {
          clearTimeout(timeout); r.cancelConnect = null;
          if (error) reject(error); else resolve();
        };
        const timeout = setTimeout(() => complete(new Error('Camera stream connection timed out.')), 5000);
        r.cancelConnect = () => complete(new Error('Camera connection cancelled.'));
        ws.onopen = () => ws.send(JSON.stringify({ capability: session.capability }));
        ws.onerror = () => complete(new Error('Cannot open the local camera stream.'));
        ws.onmessage = e => {
          const data = JSON.parse(e.data);
          if (data.type === 'connected') complete();
        };
        ws.onclose = () => complete(new Error('Camera stream closed.'));
      });
      if (r.epoch !== epoch) return false;
      let frameId = 0, encoding = false, sent = 0, inferred = 0, measuredAt = performance.now(), videoTime = -1, changedAt = performance.now();
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      ws.onmessage = e => {
        if (r.epoch !== epoch || r.ws !== ws) return;
        const data = JSON.parse(e.data);
        if (data.type === 'heartbeat') {
          if (data.generation !== undefined && data.generation < r.generation) return;
          // Heartbeats report server health; they are never fresh inference results.
          if (r.armed && ['disarmed', 'unavailable'].includes(data.state)) {
            r.control += 1;
            r.armed = false;
            setArmed(false);
            setResult({ ...data, tracks: [] });
          }
          return;
        }
        if (!r.armed || (data.generation !== undefined && data.generation < r.generation)) return;
        inferred += 1;
        r.lastResult = performance.now();
        const age = Number.isFinite(data.captured_ms) ? Math.max(0, performance.now() - data.captured_ms) : data.frame_age_ms;
        setResult({ ...data, frame_age_ms: age === undefined ? undefined : Math.round(age) });
        if (['disarmed', 'unavailable'].includes(data.state)) { r.armed = false; setArmed(false); }
      };
      ws.onclose = () => { setError('Backend stream disconnected. Start the camera again to recover.'); stop(); };
      ws.onerror = () => { setError('Local stream failed. Start again to recover.'); stop(); };
      r.timer = setInterval(() => {
        const video = videoRef.current;
        if (performance.now() - measuredAt > 1000) {
          const seconds = (performance.now() - measuredAt) / 1000;
          setFps(sent / seconds); setInferenceFps(inferred / seconds);
          sent = 0; inferred = 0; measuredAt = performance.now();
        }
        if (!r.armed || document.hidden) return;
        if (performance.now() - r.lastResult > 1500) { disarm('Fresh inference stopped. Explicitly re-arm after recovery.'); return; }
        if (encoding || !video?.videoWidth || ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 512 * 1024) return;
        if (video.currentTime !== videoTime) { videoTime = video.currentTime; changedAt = performance.now(); }
        else if (performance.now() - changedAt > 1000) { disarm('Camera preview frozen. Stop and restart the camera.'); return; }
        const capturedAt = performance.now();
        const captureControl = r.control;
        const scale = Math.min(640 / video.videoWidth, 480 / video.videoHeight, 1);
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        setAspect(canvas.width / canvas.height);
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        encoding = true;
        canvas.toBlob(async blob => {
          try {
            if (!blob || blob.size > 512 * 1024 || !r.armed || r.epoch !== epoch || r.control !== captureControl || ws.readyState !== WebSocket.OPEN) return;
            const bytes = new Uint8Array(await blob.arrayBuffer());
            let binary = ''; for (const b of bytes) binary += String.fromCharCode(b);
            if (!r.armed || r.epoch !== epoch || r.control !== captureControl || ws.readyState !== WebSocket.OPEN) return;
            ws.send(JSON.stringify({ v: 1, session_id: session.id, frame_id: frameId++, captured_ms: capturedAt, jpeg: btoa(binary) }));
            sent += 1;
          } finally { encoding = false; }
        }, 'image/jpeg', .75);
      }, 100);
      const devices = await navigator.mediaDevices.enumerateDevices().catch(() => []);
      if (r.epoch !== epoch) return false;
      setDevices(devices.filter(d => d.kind === 'videoinput'));
      setCamera(true); setStarting(false);
      return true;
    } catch (e) {
      if (r.epoch === epoch) {
        await stop();
        setError(e.name === 'NotAllowedError' ? 'Camera permission denied. Allow camera access in your browser, then Start again.' : e.name === 'NotFoundError' ? 'No camera found. Connect a camera and retry.' : e.message);
      }
      return false;
    }
  }, [stop, disarm]);

  const arm = async options => {
    setError('');
    const r = resources.current;
    const epoch = r.epoch;
    const control = ++r.control;
    const session = r.session;
    try {
      if (!session || document.hidden) throw new Error('Start a visible camera session first.');
      const response = await safetyRequest(`/sessions/${session.id}/arm`, { method: 'POST', body: { ...options, client_now_ms: performance.now() }, session });
      if (r.epoch !== epoch || r.control !== control || r.session !== session || document.hidden) {
        // A hide/disarm/stop can overtake this HTTP response. Cancel the old
        // session's arm before returning; never reactivate local capture.
        await safetyRequest(`/sessions/${session.id}/disarm`, { method: 'POST', session }).catch(() => {});
        return false;
      }
      r.lastResult = performance.now();
      r.generation = response.generation;
      r.armed = true;
      setArmed(true); setResult({ state: 'warming_up', reason: 'Building temporal evidence…', tracks: [] });
      return true;
    } catch (e) { if (r.epoch === epoch && r.control === control) setError(e.message); return false; }
  };

  useEffect(() => {
    const hidden = () => { if (document.hidden) disarm('Browser hidden. Monitoring paused; explicitly re-arm.'); };
    const pagehide = () => stop(false);
    document.addEventListener('visibilitychange', hidden);
    window.addEventListener('pagehide', pagehide);
    navigator.mediaDevices?.enumerateDevices().then(list => setDevices(list.filter(d => d.kind === 'videoinput'))).catch(() => {});
    return () => { document.removeEventListener('visibilitychange', hidden); window.removeEventListener('pagehide', pagehide); stop(false); };
  }, [stop, disarm]);
  return { videoRef, camera, starting, armed, result, error, devices, aspect, fps, inferenceFps, start, stop, arm, disarm };
}
