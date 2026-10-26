"""Grouped MIL training on frozen public-video features; never qualifies calls.

Mirrored/static views stay in their source group. Groups are source sequence or
pair indices, not verified independent participants. Positive clips have weak
window labels: MIL needs one striking window, rather than labeling idle windows
as strikes. See docs/VISUAL_STRIKE_MODEL.md for sources and limitations.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
import torch


def source_group(row):
    name = Path(row['path']).stem
    if row['path'].startswith('limu/'):
        return 'limu/' + name.rsplit('_', 1)[1]
    if row['path'].startswith('ut-interaction/'):
        return 'ut/' + name.split('_')[1]
    raise ValueError('Unknown feature source group')


def fit(x, y, keys, indices):
    torch.manual_seed(7)
    scaler = StandardScaler().fit(x[indices])
    features = torch.from_numpy(scaler.transform(x[indices]).astype(np.float32))
    head = torch.nn.Sequential(torch.nn.Linear(1024, 32), torch.nn.ReLU(), torch.nn.Linear(32, 1))
    optimizer = torch.optim.Adam(head.parameters(), lr=.005)
    local_y, local_keys = y[indices], keys[indices]
    bags = [np.flatnonzero((local_keys == key) & (local_y == 1))
            for key in sorted(set(local_keys[local_y == 1]))]
    negatives = np.flatnonzero(local_y == 0)
    if not bags or not len(negatives):
        raise ValueError('Training folds need both positive bags and negative observations')
    for _ in range(350):
        logits = head(features)[:, 0]
        positives = torch.stack([logits[bag].max() for bag in bags])
        loss = (.5 * torch.nn.functional.softplus(-positives).mean() +
                .5 * torch.nn.functional.softplus(logits[negatives]).mean() +
                1e-4 * sum(parameter.square().sum() for parameter in head.parameters()))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    return scaler, head


def artifact(scaler, head):
    return {'version': 1, 'kind': 'mlp', 'frames': 32, 'fps': 10,
            'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist(),
            'parameters': {key: value.detach().numpy().tolist() for key, value in head.state_dict().items()}}


def summarize(predictions, labels, rows, keys):
    bags = defaultdict(list)
    for i, row in enumerate(rows):
        if row['window'] != 'static':
            bags[keys[i]].append(i)
    counts = defaultdict(lambda: [0, 0, 0, 0])
    results = []
    for indices in bags.values():
        expected = bool(labels[indices[0]])
        score = float(predictions[indices].max())
        detected = score >= .75
        row = rows[indices[0]]
        dataset = 'limu' if row['path'].startswith('limu/') else 'ut'
        results.append({'path': row['path'], 'mirrored': row['mirrored'], 'expected': expected, 'score': score})
        outcome = 0 if expected and detected else 1 if not expected and detected else 2 if expected else 3
        for group in ('all', dataset):
            counts[group][outcome] += 1
    metrics = {}
    for group, (tp, fp, fn, tn) in counts.items():
        metrics[group] = {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                          'precision': tp / (tp + fp) if tp + fp else None,
                          'recall': tp / (tp + fn) if tp + fn else None,
                          'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}
    return metrics, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1] / 'data/public-evaluation')
    parser.add_argument('--features', nargs='+', type=Path, help='NPZ files from extract_visual_features.py')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--folds', type=Path, help='Also export excluded-source heads for causal replay checks')
    args = parser.parse_args()
    paths = args.features or [args.root / name for name in ['visual-training-features.npz', 'visual-extra-features.npz']]
    matrices, labels, rows = [], [], []
    for path in paths:
        with np.load(path, allow_pickle=False) as data:
            matrices.append(data['x'])
            labels.append(data['y'])
            rows.extend(json.loads(str(item)) for item in data['metadata'])
    x, y = np.concatenate(matrices), np.concatenate(labels)
    if x.ndim != 2 or x.shape[1] != 1024 or len(x) != len(y) or len(rows) != len(y) or not np.isfinite(x).all():
        raise ValueError('Invalid feature dimensions or values')
    if any(label not in (0, 1) for label in y):
        raise ValueError('Expected binary weak labels')
    groups = np.array([source_group(row) for row in rows])
    keys = np.array([row['path'] + str(row['mirrored']) for row in rows])
    torch.set_num_threads(4)
    predictions = np.zeros(len(y))
    manifest = {'groups': {}, 'heads': {}}
    if args.folds:
        args.folds.mkdir(parents=True, exist_ok=True)
    for fold, (train, test) in enumerate(GroupKFold(5).split(x, y, groups)):
        scaler, head = fit(x, y, keys, train)
        with torch.inference_mode():
            predictions[test] = head(torch.from_numpy(scaler.transform(x[test]).astype(np.float32)))[:, 0].sigmoid().numpy()
        if args.folds:
            content = {**artifact(scaler, head), 'training_groups': sorted(set(groups[train])),
                       'held_out_groups': sorted(set(groups[test]))}
            path = args.folds / f'fold-{fold}.json'
            path.write_text(json.dumps(content, separators=(',', ':')) + '\n')
            manifest['heads'][str(fold)] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for group in content['held_out_groups']:
                manifest['groups'][group] = str(fold)
        print(f'Finished grouped fold {fold + 1}/5', flush=True)
    metrics, results = summarize(predictions, y, rows, keys)
    scaler, head = fit(x, y, keys, np.arange(len(y)))
    result = {**artifact(scaler, head), 'groups': sorted(set(groups)), 'metrics': metrics,
              'feature_sha256': [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths],
              'note': 'Development validation; mirrored copies correlated; participants may overlap. Not qualified for calls.'}
    target = args.output or args.root / 'visual-mil-head-rebuilt.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + '\n')
    args.root.mkdir(parents=True, exist_ok=True)
    (args.root / 'visual-mil-cv-rebuilt.json').write_text(json.dumps({'metrics': metrics, 'clips': results}, indent=2) + '\n')
    if args.folds:
        (args.folds / 'folds.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
