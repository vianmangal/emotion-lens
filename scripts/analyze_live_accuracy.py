"""Explain existing live-trial JSON exports locally; no camera, server or calls."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path


OUTCOMES = ('true_positive', 'false_negative', 'false_positive', 'true_negative', 'unscored')
POLICY_FIELDS = ('entry', 'exit', 'entry_seconds', 'quiet_seconds', 'cooldown')
LIMITS = [
    'Results describe operator-confirmed staged trials, not general real-world accuracy.',
    '95% Wilson intervals assume independent trials; repeated people and settings can make that assumption inaccurate.',
    'Low-tracking misses remain in recall. Coverage can suggest a contributor, not prove the cause of a miss.',
    'Timed gesture trials cannot estimate continuous false alerts per hour.',
    'Exports do not label the acting side, so equal left/right performance cannot be established here.',
    'Grouping uses exported detector identities/settings; exports do not contain code or model-weight checksums.',
]


def finite_number(value, name, minimum=0, maximum=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value < minimum or (maximum is not None and value > maximum)):
        raise ValueError(f'{name} must be a finite number in the allowed range')
    return float(value)


def detector_identity(detector):
    if not isinstance(detector, dict) or not isinstance(detector.get('model'), str) or not detector['model'].strip():
        raise ValueError('Every trial needs its exported detector model and event policy')
    policy = detector.get('event_policy')
    if not isinstance(policy, dict) or any(key not in policy for key in POLICY_FIELDS):
        raise ValueError('Incomplete detector event policy')
    values = {key: finite_number(policy[key], f'event_policy.{key}', maximum=1 if key in ('entry', 'exit') else None)
              for key in POLICY_FIELDS}
    if values['exit'] >= values['entry']:
        raise ValueError('Detector exit threshold must be below its entry threshold')
    # Include any future metadata in the identity, but do not copy arbitrary
    # input fields (images, contact data, etc.) into the resulting report.
    canonical = json.dumps({**detector, 'event_policy': {**policy, **values}}, sort_keys=True,
                           separators=(',', ':'), allow_nan=False)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    return fingerprint, {'model': detector['model'], 'event_policy': values}


def validate_trial(row):
    if not isinstance(row, dict) or row.get('expected') not in ('hit', 'normal') or type(row.get('detected')) is not bool:
        raise ValueError('Each trial needs expected=hit/normal and a boolean detected value')
    outcome = row.get('outcome')
    if outcome not in OUTCOMES:
        raise ValueError('Invalid trial outcome')
    expected_outcome = ('true_positive' if row['detected'] else 'false_negative') if row['expected'] == 'hit' else (
        'false_positive' if row['detected'] else 'true_negative')
    if outcome != 'unscored' and (outcome != expected_outcome or row.get('invalid_reason')):
        raise ValueError('Trial outcome contradicts its action, detection or interruption')
    reason = row.get('invalid_reason')
    if reason is not None and not isinstance(reason, str):
        raise ValueError('Trial invalid_reason must be text or null')
    timestamp = row.get('started_at')
    if not isinstance(timestamp, str):
        raise ValueError('Each trial needs a timestamp with a timezone')
    try:
        started = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if started.tzinfo is None:
            raise ValueError('Missing timezone')
        timestamp = started.astimezone(timezone.utc).isoformat()
    except ValueError as exc:
        raise ValueError('Invalid trial timestamp; include its timezone') from exc
    frames = row.get('inference_frames')
    if type(frames) is not int or frames < 0 or (outcome != 'unscored' and frames == 0):
        raise ValueError('Scored trials need at least one inference frame')
    duration = finite_number(row.get('duration_ms'), 'duration_ms')
    if duration == 0:
        raise ValueError('Trial duration must be positive')
    coverage = finite_number(row.get('tracking_coverage'), 'tracking_coverage', maximum=1)
    identity, detector = detector_identity(row.get('detector'))
    return identity, detector, {'started_at': timestamp, 'expected': row['expected'], 'detected': row['detected'],
                                'outcome': outcome, 'invalid_reason': reason, 'duration_ms': duration,
                                'tracking_coverage': coverage, 'inference_frames': frames}


def proportion(successes, total):
    """Two-sided 95% Wilson interval; undefined rates stay unmeasured."""
    if total == 0:
        return {'numerator': successes, 'denominator': 0, 'value': None, 'interval_95': None}
    p = successes / total
    z2 = 1.959963984540054 ** 2
    denominator = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denominator
    half = math.sqrt(z2 * (p * (1 - p) / total + z2 / (4 * total ** 2))) / denominator
    return {'numerator': successes, 'denominator': total, 'value': p,
            'interval_95': [0. if successes == 0 else max(0., center - half),
                            1. if successes == total else min(1., center + half)]}


def summarize(detector, trials, clear_coverage):
    trials = sorted(trials, key=lambda row: row['started_at'])
    counts = {outcome: 0 for outcome in OUTCOMES}
    counts.update(Counter(row['outcome'] for row in trials))
    tp, fn, fp, tn = (counts[key] for key in OUTCOMES[:4])
    scored = [row for row in trials if row['outcome'] != 'unscored']
    issues = []
    for row in scored:
        if row['outcome'] in ('false_negative', 'false_positive'):
            category = ('miss_with_clear_tracking' if row['tracking_coverage'] >= clear_coverage else
                        'miss_with_tracking_loss') if row['outcome'] == 'false_negative' else 'false_alert'
            issues.append({key: row[key] for key in ('started_at', 'outcome', 'tracking_coverage')} | {'category': category})
    duration = sum(row['duration_ms'] for row in scored)
    return {'detector': detector, 'counts': counts, 'scored_trials': len(scored),
            'metrics': {'recall': proportion(tp, tp + fn), 'precision': proportion(tp, tp + fp),
                        'false_alert_rate': proportion(fp, fp + tn),
                        'accuracy': proportion(tp + tn, len(scored)) if tp + fn and fp + tn else proportion(0, 0)},
            'scored_tracking_coverage': sum(row['tracking_coverage'] * row['duration_ms'] for row in scored) / duration if duration else None,
            'issues': issues,
            'unscored_reasons': dict(Counter(row['invalid_reason'] or 'Operator did not confirm the action/timing.'
                                            for row in trials if row['outcome'] == 'unscored')),
            'missing_trial_types': [name for name, count in [('hit', tp + fn), ('normal', fp + tn)] if not count]}


def analyze_exports(payloads, clear_coverage=.9):
    clear_coverage = finite_number(clear_coverage, 'clear_coverage', maximum=1)
    groups, seen, duplicates = {}, {}, 0
    for payload in payloads:
        if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] != 1:
            raise ValueError('Unsupported live export version; expected version 1')
        rows = payload.get('trials')
        if not isinstance(rows, list):
            raise ValueError('Live export must contain a trials list')
        # Ignore the supplied summary: recompute every denominator from rows.
        export_identity = detector_identity(payload.get('detector'))[0] if rows else None
        for row in rows:
            identity, detector, normalized = validate_trial(row)
            if identity != export_identity:
                raise ValueError('Trial detector differs from its export detector')
            key = (identity, normalized['started_at'])
            if key in seen:
                if seen[key] != normalized:
                    raise ValueError('Conflicting results for the same detector and trial timestamp')
                duplicates += 1
                continue
            seen[key] = normalized
            groups.setdefault(identity, {'detector': detector, 'trials': []})['trials'].append(normalized)
    return {'version': 1, 'scope': 'Preliminary staged live trials; not detector qualification.',
            'clear_tracking_threshold': clear_coverage, 'duplicate_trials_ignored': duplicates,
            'groups': [{'settings_fingerprint': identity, **summarize(group['detector'], group['trials'], clear_coverage)}
                       for identity, group in sorted(groups.items())], 'limitations': LIMITS.copy()}


def markdown(report):
    def code(value):
        return '`' + str(value).replace('`', "'").replace('\n', ' ').replace('\r', ' ') + '`'

    lines = ['# Live detection quality report', '', report['scope'], '',
             f"Duplicate trial rows ignored: {report['duplicate_trials_ignored']}.", '',
             f"Clear-tracking diagnostic threshold: {report['clear_tracking_threshold']:.0%}. This is not a qualification threshold.", '']
    if not report['groups']:
        lines += ['No trial data. Detection accuracy is unmeasured.', '']
    for index, group in enumerate(report['groups'], 1):
        counts = group['counts']
        lines += [f'## Detector {index}', '', f"Model: {code(group['detector']['model'])}", '',
                  f"Settings fingerprint: {code(group['settings_fingerprint'])}", '',
                  f"Scored: {group['scored_trials']}; unscored: {counts['unscored']}.", '',
                  f"Detected attempts: {counts['true_positive']}; missed attempts: {counts['false_negative']}; "
                  f"false alerts: {counts['false_positive']}; correctly clear: {counts['true_negative']}.", '',
                  '| Metric | Result | Counts | 95% Wilson interval |', '| --- | --- | --- | --- |']
        for name, metric in group['metrics'].items():
            value = 'Unmeasured' if metric['value'] is None else f"{metric['value']:.1%}"
            interval = '—' if metric['interval_95'] is None else '–'.join(f'{bound:.1%}' for bound in metric['interval_95'])
            lines.append(f"| {name.replace('_', ' ').capitalize()} | {value} | {metric['numerator']}/{metric['denominator']} | {interval} |")
        lines.append('')
        coverage = group['scored_tracking_coverage']
        lines += ['Mean clear tracking during scored trials: ' + ('Unmeasured' if coverage is None else f'{coverage:.1%}') + '.', '']
        if group['missing_trial_types']:
            lines += ['Missing scored trial types: ' + ', '.join(group['missing_trial_types']) + '.', '']
        issues = Counter(issue['category'] for issue in group['issues'])
        lines += [f"Misses with clear tracking: {issues['miss_with_clear_tracking']}; "
                  f"misses with tracking loss: {issues['miss_with_tracking_loss']}. Both remain in recall.", '']
        if group['issues']:
            lines += ['| Trial started (UTC) | Result | Clear tracking |', '| --- | --- | --- |']
            lines += [f"| {issue['started_at']} | {issue['category'].replace('_', ' ')} | {issue['tracking_coverage']:.1%} |"
                      for issue in group['issues']]
            lines.append('')
        for reason, count in group['unscored_reasons'].items():
            lines.append(f'- Unscored ({count}): {code(reason)}')
        lines.append('')
    lines += ['## Interpretation', ''] + [f'- {limit}' for limit in report['limitations']]
    lines += ['', 'This report does not train a model, change thresholds, record video or enable calls.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exports', nargs='+', type=Path, help='JSON files from Export test results')
    parser.add_argument('--format', choices=['markdown', 'json'], default='markdown')
    parser.add_argument('--output', type=Path, help='New output file; existing files are never overwritten')
    parser.add_argument('--clear-coverage', type=float, default=.9, help='Diagnostic tracking fraction (default .9); misses are never excluded')
    args = parser.parse_args()
    try:
        report = analyze_exports([json.loads(path.read_text(encoding='utf-8')) for path in args.exports], args.clear_coverage)
        result = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n' if args.format == 'json' else markdown(report)
        if args.output:
            with args.output.open('x', encoding='utf-8') as target:
                target.write(result)
        else:
            print(result, end='')
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
