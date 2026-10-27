# Explain live detection results

The live screen already exports operator-confirmed staged trials through **Test detection accuracy → Export test results**. This local analyzer turns those exports into a failure review, without starting the app, accessing the camera, loading models, recording video or calling anyone. Python's standard library is sufficient.

From the repository root:

```bash
python3 scripts/analyze_live_accuracy.py ~/Downloads/emotion-lens-live-accuracy.json
```

Save a new Markdown report, or use `--format json` for machine-readable output:

```bash
python3 scripts/analyze_live_accuracy.py export-before.json export-after.json --output data/quality-review.md
```

Existing output files are never overwritten. Overlapping exports are deduplicated by detector identity and trial timestamp. Conflicting labels for the same trial are rejected so they can be resolved explicitly.

## What the report explains

- Recomputed counts, precision, hit recall, ordinary-gesture false-alert rate and trial accuracy. It ignores cached summary percentages in the input.
- Counts and 95% Wilson intervals beside each measured rate. A tiny perfect sample still has substantial uncertainty. Rates without the required trials remain unmeasured; trial accuracy requires both hit and normal trials.
- Missed attempts with clear tracking versus missed attempts with tracking loss, plus timestamps for every miss and false alert. **All scored misses stay in recall**, including poor-tracking trials.
- Discarded or interrupted trials and their reasons, kept separate from scored results.
- Separate results for different exported models or settings, rather than pooling the before/after results into one percentage.

“Clear tracking” defaults to at least 90% tracking coverage during a trial. Change that diagnostic threshold with `--clear-coverage 0.95`. It changes the failure categories only; it never changes the confusion counts or detector thresholds. Coverage suggests where to investigate and does not establish why a motion was missed.

## Limits

The analyzer trusts the operator's confirmation of which action actually happened. It cannot verify labels from video. The current export does not label the acting side, so the report cannot establish equal left/right detection performance. It also lacks code/model-weight checksums, so grouping reflects exported identities and settings only.

Wilson intervals assume independent trials. Repeating motions with the same people and camera can violate that assumption; these intervals are not a guarantee about future people or settings. Timed trials also cannot establish a continuous false-alerts-per-hour rate. Use separate participants/sessions for held-out evaluation as described in [the evaluation guide](SAFETY_EVALUATION.md).

This tool does not retrain a model, change live settings, enable phone calls or mark the detector qualified.

The workflow follows the article's emphasis on realistic validation, explainability and operator feedback: [Palo Alto Networks: AI in Threat Detection](https://www.paloaltonetworks.in/cyberpedia/ai-in-threat-detection). The interval calculation follows [NIST's Wilson interval formulas](https://itl.nist.gov/div898/handbook/prc/section2/prc241.htm).
