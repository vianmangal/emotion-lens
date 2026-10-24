# Current simplified live view verification

Updated 2026-10-24: the owner reported that motions by the person on the right side of the video were often missed. Live observation showed two-person tracking and alert display at 10 FPS, but an initial timed trial had only 38% clear tracking. That trial was discarded because the intended action was not confirmed. Temporary local numeric tracing then exposed a concrete identity-assignment bug: following a pose dropout, the greedy matcher could give an existing identity to a distant first observation even when a later observation was much closer. A dropout on either side also erased every participant's motion history.

The current baseline is `directed-wrist-trajectory-v4-independent-tracks`. Tracking now solves the small, complete assignment together, rejects genuinely ambiguous assignments, and is independent of pose return order. Visibility and identity breaks invalidate only the affected participant's contiguous observation window. After recovery, an arm needs three fresh positions spanning at least 200 ms, with two separately observed progress intervals; no trajectory may bridge its missing observations. Timestamp gaps and dropped-frame guards still reset monitoring. The optional STGCN adapter retains its additional three-second visibility requirement and has a new version identity.

Verification: 112 backend safety tests pass, including mirrored motions, both anatomical arms, reversed pose ordering, the identity-stealing regression, ambiguous tracking, and dropout/recovery sequences. Four generated recovery/bystander cases produced zero alerts before the fix and one after; hidden strikes, pose loss during the striking movement, reappearance jumps and single-frame glitches still produce zero. The generated mirror tests show equal alert behavior in both directions. These tests establish software behavior, not equal camera accuracy: a controlled right-side live retest and confirmed per-trial accuracy remain outstanding. Live-only calling and recording remain off. No participant images or video were saved by this diagnostic check.

Earlier 2026-10-23: `directed-wrist-trajectory-v3-arm-windows` fixes two motion-to-alert failures. Each moving arm now has its own contiguous visibility window, so a hidden unused arm or target wrist no longer clears every trajectory. The classifier scans recent multi-observation movements and retains a completed movement for 450 ms, allowing a short outward motion followed by immediate retraction to satisfy the existing 300 ms event confirmation. Pixel aspect ratio is respected; source body translation is removed. Two observed progress intervals are required so a single wrist-position glitch cannot become a sustained alert. In that version, missing moving-arm landmarks invalidated that arm's window and losing a shoulder cleared shared history.

Verification: 86 backend safety tests pass. New generated pose sequences exercise the actual detector, tracker, trajectory classifier and event policy together. The same short strike sequence produced zero alerts with the previous committed classifier and one with the new classifier, both with visible unused arms and with occluded unused arms. Stillness, a vertical wave, movement away, body translation, an occluded strike, a wrist reappearance jump and a single-frame wrist glitch produce no alerts. These are software regressions using generated landmarks, not camera-accuracy measurements. No participants were available for a new live action evaluation. Calls remain off; no AWS instance is required.

Earlier 2026-10-23: the webcam framing fix removes an unintended visible-hip requirement from the upper-body trajectory baseline and anchors track matching to visible shoulders rather than inferred off-screen hips. The previous baseline was `directed-wrist-trajectory-v2-upper-body`. The live UI distinguishes one tracked person and explains the framing needed. Verification at that point: 77 backend safety tests, three targeted Chromium checks (zero/one/two-person live UI and no calling), and a successful production build. A live webcam check returned two poses at 10 FPS, with arm occlusion still reported; stable real-world action accuracy remains unmeasured. This path uses the local Mac detector and requires no AWS instance.

Updated 2026-10-22 for the owner's revised scope: a live video feed, two-person tracking and possible-hit detection. History, phone/clip controls and the separate Arm step are removed from the current interface.

- 72 backend tests pass, including new live-only session guards and two synthetic hit episodes without incident storage or the incident cooldown.
- 10 Chromium browser tests pass for one-step Start, labeled two-person overlays, possible-hit display, keyboard controls, permission recovery, pause/resume, delayed-start cancellation, disconnect cleanup, stalled encoding and stale-overlay suppression. Browser action results use controlled server fixtures and a fake camera.
- The production frontend build succeeds. The backend uses the actual installed MediaPipe pose model and trajectory detector; engineering tests do not establish real two-person action accuracy.
- An additional smoke check against the running localhost API/WebSocket and installed MediaPipe model processed 10 generated blank frames in live-only mode, correctly returning zero people and no incident IDs. This checks integration, not human hit recognition.
- Live-only mode forces phone Off and clips Off, rejects attempts to enable either, avoids incident storage, and keeps the temporal evidence/visibility/freshness checks. The live view makes no history or phone API requests.

The archived 30-minute run predates live-only sessions and is not a 30-minute verification of this new path.

The reports below describe the earlier full incident/phone workflow and its separate model-evaluation gaps. Those original UI checks are historical evidence, not claims about controls in the current simplified screen. The original broad detector-qualification gate remains unmeasured; it does not prevent experimental live use.

---

## Earlier extended-workflow verification (through a34a7a2)

### Actual verification and remaining qualification

