# Actual verification and remaining qualification

2026-10-21. **Live experimental implementation is available. Detector qualification and the overall qualified detector feature remain unfinished.** Automatic real calls are unavailable. No real provider request or physical webcam recording was made during automated verification.

## Engineering results

Commands run from the repository root:

```bash
.venv-safety/bin/python -m pytest -q
npm run build --prefix deep_fe/frontend
npm run test:e2e --prefix deep_fe/frontend
```

39 backend tests pass. Five Playwright browser tests pass. The frontend production build succeeds. Tests use actual temporary SQLite databases, generated benign image/video fixtures, synthetic evidence, mocked provider transport, and Chromium's fake camera. No test dials a phone number. The preexisting HEIC test now uses a generated 64×64 white decoder fixture, avoiding a native HEIF-encoder crash observed when encoding after VP8 initialization on this machine. Production HEIC decoding and the upload contract still pass.

| Acceptance area | Evidence and limits |
| --- | --- |
| A1 local foundation | Default SQLite, real `/predict` persistence/JSON/UUID round trip, old upload/HEIC/rejection tests; fresh and repeated Alembic upgrade succeeds; no external database used |
| A2 separate readiness | No TensorFlow import on startup; missing pose configuration reports unavailable without crashing API; missing expression weights do not block safety |
| A3 resource lifecycle | Fake-camera browser tests check explicit start/arm, Stop/view cleanup, track termination, permission denial/retry, hidden-tab disarm and disconnect cleanup |
| A4 call gates | Unqualified automatic-real mode rejects arm; uncertainty/lone/undirected/gaps abstain; replay cannot enqueue automatic calls; real manual test needs explicit acknowledgement/configuration |
| A5 episodes | Policy positive/quiet/cooldown sequences and live transport integration create one persistent incident per continuous synthetic episode |
| A6 local boundary | Host/Origin rejection, capability checks, missing/wrong WebSocket auth, HTTP/message/JPEG dimension/byte limits, malformed images, nonfinite/backwards timestamps, path traversal and symlink rejection |
| A7 bounded work | Slow inference test replaces queued frames and counts drops; one active + one pending job; bounded history/clip rings; 18,000 synthetic time steps exercise 30-minute buffer bounds |
| A8 clips | Actual VP8/WebM encode/decode; Chromium playback; partial clip finalized on disarm; source gap/pre/post metadata; quota, retention and deletion tests. Physical webcam clips untested |
| A9 restart | Review labels/JSON survive another app instance; pending countdowns cancelled and submitting actions marked unknown; no automatic rearming/replay |
| A10 adapter | Mocked success, explicit rejection, invalid response, timeout/unknown, same-action duplicate claim, cancellation, one in flight, cooldown, rolling quota and restart recovery |
| A11 secrets/offline | Server-side SecretStr configuration, masked recipient and sanitized dry-run summary; no arbitrary destination; dry-run never invokes provider; no credentials used |
| A12 documentation/cleanup | Local setup, source/checksum/config/measurement reports; Terraform, cloud deploy workflow, S3 entrypoint and untested Docker/Compose removed; replacement CI only tests/builds |

GitHub Ubuntu CI also passed the backend tests, frontend build, and browser tests for implementation commit `029204b`. Existing tracked weights and local data were preserved. No cloud resources were inspected or modified.

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
| 30-minute continuous real camera memory test | Not performed; bounded data structures and synthetic-time buffer test only |
| Compatible license/data rights | Source code licenses verified; complete artifact/data conditions unresolved |
| Real ElevenLabs test | Not performed; mocked adapter tests only |

No held-out thresholds were tuned, no participant/session split was claimed, and no confidence intervals can be calculated without samples. The synthetic STGCN/baseline comparison is recorded in `SAFETY_BENCHMARK.json` and explained in `SAFETY_MODEL_REPORT.md`; it is not a substituted real-world benchmark.

## Reproducible future evaluation

`docs/evaluation-manifest.example.json` intentionally has an empty `clips` list. Populate it with legally usable local videos; each item must specify `path`, `source`, `license`, `participants`, `session`, `angle`, `lighting`, `category`, `split` (`development` or `held_out`), and `onsets` (seconds). Positive actions must be staged, non-contact motions by consenting adults. Include ordinary gestures and the hard negatives named in the PRD, including visibility loss and camera movement. An example item is:

```json
{"path":"clips/session-a.mp4","source":"owner staged recording with consent","license":"private evaluation permission","participants":["p1","p2"],"session":"session-a","angle":"front","lighting":"daylight","category":"noncontact_directed_arm","split":"development","onsets":[3.2]}
```

Replay uses the same `Detector` adapter and `EventPolicy` as live mode. It preserves source timestamps and sampling, resets state between clips, writes no live automatic phone actions, and labels output replay. `scripts/evaluate.py` rejects participant/session overlap between splits. It matches each predicted onset to at most one labeled onset in `[onset, onset+4s]`; extra/duplicate predictions count as false positives and unmatched labels as misses. It reports event counts, precision, recall, benign false alerts per hour, delay percentiles, processing timings and observation coverage. Tune only on development data, freeze the model/threshold version, then run held-out once; source/data overlap still requires human review. The script never unlocks calls or automatically marks qualification achieved.

```bash
.venv-model/bin/python scripts/evaluate.py path/to/manifest.json --model stgcn --split development --output data/dev.json
.venv-model/bin/python scripts/evaluate.py path/to/manifest.json --model stgcn --split held_out --output data/held-out.json
```

Record continuous benign runs separately, inspect false alerts/misses and abstentions, and compare against the frozen baseline. Live manual observation can demonstrate operation but cannot replace labeled timing/denominators needed for accuracy metrics.
