# Live Safety model feasibility report

Updated 2026-10-22. **Engineering prototype runs live; detector qualification is unmet.** There are no held-out human action recordings/results. Automatic real calls stay locked. This report does not claim measured violence recognition or pre-contact prediction.

## Actual stack and artifacts

| Stage | Implementation |
| --- | --- |
| Capture | Browser getUserMedia, video only; JPEG at up to 640×480, target 10 analyzed FPS |
| Person detection / pose | MediaPipe 0.10.21 PoseLandmarker Lite, image mode, maximum 4 poses; integrated person detector and 33-landmark pose model |
| Tracking | Repository centroid matcher on shoulders/hips; unique assignment; ambiguous proximity, missing tracks, and identity discontinuity reset temporal history |
| Baseline | Directed wrist trajectory relative to its shoulder, trailing 0.35-second motion with stable history; no single-frame action decision |
| Pretrained temporal candidate | MMAction2 STGCN, NTU60 XSub COCO-17 2D joint checkpoint, 60 output classes, PyTorch CPU |
| Runtime decision | Visibility/temporal abstention, supported action and directed motion gates, hysteresis, one incident per episode |

Artifacts are fetched only by `scripts/download_models.py` from the official URLs in `scripts/model_artifacts.json`; they are ignored by Git. SHA256 values were calculated from the downloaded official files and pinned here, not invented or claimed as independently published upstream signatures.

| File | Bytes | SHA256 |
| --- | ---: | --- |
| `pose_landmarker_lite.task` | 5,777,746 | `59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a` |
| `stgcn_ntu60.pth` | 12,479,895 | `484a394a50246032fef9694396096902909784e8618ccc845d2859dc2b952fea` |

The bundle's TFLite input tensors were inspected: `pose_detector.tflite` takes float32 `[1,224,224,3]`, and `pose_landmarks_detector.tflite` takes float32 `[1,256,256,3]`. MediaPipe's official task API performs internal crop/resize/normalization; the app supplies RGB image pixels and uses normalized image coordinates. These tensor resolutions differ from the external camera frame. The existing optional TensorFlow environment was used only in a separate inspection process, not as a safety runtime dependency.

MMAction2 source is pinned to `4d6c93474730cad2f25e51109adcf96824efc7a3` (v1.2.0). Its PyPI wheel was tried and failed because it omitted `mmaction.models.localizers.drn`. The generic dependency set also requested `decord`, with no matching macOS ARM wheel. An isolated source installation, without irrelevant generic video-loader extras, successfully loaded and ran the checkpoint. `scripts/setup_temporal.py` reproduces that path. No source hacks or fake framework modules are used.