Updated 2026-10-22. **Live experimental implementation is available. Detector qualification and the overall qualified detector feature remain unfinished.** Automatic real calls are unavailable. No real provider request or physical webcam recording was made during automated verification.

## Engineering results

Commands run from the repository root:

```bash
.venv-safety/bin/python -m pytest -q
npm run build --prefix deep_fe/frontend
npm run test:e2e --prefix deep_fe/frontend
```

68 backend tests pass. Thirteen Playwright browser tests pass. The frontend production build succeeds. Tests use actual temporary SQLite databases, generated benign image/video fixtures, synthetic evidence, mocked provider transport, and Chromium's fake camera. No test dials a phone number. Additional regression coverage checks stopped/replaced session races, stalled JPEG encoding despite heartbeats, server-driven disarming, encoder/deletion races, full-storage cleanup, the corrected zero-based NTU punch class, same-pair temporal classification with bystanders, stale first-frame rejection, optional audio cleanup, and a keyboard-only live/control/review flow using Tab, Enter, Space and native-select type-ahead. Database initialization/read/claim failures preserve API health/local warnings and disable phone dispatch until restart. The preexisting HEIC test now uses a generated 64×64 white decoder fixture, avoiding a native HEIF-encoder crash observed when encoding after VP8 initialization on this machine. Production HEIC decoding and the upload contract still pass.

| Acceptance area | Evidence and limits |
| --- | --- |
| A1 local foundation | Default SQLite, real `/predict` persistence/JSON/UUID round trip, old upload/HEIC/rejection tests; fresh and repeated Alembic upgrade succeeds; no external database used |
| A2 separate readiness | No TensorFlow import on startup; missing pose configuration reports unavailable without crashing API; missing expression weights do not block safety |
| A3 resource lifecycle | Fake-camera browser tests check explicit start/arm, Stop/view cleanup, track termination, permission denial/retry, hidden-tab disarm, delayed arm/stop races, audio context closure and disconnect cleanup |
| A4 call gates | Unqualified automatic-real mode rejects arm; uncertainty/lone/undirected/gaps abstain; replay cannot enqueue automatic calls; real manual test needs explicit acknowledgement/configuration |
| A5 episodes | Policy positive/quiet/cooldown sequences and live transport integration create one persistent incident per continuous synthetic episode |
| A6 local boundary | Host/Origin rejection, capability checks, missing/wrong WebSocket auth, HTTP/message/JPEG dimension/byte limits, malformed images, nonfinite/backwards timestamps, path traversal and symlink rejection |
| A7 bounded work | Slow inference test replaces queued frames and counts drops; one active + one pending job; bounded history/clip rings; 18,000 synthetic time steps exercise buffer bounds; the separate actual 30-minute generated-input run is reported below |
| A8 clips | Actual VP8/WebM encode/decode; Chromium playback; partial clip finalized on disarm; encoder/deletion serialization and queued-encode cancellation; source gap/pre/post metadata; quota, retention and deletion tests. Physical webcam clips untested |
| A9 restart | Review labels/JSON survive another app instance; pending countdowns cancelled and submitting actions marked unknown; no automatic rearming/replay |
| A10 adapter | Mocked success, explicit rejection, invalid response, timeout/unknown, same-action duplicate claim, cancellation, one in flight, cooldown, rolling quota and restart recovery |
| A11 secrets/offline | Server-side SecretStr configuration, masked recipient and sanitized dry-run summary; no arbitrary destination; dry-run never invokes provider; no credentials used |
| A12 documentation/cleanup | Local setup, source/checksum/config/measurement reports; Terraform, cloud deploy workflow, S3 entrypoint and untested Docker/Compose removed; replacement CI only tests/builds |

