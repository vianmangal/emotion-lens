import { useEffect, useRef, useState } from 'react';
import { canStartTrial, createTrial, finishTrial, observeTrial, RESULT_GRACE_MS, summarizeTrials, trialTiming } from '../../utils/liveAccuracy';

const percent = value => value === null ? '—' : `${Math.round(value * 100)}%`;
const instructions = {
  hit: 'One staged striking attempt toward the other person, stopping short with no contact.',
  normal: 'One ordinary gesture: wave, reach, mime a high-five, or turn. No striking attempt.',
};

export default function LiveAccuracyTest({ armed, result, status, onCue }) {
  const [open, setOpen] = useState(false), [expected, setExpected] = useState('hit');
  const [running, setRunning] = useState(false), [pending, setPending] = useState(null);
  const [trials, setTrials] = useState([]), [detector, setDetector] = useState(null), [clock, setClock] = useState(0);
  const [error, setError] = useState('');
  const active = useRef(null), inputs = useRef({ armed, result });
  inputs.current = { armed, result };
  const currentDetector = status ? { model: status.model, event_policy: { ...status.event_policy, cooldown: 0 } } : null;
  const timing = trialTiming(currentDetector);
  const settingsChanged = detector && JSON.stringify(detector) !== JSON.stringify(currentDetector);
  const summary = summarizeTrials(trials);

  const complete = interruption => {
    if (!active.current) return;
    setPending(finishTrial(active.current, interruption));
    active.current = null;
    setRunning(false);
    onCue(null);
  };

  useEffect(() => {
    if (active.current && result) active.current = observeTrial(active.current, result, performance.now());
  }, [result]);

  useEffect(() => {
    if (!armed) complete('Detection stopped or paused during the trial.');
  }, [armed]);

  useEffect(() => {
    if (!running) return;
    let lastTick = performance.now();
    const tick = () => {
      const trial = active.current;
      if (!trial) return;
      const now = performance.now();
      if (document.hidden || !inputs.current.armed || now - lastTick > 1000) {
        complete('The live test was interrupted. Repeat this trial.');
        return;
      }
      lastTick = now;
      if (trial.earlyAlert) { complete(); return; }
      if (now >= trial.response_end + RESULT_GRACE_MS) { complete(); return; }
      const preparing = now < trial.start, finishing = now >= trial.end;
      onCue(preparing ? `Get ready · ${Math.ceil((trial.start - now) / 1000)}` : finishing ?
        trial.response_ms && now < trial.response_end ? `Hold still · ${Math.ceil((trial.response_end - now) / 1000)}s` : 'Checking final frames…' :
        `MOVE NOW · ${Math.ceil((trial.end - now) / 1000)}s`);
      setClock(now);
    };
    tick();
    const timer = setInterval(tick, 100);
    const hidden = () => { if (document.hidden) complete('The browser was hidden during the trial.'); };
    document.addEventListener('visibilitychange', hidden);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', hidden); onCue(null); };
  }, [running, onCue]);

  const start = () => {
    if (!armed || !canStartTrial(inputs.current.result, performance.now())) {
      setError('Wait for exactly two clearly tracked people and let the previous alert clear.');
      return;
    }
    if (!currentDetector || settingsChanged) { setError('Detector settings changed. Reset the test before continuing.'); return; }
    setError('');
    setDetector(currentDetector);
    active.current = createTrial(expected, performance.now(), new Date().toISOString(), currentDetector);
    setClock(performance.now());
    setRunning(true);
  };
  const save = () => { setTrials(previous => [...previous, pending]); setPending(null); };
  const discard = () => {
    setTrials(previous => [...previous, { ...pending, outcome: 'unscored', invalid_reason: pending.invalid_reason || 'Operator discarded: intended motion or timing not confirmed.' }]);
    setPending(null);
  };
  const download = () => {
    const report = { version: 1, source: 'live camera; operator-confirmed staged trials',
      scope: 'Preliminary per-trial detection results for this setup, not a general accuracy claim. No video or poses saved.',
      protocol: { countdown_ms: trialTiming(detector).prepare_ms, trial_ms: 6000,
        response_window_ms: trialTiming(detector).response_ms, result_grace_ms: RESULT_GRACE_MS,
        ground_truth: 'Operator confirms one intended action during MOVE NOW and stays still during the response window. Interrupted and discarded trials are unscored.',
        tracking: 'Loss of clear tracking within a completed trial does not exclude a miss. Coverage is reported separately.' },
      exported_at: new Date().toISOString(), detector, summary, trials };
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'emotion-lens-live-accuracy.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const preparing = active.current && clock < active.current.start;
  const finishing = active.current && clock >= active.current.end;

  return <div>
    <button className="text-xs text-zinc-400 underline underline-offset-4 hover:text-white" aria-expanded={open} aria-controls="accuracy-test" onClick={() => { if (running) complete('Operator closed the test during a trial.'); setOpen(value => !value); }}>Test detection accuracy</button>
    {open && <section id="accuracy-test" aria-label="Live accuracy test" className="safety-panel mt-3 space-y-4">
      <div><h2 className="font-semibold">Live accuracy test</h2><p className="mt-1 text-xs leading-relaxed text-zinc-400">Test with two people. Keep space between them and use staged motions without contact. Aim for 10 hit attempts and 10 ordinary-gesture trials; swap roles halfway.</p></div>
      <label className="flex flex-wrap items-center gap-3 text-xs text-zinc-300">Trial action
        <select aria-label="Trial action" value={expected} disabled={running || Boolean(pending)} onChange={event => setExpected(event.target.value)}>
          <option value="hit">Staged hit attempt</option><option value="normal">Ordinary gesture</option>
        </select>
      </label>
      <p className="text-sm text-zinc-300">{instructions[expected]}</p>
      <p className="text-xs text-zinc-400">Start a trial, stay still for the {timing.prepare_ms / 1000}-second countdown, then perform the action once during the 6-second MOVE NOW window.{timing.response_ms > 0 && ` Stay still for ${timing.response_ms / 1000} more seconds while the detector finishes.`}</p>
      {error && <p className="text-sm text-amber-300">{error}</p>}
      {settingsChanged && <p className="text-sm text-amber-300">Detector settings changed. Reset before another trial.</p>}
      {!pending && <div className="flex flex-wrap items-center gap-3">
        <button className="safety-button safety-primary" onClick={start} disabled={running || !armed || !status?.ready || Boolean(settingsChanged)}>Start trial</button>
        {running && <button className="safety-button" onClick={() => complete('Operator cancelled the trial.')}>Cancel trial</button>}
        <p aria-live="polite" className="text-sm text-cyan-200">{running ? preparing ? 'Get ready…' : finishing ? 'Checking final frames…' : 'MOVE NOW' : !armed ? 'Start the camera first.' : 'Wait until both people are clearly tracked and any alert clears.'}</p>
      </div>}
      {pending && <div className="space-y-3 rounded-xl border border-zinc-700 p-3">
        <p className="text-sm font-semibold">{pending.invalid_reason ? 'Trial not scored' : pending.detected ? 'Detector result: alert observed' : 'Detector result: no alert'}</p>
        <p className="text-xs text-zinc-400">{pending.invalid_reason || 'Save only if the selected action was performed once during MOVE NOW and you stayed still afterward. Otherwise discard and repeat.'}</p>
        <p className="text-xs text-zinc-400">Clear two-person tracking: {percent(pending.tracking_coverage)} of the trial. Tracking loss can cause missed attempts; those misses still count.</p>
        <div className="flex flex-wrap gap-2">
          {!pending.invalid_reason && <button className="safety-button safety-primary" onClick={save}>Confirm action & save</button>}
          <button className="safety-button" onClick={discard}>{pending.invalid_reason ? 'Dismiss & retry' : 'Discard trial'}</button>
        </div>
      </div>}
      <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
        <div><p className="text-xs text-zinc-400">Hit recall</p><p className="mt-1 text-xl" data-testid="hit-recall">{percent(summary.recall)}</p><p className="text-xs text-zinc-500">{summary.true_positive}/{summary.positive_trials} staged attempts detected</p></div>
        <div><p className="text-xs text-zinc-400">Alert precision</p><p className="mt-1 text-xl" data-testid="alert-precision">{percent(summary.precision)}</p><p className="text-xs text-zinc-500">{summary.true_positive}/{summary.true_positive + summary.false_positive} alerts matched staged attempts</p></div>
        <div><p className="text-xs text-zinc-400">Trial accuracy</p><p className="mt-1 text-xl" data-testid="trial-accuracy">{percent(summary.accuracy)}</p><p className="text-xs text-zinc-500">Needs both trial types</p></div>
      </div>
      <p className="text-xs text-zinc-400" data-testid="accuracy-counts">Detected attempts: {summary.true_positive} · Missed attempts: {summary.false_negative} · False alerts: {summary.false_positive} · Correctly clear: {summary.true_negative} · Unscored: {summary.unscored}</p>
      <p className="text-xs leading-relaxed text-zinc-500">Preliminary results apply to these people, motions, lighting and camera angle. Each trial counts once. Results stay in this page until reset or reload; export to keep them. No video or incident history is saved.</p>
      <div className="flex flex-wrap gap-2">
        <button className="safety-button" disabled={!trials.length || running || Boolean(pending)} onClick={download}>Export test results</button>
        <button className="safety-button" disabled={!trials.length || running || Boolean(pending)} onClick={() => { setTrials([]); setDetector(null); setError(''); }}>Reset test</button>
      </div>
    </section>}
  </div>;
}
