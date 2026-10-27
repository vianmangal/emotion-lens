"""Report calculations use generated labels, never camera-accuracy claims."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.analyze_live_accuracy import analyze_exports, markdown, proportion


DETECTOR = {'model': 'generated-test-model', 'event_policy': {
    'entry': .75, 'exit': .35, 'entry_seconds': .3, 'quiet_seconds': 2, 'cooldown': 0}}
SCRIPT = Path(__file__).resolve().parents[3] / 'scripts/analyze_live_accuracy.py'


def trial(index, expected='hit', detected=True, coverage=1, unscored=False):
    outcome = ('true_positive' if detected else 'false_negative') if expected == 'hit' else (
        'false_positive' if detected else 'true_negative')
    return {'started_at': (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index * 10)).isoformat(),
            'expected': expected, 'detected': detected, 'outcome': 'unscored' if unscored else outcome,
            'invalid_reason': 'Operator did not confirm the motion.' if unscored else None,
            'duration_ms': 6000, 'tracking_coverage': coverage, 'inference_frames': 60,
            'detector': deepcopy(DETECTOR)}


def export(rows, model=None):
    result = {'version': 1, 'detector': deepcopy(DETECTOR), 'trials': deepcopy(rows),
              'summary': {'recall': 1, 'accuracy': 1, 'true_positive': 999}}
    if model:
        result['detector']['model'] = model
        for row in result['trials']:
            row['detector']['model'] = model
    return result


def test_recomputes_counts_keeps_low_tracking_misses_and_explains_failures():
    payload = export([trial(0), trial(1, detected=False, coverage=.3), trial(2, detected=False, coverage=.95),
                      trial(3, 'normal', True), trial(4, 'normal', False), trial(5, unscored=True)])
    group = analyze_exports([payload])['groups'][0]
    assert group['counts'] == dict(true_positive=1, false_negative=2, false_positive=1, true_negative=1, unscored=1)
    assert group['scored_trials'] == 5
    assert group['metrics']['recall']['value'] == 1 / 3
    assert group['metrics']['recall']['denominator'] == 3
    assert group['metrics']['precision']['value'] == .5
    assert group['metrics']['accuracy']['value'] == .4
    assert [issue['category'] for issue in group['issues']] == [
        'miss_with_tracking_loss', 'miss_with_clear_tracking', 'false_alert']
    assert group['unscored_reasons'] == {'Operator did not confirm the motion.': 1}


def test_intervals_remain_uncertain_at_small_sample_and_match_reference_values():
    assert proportion(0, 0)['value'] is None
    assert proportion(0, 0)['interval_95'] is None
    assert proportion(50, 100)['interval_95'] == pytest.approx([.40383153, .59616847])
    assert proportion(10, 10)['interval_95'] == pytest.approx([.7224672, 1])
    assert proportion(0, 10)['interval_95'] == pytest.approx([0, .2775328])
    assert proportion(1, 1)['interval_95'][0] < .21


def test_empty_unscored_and_single_class_data_are_not_reported_as_measured_accuracy():
    empty = analyze_exports([{'version': 1, 'trials': [], 'detector': None}])
    assert empty['groups'] == [] and 'unmeasured' in markdown(empty)
    unscored = analyze_exports([export([trial(0, unscored=True)])])['groups'][0]
    assert unscored['scored_trials'] == 0
    assert all(metric['value'] is None for metric in unscored['metrics'].values())
    hits = analyze_exports([export([trial(0)])])['groups'][0]
    assert hits['missing_trial_types'] == ['normal']
    assert hits['metrics']['accuracy']['value'] is None
    assert hits['metrics']['false_alert_rate']['value'] is None


def test_overlapping_exports_are_deduplicated_and_conflicting_labels_rejected():
    a, b = trial(0), trial(1)
    result = analyze_exports([export([a, b]), export([a])])
    assert result['duplicate_trials_ignored'] == 1
    assert result['groups'][0]['scored_trials'] == 2
    with pytest.raises(ValueError, match='Conflicting results'):
        analyze_exports([export([a]), export([trial(0, 'normal', True)])])


def test_model_or_policy_changes_are_never_pooled():
    changed = export([trial(0)])
    changed['detector']['event_policy']['entry'] = .8
    changed['trials'][0]['detector']['event_policy']['entry'] = .8
    report = analyze_exports([export([trial(0)]), export([trial(0)], model='another-model'), changed])
    assert len(report['groups']) == 3
    assert all(group['scored_trials'] == 1 for group in report['groups'])
    inconsistent = export([trial(0)])
    inconsistent['trials'][0]['detector']['model'] = 'another-model'
    with pytest.raises(ValueError, match='differs from its export'):
        analyze_exports([inconsistent])


@pytest.mark.parametrize('field,value', [
    ('tracking_coverage', float('nan')), ('tracking_coverage', float('inf')),
    ('tracking_coverage', 1.01), ('tracking_coverage', True), ('duration_ms', 0),
    ('inference_frames', True), ('inference_frames', 0), ('detected', 1),
    ('outcome', 'false_negative'), ('invalid_reason', 'Interrupted'),
    ('started_at', '2026-01-01T00:00:00'),
])
def test_bad_trial_fields_cannot_inflate_metrics(field, value):
    row = trial(0); row[field] = value
    with pytest.raises(ValueError):
        analyze_exports([export([row])])


def test_report_copies_only_relevant_data_and_escapes_model_and_reason_markup():
    row = trial(0, unscored=True)
    row.update(jpeg='PRIVATE_FRAME', phone_number='PRIVATE_CONTACT')
    row['invalid_reason'] = '`\n[click](https://example.invalid)'
    payload = export([row], model='model`\n<script>alert(1)</script>')
    result = analyze_exports([payload])
    assert 'PRIVATE_' not in json.dumps(result)
    text = markdown(result)
    assert 'Model: `model\' <script>alert(1)</script>`' in text
    assert '95% Wilson' in text and 'cannot estimate continuous false alerts per hour' in text


def test_cli_runs_without_app_services_and_never_overwrites_input_or_existing_output(tmp_path):
    source = tmp_path / 'export.json'
    source.write_text(json.dumps(export([trial(0), trial(1, 'normal', False)])))
    original = source.read_bytes()
    output = tmp_path / 'report.json'
    command = [sys.executable, str(SCRIPT), str(source), '--format', 'json', '--output', str(output)]
    first = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert json.loads(output.read_text())['groups'][0]['metrics']['accuracy']['value'] == 1
    second = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert second.returncode == 2 and 'File exists' in second.stderr
    assert source.read_bytes() == original
    bad = subprocess.run([sys.executable, str(SCRIPT), str(source), '--clear-coverage', 'nan'],
                         cwd=tmp_path, capture_output=True, text=True)
    assert bad.returncode == 2 and 'finite number' in bad.stderr