GitHub Ubuntu CI passed the backend tests, frontend build, and browser tests for hardening commit `056abf2` ([run 39667723484](https://github.com/vianmangal/emotion-lens/actions/runs/39667723484)). Existing tracked weights and local data were preserved. No cloud resources were inspected or modified.

The ordinary development server was also exercised through a real localhost WebSocket at 10 FPS with 50 generated blank JPEG frames using the actual MediaPipe detector and STGCN configuration. It correctly returned zero people/insufficient evidence with no incidents. Reported frame age: median 19.5 ms, p95 24.55 ms. This tests transport and the real pose pipeline, not two-person webcam accuracy or full temporal-model invocation on real poses.

## Model evaluation: unperformed

No local consenting participant recordings were supplied. The owner clarified that the feature should run live; prerecorded input is optional tooling, never a condition for using Live Safety. Webcam operation is implemented, but unmeasured live accuracy cannot be inferred from engineering tests.

| PRD evaluation requirement | Actual coverage |
| --- | --- |
| 30 held-out staged positive events | 0 evaluated |
| 60 benign clips across hard-negative categories | 0 evaluated |
| 60 minutes continuous benign footage | 0 evaluated |
| Four participants / multiple camera setups | 0 evaluated |
| Precision ≥90%, recall ≥80%, ≤2 false alerts/hour | Unmeasured |
| Median onset delay ≤2 s, p95 ≤4 s | Unmeasured; STGCN has a minimum 3-second observation window |
| Real two-person 10 FPS / frame age target | Unmeasured; blank-frame/synthetic feasibility only |
| 30-minute continuous real camera memory test | Not performed with a physical camera; actual generated-input 30-minute run reported below |
| Compatible license/data rights | Code licenses and Google’s Lite-family model-card license recorded; NTU/STGCN conditions unresolved |
| Real ElevenLabs test | Not performed; mocked adapter tests only |

No held-out thresholds were tuned, no participant/session split was claimed, and no confidence intervals can be calculated without samples. The synthetic STGCN/baseline comparison is recorded in `SAFETY_BENCHMARK.json` and explained in `SAFETY_MODEL_REPORT.md`; it is not a substituted real-world benchmark.

## Reproducible future evaluation

`docs/evaluation-manifest.example.json` intentionally has an empty `clips` list. Populate it with legally usable local videos; each item must specify `path`, `source`, `license`, `participants`, `session`, `angle`, `lighting`, `category`, `split` (`development` or `held_out`), and `onsets` (seconds). Positive actions must be staged, non-contact motions by consenting adults. Include ordinary gestures and the hard negatives named in the PRD, including visibility loss and camera movement. An example item is:

```json
{"path":"clips/session-a.mp4","source":"owner staged recording with consent","license":"private evaluation permission","participants":["p1","p2"],"session":"session-a","angle":"front","lighting":"daylight","category":"noncontact_directed_arm","split":"development","onsets":[3.2]}
```

Replay uses the same `Detector` adapter and `EventPolicy` as live mode. It preserves source timestamps and sampling, resets state between clips, writes no live automatic phone actions, and labels output replay. `scripts/evaluate.py` rejects participant/session overlap between splits, duplicate video content even under renamed paths, invalid onsets, and changes to the frozen model/pipeline/threshold identity. It matches predictions chronologically to the oldest eligible unused labeled onset in `[onset, onset+4s]`, avoiding a nearest-label greedy undercount when windows overlap; extra/duplicate predictions count as false positives and unmatched labels as misses. It reports event counts, precision, recall, continuous-benign false alerts per hour, delay percentiles, processing timings and observation coverage. Set `continuous: true` only on continuous benign recordings; short benign clips are counted separately. Presentation timestamps are preserved where exposed by OpenCV; any nominal-FPS fallback is explicitly reported. Tune only on development data, freeze the model/threshold version, then run held-out once; source/data overlap still requires human review. The script never unlocks calls or automatically marks qualification achieved.

```bash
.venv-model/bin/python scripts/evaluate.py path/to/manifest.json --model stgcn --split development --output data/dev.json
.venv-model/bin/python scripts/evaluate.py path/to/manifest.json --model stgcn --split held_out --development-report data/dev.json --output data/held-out.json
```

Record continuous benign runs separately, inspect false alerts/misses and abstentions, and compare against the frozen baseline. Live manual observation can demonstrate operation but cannot replace labeled timing/denominators needed for accuracy metrics.

## Follow-up engineering audit

The model adapter's initial punch-class index was shifted by one. Upstream's 50th label is zero-based index 49; the corrected adapter accepts punch/slap (49), conditionally kick (50), and rejects push (51). This is a functional correction, not evidence of real-world accuracy.

Live/replay policy settings are now shared and fingerprinted. Replay sampling at 25 FPS now retains the intended 10 analyzed FPS instead of drifting down to ~8.3 FPS. Held-out runs require an explicit development report and reject changed model, artifact, preprocessing, evaluator, or threshold identity.

The final source-fingerprinted v3 generated-input soak completed successfully: 17,988 frames in 1800.090 seconds (9.993 FPS), at most 45 frames / 12,421,125 bytes in the clip ring, and 45,056 bytes of temporary database/storage throughout. The last 2,000 result ages had p95 46 ms. Model and runtime source fingerprints match the hardening implementation. Full samples and identities are in [SAFETY_SOAK.json](SAFETY_SOAK.json).

RSS needs its full context: the raw growth metric compares the run peak against the initial two-minute peak. One later sample at 510.771 seconds reached 285.83 MiB, then fell below 100 MiB at the next sample. The final sample was 87.36 MiB; samples in the last ten minutes ranged from 86.48 to 96.50 MiB. No sustained upward trend was observed. The zero raw growth value does not mean every post-warmup sample was below a single baseline. This was not a physical-camera, person-tracking, incident-encoding or action-accuracy check: generated noise produced no people/events, so temporal action inference and clip encoding were not exercised during this run. Those paths have separate synthetic/model/codec tests, not a continuous human test.

Current v3 processing selects the same directed participant pair for STGCN and the trajectory gate, rather than mixing a bystander pair with another interaction. Visibility loss clears temporal history before recovery. Arming now supplies a fresh monotonic client-clock sample: the first image cannot establish its own apparent freshness. Browser frame age is computed directly from the returned capture timestamp; heartbeat traffic cannot keep stale inference looking active.
