import { useEffect, useState } from 'react';
import { safetyRequest } from '../../api/safety';

export default function PhoneAlerts({ status, ownerKey, enabled, onEnable, onDisable, session, armed, locked, result, onUnavailable }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [actions, setActions] = useState([]);
  const [serverNow, setServerNow] = useState(0);

  useEffect(() => {
    setActions([]);
    if (!enabled || !session) return;
    let disposed = false, timer;
    const load = async () => {
      try {
        const data = await safetyRequest(`/sessions/${session.id}/phone-actions`, { session, ownerKey });
        if (!disposed) { setActions(data.items); setServerNow(data.server_now); setError(''); }
      } catch (e) {
        if (!disposed) {
          setError(e.message);
          await onUnavailable('Phone status unavailable. Pending calls cancelled; resume after recovery.');
        }
      } finally { if (!disposed) timer = setTimeout(load, 500); }
    };
    load();
    return () => { disposed = true; clearTimeout(timer); };
  }, [enabled, ownerKey, session, onUnavailable]);

  const enable = async event => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const data = await safetyRequest('/owner/status', { ownerKey: code.trim() });
      if (!data.real_auto_calls_available) throw new Error('Phone alerts are not configured on this server.');
      onEnable(code.trim()); setCode('');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const cancel = async id => {
    setBusy(true);
    try {
      await safetyRequest(`/sessions/${session.id}/phone-actions/${id}/cancel`, { method: 'POST', session, ownerKey });
      setActions(items => items.map(item => item.id === id ? { ...item, state: 'cancelled', error_category: 'operator_cancelled' } : item));
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  if (!status?.real_auto_calls_available && !ownerKey) return null;
  const labels = {
    submitting: 'Submitting call to provider…', submitted: 'Call request accepted by provider',
    failed: 'Call failed', delivery_unknown: 'Call delivery unknown — no automatic retry',
    cancelled: 'Call cancelled', dry_run: 'Simulation completed',
  };
  return <section className="rounded-2xl border border-zinc-800 bg-zinc-950 p-4 space-y-3" aria-label="Phone alerts">
    <h2 className="font-semibold">Phone alerts {enabled ? 'enabled' : status.demo_auto_calls ? 'off' : '(owner only)'}</h2>
    <p className="text-sm text-zinc-400">Call {status.recipient} after {status.call_trigger_seconds} seconds of sustained possible-strike detection and a {status.call_grace_seconds}-second cancellation countdown. This does not verify physical contact.</p>
    <p className="text-xs text-zinc-500">Experimental · Provider charges may apply · At most {status.call_max_per_hour} calls/hour, {Math.ceil(status.call_cooldown_seconds / 60)} minutes apart. Keep this tab visible. Stop or pause cancels pending calls. Incident metadata is saved; video recording stays off.</p>
    {error && <p role="alert" className="safety-error">{error}</p>}
    {!enabled ? status.demo_auto_calls ? <button className="safety-button" disabled={locked} onClick={() => onEnable('')}>Enable demo calls</button> : <form onSubmit={enable} className="flex flex-wrap items-end gap-3">
      <label className="text-xs text-zinc-400">Owner call access code
        <input aria-label="Owner call access code" type="password" autoComplete="off" value={code} disabled={locked || busy} onChange={e => setCode(e.target.value)} className="mt-1 block rounded-lg border border-zinc-700 bg-black px-3 py-2 text-white" />
      </label>
      <button className="safety-button" disabled={locked || busy || !code.trim()}>{busy ? 'Checking…' : `Enable calls to ${status.recipient}`}</button>
      {locked && <p className="text-xs text-zinc-400">Stop the camera to enable phone alerts.</p>}
    </form> : <>
      <p className="text-sm text-amber-200">{armed ? 'Monitoring with phone alerts.' : 'Start or resume the camera to monitor with phone alerts.'}{armed && result?.call_candidate_seconds > 0 ? ` Sustained detection: ${Math.min(status.call_trigger_seconds, result.call_candidate_seconds).toFixed(1)} / ${status.call_trigger_seconds}s.` : ''}</p>
      <button className="safety-button" onClick={onDisable}>Disable calls and stop camera</button>
      {actions.map(action => <div key={action.id} className="flex flex-wrap items-center gap-3 text-sm" aria-live="polite">
        <span>{action.state === 'countdown' ? `Calling in ${Math.max(0, Math.ceil(action.due_at - serverNow))}s` : labels[action.state] || action.state}{action.error_category ? ` · ${action.error_category.replaceAll('_', ' ')}` : ''}</span>
        {action.state === 'countdown' && <button className="safety-button" disabled={busy} onClick={() => cancel(action.id)}>Cancel call</button>}
      </div>)}
    </>}
  </section>;
}
