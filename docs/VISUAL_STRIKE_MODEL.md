# Experimental local visual strike detector

Updated 2026-10-27. The default local demo uses learned RGB action recognition and independent person boxes. It replaces the wrist-trajectory baseline as the default because public two-person footage exposed frequent misses, ordinary-gesture false alerts and sensitivity to video orientation. It remains an experimental demonstration detector; qualification is false and automatic real calls remain locked.

## Runtime

1. Browser sends video-only JPEGs, quality 75, at a target 10 FPS and at most 640×480. Webcam pixels are not mirrored before inference; the UI mirrors video and overlays together.
2. MediaPipe EfficientDet-Lite2 int8 detects person boxes, with score ≥0.20 and area ≥1% of the image. A global centroid assignment supplies session-local track IDs. These are observed boxes, not fabricated pose landmarks. No skeleton is drawn in visual mode.
3. Exactly two detected people must be present now, and in at least 80% of the roughly 3.2-second RGB window. Warm-up requires at least 24 samples spanning three seconds, with adjacent sample gaps no greater than 500 ms. Missing wrists or shoulders do not independently remove a person box. A third foreground person prevents action inference.
4. A frozen Torchvision S3D Kinetics-400 encoder receives 32 uniformly sampled RGB frames at 10 FPS, resized to 256×256 and transformed by its official normalization/224-pixel center crop. A numeric 1024→32 ReLU→1 head scores possible striking motion.
5. One background inference job runs at a time, scheduled at most every 500 ms. The frame buffer and work queue are bounded; new camera frames do not wait for neural inference. Scores older than one second from their source frame abstain. Reset, long gaps and session changes discard incompatible windows/results. Runtime downloads nothing.
6. Live-only policy requires score ≥0.75 for 300 ms. An alert clears after score ≤0.35 for two seconds of ready evidence. Live-only cooldown is zero. Uncertain frames cannot open or close an episode. Alert delay includes the RGB window and inference time; this is not pre-contact prediction.

The score is not a calibrated probability of violence. The model labels a whole two-person window and highlights both tracks; it does not identify an attacker, infer intention, confirm contact or assess injury. Small/overlapping people, occlusion, a tight crop, poor lighting, new camera angles and unrelated fast gestures can cause misses or false alerts.

## Pinned artifacts

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| EfficientDet-Lite2 int8 | 7,515,971 | `b3f50554cb0ea559e90328845f7d9ba4d13c8bff372914d24e06bc8bb72fa896` |
| S3D Kinetics-400 | 33,524,997 | `d76dad2f4b2a6701ad7f64e85b294b2d1989f1ea0d3f8b240446ed2152850bbb` |
| Numeric strike head | 742,612 | `8c3131ffb8b43de564279fcb909b58f5fa28bbff6c10f126ecbf127b98daa5c2` |

