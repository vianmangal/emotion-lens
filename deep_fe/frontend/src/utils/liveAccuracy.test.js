import test from 'node:test';
import assert from 'node:assert/strict';
import { canStartTrial, createTrial, finishTrial, observeTrial, summarizeTrials } from './liveAccuracy.js';

const pair = [{ id: 1 }, { id: 2 }];
const result = (t, extra = {}) => ({ captured_ms: t, frame_age_ms: 20, tracks: pair, tracking: 'observed', state: 'monitoring', ...extra });
const trial = (expected = 'hit') => createTrial(expected, 1000, '2026-10-22T12:00:00Z', { model: 'test-model' });

test('trials need a fresh, clear pair with no active or candidate alert', () => {
  assert.equal(canStartTrial(result(1000), 1050), true);
  for (const extra of [{ state: 'alert_active' }, { state: 'candidate' }, { tracks: [pair[0]] },
    { tracks: [...pair, { id: 3 }] }, { tracking: 'insufficient_evidence' }, { frame_age_ms: 800 }]) {
    assert.equal(canStartTrial(result(1000, extra), 1050), false);
  }
  assert.equal(canStartTrial(result(1000), 1500), false);
  assert.equal(canStartTrial(result(1100), 1000), false);
});

test('only fresh captures inside the trial window can count as alerts', () => {
  let attempt = trial();
  attempt = observeTrial(attempt, result(3000), 3020);
  attempt = observeTrial(attempt, result(4000, { state: 'alert_active' }), 4600); // stale
  attempt = observeTrial(attempt, result(9000, { state: 'alert_active' }), 9020); // outside
  assert.equal(finishTrial(attempt).outcome, 'false_negative');
  attempt = observeTrial(attempt, result(8900, { state: 'alert_active' }), 9200); // late, but fresh and captured inside
  assert.equal(finishTrial(attempt).outcome, 'true_positive');
  assert.equal(attempt.samples.length, 2);
});

test('duplicate results and repeated alert frames count as one trial', () => {
  let attempt = trial('normal');
  attempt = observeTrial(attempt, result(3100, { state: 'alert_active' }), 3120);
  attempt = observeTrial(attempt, result(3100, { state: 'alert_active' }), 3130);
  attempt = observeTrial(attempt, result(3200, { state: 'alert_active' }), 3220);
  assert.equal(attempt.samples.length, 2);
  const completed = finishTrial(attempt);
  assert.equal(completed.outcome, 'false_positive');
  assert.equal(summarizeTrials([completed]).false_positive, 1);
});

test('countdown alerts, interruptions and no fresh inference cannot become successful negatives', () => {
  let attempt = trial('normal');
  attempt = observeTrial(attempt, result(2500, { state: 'alert_active' }), 2520);
  attempt = observeTrial(attempt, result(3200), 3220);
  assert.equal(finishTrial(attempt).outcome, 'unscored');
  assert.match(finishTrial(attempt).invalid_reason, /countdown/);
  assert.equal(finishTrial(trial('normal')).outcome, 'unscored');
  assert.equal(finishTrial(attempt, 'Camera stopped').invalid_reason, 'Camera stopped');
});

test('loss of tracking in a completed hit trial still counts as a missed attempt', () => {
  const attempt = observeTrial(trial(), result(3500, { tracking: 'insufficient_evidence', tracks: [] }), 3520);
  const completed = finishTrial(attempt);
  assert.equal(completed.outcome, 'false_negative');
  assert.equal(completed.tracking_coverage, 0);
});

test('tracking coverage measures time and does not bridge long gaps', () => {
  let attempt = trial();
  for (let t = 3000; t < 9000; t += 100) attempt = observeTrial(attempt, result(t), t + 20);
  assert.equal(finishTrial(attempt).tracking_coverage, 1);
  const sparse = observeTrial(trial(), result(3000), 3020);
  assert.equal(finishTrial(sparse).tracking_coverage, 500 / 6000);
});

test('metrics use the complete confusion matrix and exclude unscored trials', () => {
  const summary = summarizeTrials(['true_positive', 'true_positive', 'false_negative', 'false_positive', 'true_negative', 'unscored'].map(outcome => ({ outcome })));
  assert.equal(summary.recall, 2 / 3);
  assert.equal(summary.precision, 2 / 3);
  assert.equal(summary.false_alert_rate, 1 / 2);
  assert.equal(summary.accuracy, 3 / 5);
  assert.equal(summary.scored_trials, 5);
  assert.equal(summary.unscored, 1);
});

test('empty denominators stay unknown and accuracy requires both trial types', () => {
  const empty = summarizeTrials([]);
  assert.equal(empty.recall, null);
  assert.equal(empty.precision, null);
  assert.equal(empty.accuracy, null);
  const negatives = summarizeTrials([{ outcome: 'true_negative' }]);
  assert.equal(negatives.recall, null);
  assert.equal(negatives.precision, null);
  assert.equal(negatives.accuracy, null);
  assert.equal(negatives.false_alert_rate, 0);
});
