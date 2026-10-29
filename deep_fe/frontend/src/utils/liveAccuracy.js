export const PREPARE_MS = 2000;
export const TRIAL_MS = 6000;
export const RESULT_GRACE_MS = 500;

export function trialTiming(detector) {
  const visual = detector?.model?.startsWith('learned-video-');
  return { prepare_ms: visual ? 4000 : PREPARE_MS, response_ms: visual ? 2000 : 0 };
}

function fresh(result, now) {
  return Number.isFinite(result?.captured_ms) && now >= result.captured_ms &&
    now - result.captured_ms < 500 && Number.isFinite(result.frame_age_ms) &&
    result.frame_age_ms >= 0 && result.frame_age_ms < 500;
}

export function trackedPair(result, now) {
  return fresh(result, now) && result.tracking === 'observed' && result.tracks?.length === 2;
}

export function canStartTrial(result, now) {
  return trackedPair(result, now) && ['monitoring', 'cooldown'].includes(result.state);
}

export function createTrial(expected, now, startedAt, detector) {
  const timing = trialTiming(detector), start = now + timing.prepare_ms, end = start + TRIAL_MS;
  return { expected, started_at: startedAt, detector, ...timing, start,
    end, response_end: end + timing.response_ms, samples: [], earlyAlert: false };
}

export function observeTrial(trial, result, now) {
  if (!fresh(result, now)) return trial;
  const t = result.captured_ms;
  const alert = result.tracking === 'observed' && result.tracks?.length >= 2 && result.state === 'alert_active';
  if (t < trial.start) return alert ? { ...trial, earlyAlert: true } : trial;
  if (t >= trial.response_end || now > trial.response_end + RESULT_GRACE_MS ||
      trial.samples.some(sample => sample.t === t)) return trial;
  return { ...trial, samples: [...trial.samples, { t, tracked: trackedPair(result, now), alert }] };
}

export function finishTrial(trial, interruption = null) {
  const samples = [...trial.samples].sort((a, b) => a.t - b.t);
  const actionSamples = samples.filter(sample => sample.t < trial.end);
  const invalid = interruption || (trial.earlyAlert ? 'An alert began during the countdown. Wait for it to clear and retry.' :
    !actionSamples.length ? 'No fresh inference arrived during the trial.' : null);
  let trackedMs = 0;
  actionSamples.forEach((sample, index) => {
    if (sample.tracked) trackedMs += Math.max(0, Math.min(actionSamples[index + 1]?.t ?? trial.end, sample.t + 500, trial.end) - sample.t);
  });
  const detected = samples.some(sample => sample.alert);
  return { expected: trial.expected, started_at: trial.started_at, detector: trial.detector,
    duration_ms: TRIAL_MS, response_window_ms: trial.response_ms, prepare_ms: trial.prepare_ms, detected, outcome: invalid ? 'unscored' :
      trial.expected === 'hit' ? (detected ? 'true_positive' : 'false_negative') : (detected ? 'false_positive' : 'true_negative'),
    invalid_reason: invalid, inference_frames: samples.length, tracking_coverage: trackedMs / TRIAL_MS };
}

export function summarizeTrials(trials) {
  const counts = { true_positive: 0, false_negative: 0, false_positive: 0, true_negative: 0, unscored: 0 };
  trials.forEach(trial => { counts[trial.outcome] += 1; });
  const positive = counts.true_positive + counts.false_negative;
  const negative = counts.false_positive + counts.true_negative;
  const alerts = counts.true_positive + counts.false_positive;
  return { ...counts, positive_trials: positive, negative_trials: negative, scored_trials: positive + negative,
    recall: positive ? counts.true_positive / positive : null,
    precision: alerts ? counts.true_positive / alerts : null,
    false_alert_rate: negative ? counts.false_positive / negative : null,
    accuracy: positive && negative ? (counts.true_positive + counts.true_negative) / (positive + negative) : null };
}