Code sources: [MediaPipe Python guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python), [official STGCN config](https://github.com/open-mmlab/mmaction2/blob/v1.2.0/configs/skeleton/stgcn/stgcn_8xb16-joint-u100-80e_ntu60-xsub-keypoint-2d.py), and [official demo/checkpoint reference](https://github.com/open-mmlab/mmaction2/blob/v1.2.0/demo/README.md).

## Preprocessing and decision contract

MediaPipe → COCO mapping is `[0,2,5,7,8,11,12,13,14,15,16,23,24,25,26,27,28]`: nose, left/right eyes, ears, shoulders, elbows, wrists, hips, knees, ankles. Coordinates remain in the unmirrored image coordinate system; the UI mirrors video and overlays together. Off-screen coordinates do not count as visible landmarks. Visibility/presence confidence below 0.55 on relevant arms causes abstention. Tracking is an experimental image-space association, not person identification.

Baseline: at least 8 observations and 0.7 seconds of stable history, bounded to 1.2 seconds/120 samples. Require two observed people, source arm visibility and target torso visibility, wrist speed above 2 shoulder widths per second, alignment above 0.8 toward the other participant, extension above 0.9 shoulder widths, and wrist-to-target-center proximity below 2.5 shoulder widths. Relative wrist/shoulder motion reduces whole-body translation artifacts. These are dimensionless image-space rules; they do not estimate physical distance, impact, or intent.

STGCN: at least 24 observations and 3 seconds of stable history, bounded to 3.3 seconds/120 samples. Convert normalized coordinates back to pixels using actual image dimensions and preserve keypoint confidence. Run upstream `PreNormalize2D → GenSkeFeat(coco,j) → UniformSampleFrames(100, one clip, deterministic seed 255) → PoseDecode → FormatGCNInput(two people) → PackActionInputs`. One clip matches upstream validation; upstream test uses ten. The classifier receives a uniformly sampled complete temporal window, not one frame. The checkpoint was trained using a different pose extraction pipeline; MediaPipe-to-COCO coordinate compatibility does not establish distribution equivalence.

Class mapping: [NTU60 labels](https://github.com/open-mmlab/mmaction2/blob/v1.2.0/tools/data/skeleton/label_map_ntu60.txt), zero-based **49** punching/slapping another person (A50) and **50** kicking another person (A51). Index 51 is pushing and is excluded. The initial adapter incorrectly shifted these by one; v2 corrected the mapping; v3 also uses the same directed participant pair for model input and motion gating. Explicit regression tests cover both fixes. The adapter also requires the directed-arm baseline gate. That gate narrows coverage to arm interactions; kicks without arm evidence will abstain. Class scores are model outputs, not probabilities of harmful intent.

Current experimental policy: entry ≥0.75 for 0.3 seconds, exit ≤0.35 with 2 seconds quiet, 30 seconds cooldown after episode end. Frame gaps above 1 second invalidate monitoring and require explicit rearming; frame replacement resets incompatible history. These thresholds are developer defaults, **not calibrated values frozen after a human development set**. STGCN's evidence window alone exceeds the desired 2-second median alert target for some events. No threshold was adjusted against held-out results.

## Hardware and measurements

Apple M4, 16 GiB, macOS 27.0.1 arm64, Python 3.11.15. MediaPipe uses TensorFlow Lite XNNPACK CPU inference; its startup also initializes the system GL context. STGCN explicitly uses `device=cpu`; no CUDA or MPS/Apple acceleration claim is made. Exact package snapshots are under `docs/dependency-snapshots/` and measured output in `SAFETY_BENCHMARK.json`.

Reproduce: `.venv-model/bin/python scripts/benchmark_models.py`.

| Generated-data measurement | Observed result |
| --- | --- |
| Empty 640×480 pose input, after warm-up | median 7.51 ms, p95 12.70 ms |
| STGCN, stationary two-person synthetic window | median 27.28 ms, p95 31.99 ms |
| STGCN, directed-arm synthetic window | median 26.29 ms, p95 31.22 ms |
| Baseline, directed-arm synthetic window | about 0.468 ms |
| Peak process RSS for combined benchmark | 496,353,280 bytes (~473 MiB) |
| Local HTTP/WebSocket + JPEG decode + actual pose inference, 50 blank frames at 10 FPS | median reported age 19.5 ms, p95 24.55 ms; zero people; abstention |

Those rates exclude real person pose computation costs, camera acquisition, browser permission/UI, and model evidence-window delay. They are not a two-person webcam throughput benchmark. The historical 50-frame transport measurement used first-frame alignment. Current arming supplies a fresh monotonic client-clock sample before image capture, so a stale first frame is rejected. Server age retains one-way network alignment uncertainty; the UI directly computes browser capture-to-result age. Neither is a physical sensor latency measurement.

Synthetic comparison: stationary and waving fixtures produced no accepted action for either classifier; lone-person fixtures abstained. The trajectory baseline scored the directed-arm fixture ~0.93. STGCN's highest class for that artificial fixture was index 53 (pointing at the other person), so it produced **no accepted action**. This is useful evidence that a loaded pretrained model is not a qualified detector. Synthetic bodies do not establish real-world accuracy. The JSON benchmark records the outputs without replacing them with expected labels.

## Licensing / qualification limits

[MediaPipe code](https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE) and [MMAction2 code](https://github.com/open-mmlab/mmaction2/blob/v1.2.0/LICENSE) use Apache-2.0. Google’s [official pose guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker) links the Lite download to the [BlazePose GHUM 3D model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20BlazePose%20GHUM%203D.pdf). That card explicitly covers Lite, Full and Heavy (page 1) and states Apache-2.0 (page 2), providing upstream model-family license evidence beyond the code license. The 2021 card evaluates single-person crops and lists multiple people, hidden heads and distant people outside its scope. The newer task API permits multiple poses; that does not establish interaction accuracy. Artifacts are downloaded from official references and not redistributed here. STGCN checkpoint rights and inherited NTU data conditions remain unresolved; qualification also lacks real participant/session-separated evaluation.

Decision: keep both adapters available for **experimental live local use** and reproducible replay, default to the understandable trajectory baseline, and lock automatic real calls. STGCN is technically usable on this machine, but neither adapter has passed human positive/hard-negative or continuous benign evaluation. The owner's request is for live operation; no prerecorded clip is required to operate it. Without evaluation data, accuracy targets remain unmeasured, and the overall qualified detector feature remains unfinished.

The [NTU dataset publisher](https://rose1.ntu.edu.sg/dataset/actionRecognition/) confirms participant consent, but requires registration/approval and an academic non-commercial release agreement for dataset access, and restricts redistribution/derived datasets. No NTU footage or skeleton dataset was downloaded for evaluation. These dataset terms do not by themselves resolve rights for the separate STGCN checkpoint. A [MediaPipe maintainer clarification](https://github.com/google-ai-edge/mediapipe/issues/6306) separately describes the versioned Full bundle as Apache-2.0. The Lite evidence above comes from its official model-card link. Neither source resolves the separate NTU/STGCN conditions.

Public evaluation candidate inspected: [UT-Interaction](https://cvrc.ece.utexas.edu/SDHA2010/Human_Interaction.html) provides short staged interaction sequences with labels, but does not provide a clear artifact redistribution/license statement on the inspected page and cannot supply the required hour of continuous benign webcam footage. It has not been downloaded or represented as the held-out webcam evaluation.

For more than two visible people, v3 selects the baseline candidate's source/target IDs for the temporal tensor. It does not combine a score for the first two tracked people with a motion gate for unrelated bystanders. Unreliable relevant landmarks clear history, requiring warm-up after occlusion. These correctness fixes do not supply missing human evaluation or calibrated thresholds.
