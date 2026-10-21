"""Event-level evaluation. Local consenting recordings only; split by participant/session."""
import argparse
import json
from pathlib import Path
import numpy as np
from replay import Detector, model_settings, replay


def match_events(predictions, truth, tolerance=4):
    # One-to-one greedy chronological onset matching in [onset, onset + tolerance].
    used = set(); delays = []; false = 0
    for predicted in sorted(predictions):
        matches = [(i, t) for i, t in enumerate(truth) if i not in used and 0 <= predicted - t <= tolerance]
        if matches:
            i, onset = min(matches, key=lambda x: abs(predicted - x[1]))
            used.add(i); delays.append(predicted - onset)
        else:
            false += 1
    return len(used), false, len(truth) - len(used), delays


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--model', choices=['baseline','stgcn'], default='baseline')
    parser.add_argument('--split', choices=['development','held_out'], default='held_out')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    rows = manifest['clips']
    for field in ('source', 'license', 'participants', 'session', 'angle', 'lighting', 'onsets', 'split', 'path', 'category'):
        if any(field not in c for c in rows): raise SystemExit(f'Manifest missing {field}')
    split_groups = {}
    for row in rows:
        for group in [f'participant:{p}' for p in row['participants']] + [f'session:{row["session"]}']:
            if group in split_groups and split_groups[group] != row['split']:
                raise SystemExit(f'Participant/session leakage across splits: {group}')
            split_groups[group] = row['split']
    selected = [c for c in rows if c['split'] == args.split]
    if not selected:
        raise SystemExit('No clips supplied; accuracy cannot be evaluated')
    detector = Detector(model_settings(args.model))
    if not detector.ready: raise SystemExit(detector.reason)
    results = []; tp = fp = fn = 0; delays = []; benign_seconds = 0; benign_alerts = 0
    try:
        for clip in selected:
            path = (args.manifest.parent / clip['path']).resolve()
            result = replay(path, detector)
            a,b,c,d = match_events([e['onset'] for e in result['events']], clip['onsets'])
            tp += a; fp += b; fn += c; delays.extend(d)
            if not clip['onsets']:
                benign_seconds += result['duration_seconds']; benign_alerts += b
            results.append({'path':clip['path'], **result, 'tp':a,'fp':b,'fn':c})
    finally:
        detector.close()
    summary = {'qualified': False, 'qualification_note':'Requires manual review of data coverage, thresholds, held-out targets and continuous footage; this script never unlocks calls.',
               'split':args.split, 'model':args.model, 'tp':tp,'fp':fp,'fn':fn, 'precision':tp/(tp+fp) if tp+fp else None,
               'recall':tp/(tp+fn) if tp+fn else None, 'false_alerts_per_hour':benign_alerts/(benign_seconds/3600) if benign_seconds else None,
               'onset_delay_median_seconds':float(np.median(delays)) if delays else None,
               'onset_delay_p95_seconds':float(np.percentile(delays,95)) if delays else None, 'clips':results}
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='clips'},indent=2))


if __name__ == '__main__': main()