Official upstream sources: [MediaPipe object detection](https://developers.google.com/edge/mediapipe/solutions/vision/object_detector), [Torchvision S3D](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.video.s3d.html). Exact download URLs and hashes are in `scripts/model_artifacts.json`. Downloads are ignored by Git; the small numeric head is versioned with the code. Torch loads the verified backbone with `weights_only=True`; the head uses validated numeric JSON.

## Public development footage and training

- [UT-Interaction, Ryoo and Aggarwal, SDHA 2010](https://cvrc.ece.utexas.edu/SDHA2010/Human_Interaction.html): both segmented sets, 120 original clips. Author label indices are 0 handshake, 1 hug, 2 kick, 3 point, 4 punch, 5 push. Only punch is a positive label for this head; other actions are development negatives.
- [LIMU, Kyushu University interaction dataset](https://limu.ait.kyushu-u.ac.jp/~resource/dataset/en/interaction_dataset.html): `punch_1..10.avi`, `handclap_1..10.avi`, `handshake_1..10.avi`, 30 originals. The source describes the first five clips as left-actor actions and the last five as right-actor actions. Clips can contain multiple repetitions. Only punch is positive. Other LIMU categories have not been evaluated here.

Original videos remain under ignored `data/public-evaluation/`; no webcam recording was collected. Source file hashes and effective validation-head hashes are recorded in the development report. Public availability is not a claim of unrestricted redistribution rights; source clips are not added to Git.

The frozen backbone generates 1024 features for 32-frame windows, stride 16, plus a terminal window. Short training clips are padded with their first frame. Mirrored variants and repeated-first-frame stationary negatives are included. The current training inputs contain 978 examples from 150 original videos. Only the small head is trained: standardization fitted on training data, 32 hidden units, seed 7, Adam learning rate 0.005, 350 epochs, balanced positive-bag/negative softplus loss and L2 penalty 0.0001. Multiple-instance training requires at least one positive window per positive clip rather than assigning idle portions a strike label.

Five-fold GroupKFold keeps each original, its mirrored copy and its static variants together. Groups are UT sequence indices and LIMU pair indices across categories. **They are not verified independent participants.** Each causal validation replay loads a head that excluded that source group; the checker verifies that exclusion and the artifact checksum. The shipped head is then trained on all development footage. Architecture, person thresholds and model selection used this development material, so these results are not an untouched test set or a webcam qualification.

## Measured full-pipeline development check

The final check replays all 30 selected LIMU videos in each orientation through actual JPEG decoding, person detection, tracking, RGB inference and the live-only event policy. Replay is causal; synchronous offline inference waits for its measured computation delay in source time before publishing a score. Cold-start warm-up and tracking failures remain in the clip denominator.

| Detector / orientation | Punch clips alerted | Ordinary clips falsely alerted |
| --- | ---: | ---: |
| Previous trajectory baseline / original | 4/10 | 6/20 |
| Previous trajectory baseline / mirrored | 3/10 | 5/20 |
| Learned visual, source-excluded head / original | 8/10 | 2/20 |
| Learned visual, source-excluded head / mirrored | 8/10 | 1/20 |

The final model still missed `punch_2` and `punch_7` in both orientations. Original-video false alerts occurred once among handclaps and once among handshakes; mirrored-video false alerts occurred once among handclaps. Mirrored copies are correlated views of the same source clips and must not be counted as additional independent trials. These are **clips with at least one alert**, not per-punch recall; the clips contain multiple actions. About 54% of all punch-clip frames were ready for action scoring, including cold-start warm-up in the denominator.

Machine-readable evidence: [development check](VISUAL_DEVELOPMENT_CHECK.json). The earlier UT baseline check found only 4/20 punch clips in original view and 2/20 mirrored. A complete final end-to-end UT comparison is not reported; many UT clips are shorter than the visual warm-up window. Feature-window cross-validation is also not interchangeable with the full pipeline numbers above.

No new participant webcam accuracy measurement has been performed for this model. The live trial panel uses four seconds to prepare, six seconds to act, two seconds to hold still for the model response, and 500 ms transport grace. This accounts for delayed video inference without labeling a second action as part of the first trial.

## Reproduction

From the repository root, use a separate Python 3.11 environment:

```bash
python3.11 -m venv .venv-visual
.venv-visual/bin/pip install -r backend/requirements-visual-training.txt
.venv-visual/bin/python scripts/download_models.py --visual
```

Obtain the author datasets from the links above, preserve original filenames, extract UT clips below `data/public-evaluation/ut-interaction/` and the selected LIMU files below `data/public-evaluation/limu/`. The scripts do not open a camera or invoke a phone provider.

```bash
.venv-visual/bin/python scripts/extract_visual_features.py --output data/public-evaluation/all-features.npz
.venv-visual/bin/python scripts/train_visual_strike.py --features data/public-evaluation/all-features.npz --output data/public-evaluation/retrained-head.json --folds data/public-evaluation/retrained-folds
.venv-visual/bin/python scripts/check_public_safety.py --dataset limu --model visual --fold-heads data/public-evaluation/retrained-folds/folds.json --output data/public-evaluation/retrained-check.json
.venv-visual/bin/python scripts/run_local.py
```

Floating-point/platform differences and the canonical sorted training order can change retrained weights; these commands reproduce the method, not a promise of bit-identical shipped weights. Use the pinned shipped hash to reproduce the installed runtime. Without `--fold-heads`, checks use the shipped all-data head and are regression checks on training material, not source-excluded validation.
