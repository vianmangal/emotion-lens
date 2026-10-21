import { useCallback, useEffect, useState } from 'react';
import { safetyRequest } from '../../api/safety';

export default function IncidentHistory({ compact = false }) {
  const [events, setEvents] = useState([]), [total, setTotal] = useState(0), [offset, setOffset] = useState(0);
  const [error, setError] = useState(''), [clip, setClip] = useState(null);
  const [now, setNow] = useState(Date.now());
  const load = useCallback(async () => {
    try { const data = await safetyRequest(`/events?offset=${offset}&limit=${compact ? 5 : 20}`); setEvents(data.items); setTotal(data.total); }
    catch (e) { setError(e.message); }
  }, [offset, compact]);
  useEffect(() => { load(); const timer = setInterval(() => { load(); setNow(Date.now()); }, 1000); return () => clearInterval(timer); }, [load]);
  useEffect(() => () => { if (clip) URL.revokeObjectURL(clip.url); }, [clip]);
  const act = async (path, method, body) => { try { await safetyRequest(path, { method, body }); setError(''); await load(); } catch (e) { setError(e.message); } };
  const openClip = async event => {
    try { const blob = await safetyRequest(`/events/${event.id}/clip`, { blob: true }); setClip({ id: event.id, url: URL.createObjectURL(blob) }); }
    catch (e) { setError(e.message); }
  };
  return <section className="safety-panel" aria-label="Incident history">
    <div className="flex items-center justify-between gap-4"><h2 className="text-lg font-semibold">Incident review</h2><span className="text-xs text-zinc-400">{total} local records</span></div>
    <p className="mt-2 text-xs text-zinc-400">Review labels are feedback. Metadata is kept for 7 days; clips for 24 hours by default.</p>
    {error && <p role="alert" className="safety-error">{error}</p>}
    {!events.length && <p className="py-8 text-sm text-zinc-500">No incidents recorded.</p>}
    <div className="mt-4 space-y-3">{events.map(event => <article key={event.id} className="rounded-xl border border-zinc-800 p-4">
      <p className="font-semibold text-amber-200">⚠ Possible striking motion — review footage.</p>
      <p className="my-2 text-xs text-zinc-400">{new Date(event.created_at * 1000).toLocaleString()} · {event.source === 'replay' ? 'REPLAY / NO CALLS' : 'LIVE'} · {event.status}</p>
      <p className="text-xs text-zinc-500">{event.model_version} · model score {event.score.toFixed(2)} · clip: {event.clip_status}</p>
      {event.actions.map(action => <div key={action.id} className="mt-3 flex flex-wrap items-center gap-3 text-sm" role="status">
        <span>Phone {action.mode}: {action.state === 'countdown' ? `countdown ${Math.max(0, Math.ceil(action.due_at - now / 1000))}s` : action.state}{action.error_category ? ` (${action.error_category})` : ''}</span>
        {action.state === 'countdown' && <button className="safety-button" onClick={() => act(`/events/${event.id}/actions/cancel`, 'POST')}>Cancel now</button>}
      </div>)}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <label className="text-xs">Review <select aria-label={`Review incident ${event.id}`} value={event.review_label} onChange={e => act(`/events/${event.id}`, 'PATCH', { label: e.target.value })}>
          <option value="unreviewed">Unreviewed</option><option value="relevant">Relevant</option><option value="false_alarm">False alarm</option><option value="unclear">Unclear</option>
        </select></label>
        {['ready', 'partial'].includes(event.clip_status) && <button className="safety-button" onClick={() => openClip(event)}>Play clip</button>}
        <button className="safety-button" onClick={() => { if (clip?.id === event.id) setClip(null); act(`/events/${event.id}`, 'DELETE'); }}>Delete event and clip</button>
      </div>
    </article>)}</div>
    {clip && <div className="mt-4"><video controls autoPlay src={clip.url} className="max-h-96 w-full rounded-xl" aria-label="Incident clip" /><button className="safety-button mt-2" onClick={() => setClip(null)}>Close clip</button></div>}
    {!compact && total > 20 && <div className="mt-4 flex gap-3"><button className="safety-button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</button><button className="safety-button" disabled={offset + 20 >= total} onClick={() => setOffset(offset + 20)}>Next</button></div>}
  </section>;
}
