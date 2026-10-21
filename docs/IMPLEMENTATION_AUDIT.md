# Live Safety completion audit

Updated 2026-10-22 against `PRD-LIVE-SAFETY.md` v1.0. This audit preserves the PRD scope. **The overall qualified detector feature is not complete.** Implemented engineering and passing synthetic/mocked tests do not establish webcam action accuracy.

## Required MVP and user journey

| Requirement | Current evidence | Result |
| --- | --- | --- |
| MVP 1: local setup without cloud/database/paid credentials | SQLite default; lazy expression model; local run helper; real SQLite upload test; removed deployment files; Ubuntu CI for the initial implementation | Implemented; updated CI run tracked separately |
| MVP 2 / journey 1–3: camera selection, preview, explicit Start/Stop and Arm/Disarm | Dedicated LiveSafety view and useSafetySession hook; Chromium fake-device lifecycle and permission-recovery tests | Implemented; physical device selection/permission remains unverified |
| MVP 3 / journey 4: multiple people and temporal striking classification | Actual MediaPipe pose model and STGCN checkpoint load/run; trajectory history; same-pair selection; upstream class-map regressions | Implemented experimentally; human striking recognition is unverified |
| MVP 4 / journey 7–8: readiness, tracking quality, warm-up, candidate and abstention | Separate status fields; visibility-reset and stale-first-frame tests; candidate cannot enqueue; frozen capture watchdog and heartbeats | Engineering verified for tested cases; real visibility coverage unmeasured |
| MVP 5 / journey 8,10: one incident per episode, local warning/sound, history/review | Policy sequences, live transport synthetic evidence, SQLite restart/review tests; sound context cleanup tests | Implemented; full non-contact human demonstration unperformed |
| MVP 6 / journey 5,10–11: optional pre/post clips and resource cleanup | Bounded JPEG ring, VP8 encode/decode and Chromium playback, partial finalization, retention/quota, deletion/encoder race tests | Implemented; physical webcam clips unverified |
| MVP 7 / journey 6,9,11: optional calls, visible mode, countdown and cancellation | Dry-run summaries, masked recipient, mocked ElevenLabs transport, durable claims/quotas/recovery, cancel controls | Dry run and explicit manual real-test adapter implemented; automatic real mode intentionally unavailable while qualification is unmet |
| MVP 8: measured false alerts, misses and latency | Replay/evaluator, validated manifest, frozen development identity, one-to-one matching and timing reports | Harness implemented; human evaluation not performed |

All requested screen controls are present. Text/icons accompany alerts, and controls use native buttons, selects and labels with focus styling. Fake-camera tests cover selected keyboard-compatible browser controls, but a complete manual keyboard/accessibility audit has not been performed. Capture and inference FPS count actual sent/results; the UI computes frame age on the browser clock and suppresses stale overlays.

## Detection gates

| Contract | Proof or missing evidence | Result |
| --- | --- | --- |
| D1 sequence input, session-local tracking, two observed people, directed interaction, no expression dependency | detector.py, temporal_model.py, tracking.py; temporal/lone-person/occlusion and same-pair tests; no expression imports in safety inference | Implemented; real-world decision quality unverified |
| D2 exact stack, checkpoint/source/checksum/input shape/order/preprocessing/class map | Model report, artifact manifest, source/dependency pins, actual tensor inspection and model execution | Recorded and partially verified; complete weight/data rights unresolved |
| D2 actual machine feasibility and pretrained model vs baseline on staged positive/benign clips | M4 CPU generated-frame and synthetic-skeleton benchmark | Synthetic feasibility only; staged human comparison missing |
| D2 interchangeable adapters, isolated pinned environment, explicit downloads/no CUDA requirement | Detector adapters, setup_temporal.py, download_models.py, requirements and dependency snapshots | Implemented and exercised locally |
| D3 abstain on visibility loss, ID changes, stale frames, gaps and inadequate history | Policy/model/transport tests; old decoded/queued work cannot enter a replacement session | Implemented for tested cases |
| D3 calibrated acceptance and development/held-out freeze | Configurable finite ordered thresholds; stored fingerprint; evaluator rejects model/pipeline/threshold changes | Freeze machinery implemented; calibration and held-out measurements absent |
| D4 explicit lifecycle, stable episode ID, quiet end, 30-second cooldown | EventPolicy sequences and persisted episode integration test | Implemented for synthetic evidence |
| D4 Stop/disconnect/hidden/sleep recovery and replay exclusion | Session-scoped control/arming generations, heartbeat/watchdog tests, explicit rearm; replay cannot enqueue automatic calls | Tested with fake camera and controlled transport; physical sleep/camera recovery unverified |

## Capture, persistence, clips and API

Frame transport has a version, session ID, increasing frame ID and capture timestamp; arming additionally requires a fresh client-clock sample. The server validates Host/Origin/capabilities, message/JPEG/pixel limits and malformed timestamps/images before inference. One ordered inference worker and a newest-only pending queue bound work; dropped frames invalidate history. Results carry frame/arming identities. Encoder/provider work runs separately from inference.

Prediction UUID/JSON records and new incident/action records use SQLite. Metadata stores episode/model/threshold/track/review/clip fields. Action claims/dedup/quota persist across restart and event deletion. Credentials remain server-only; only sound/clip preferences persist in browser storage. Startup adds missing tables, never drops data; fresh/repeated Alembic initialization has been exercised. Migration from an old external PostgreSQL database is documented as a separate export/import, not silently performed.

Clip names are generated from event IDs below the configured local directory. Traversal and symlink escapes are rejected. Default retention is 24 hours for clips, 7 days for metadata, with a 500 MiB clip quota; cleanup runs at startup and periodically. Available pre/post duration and source gaps are recorded. Deletion serializes with active encoding and prevents queued encoding from recreating a deleted file. Unsupported codecs and storage failures have explicit statuses. Database initialization/read/write failures retain health/local warning capability and pause phone dispatch until restart; tested failures never erase existing files.

Every endpoint responsibility in PRD section 7 is implemented, including status/bootstrap, create/arm/disarm/end, authenticated WebSocket with heartbeat, paginated events, review, clip serving, deletion, cancellation and explicit phone tests. Additional action-list/cancel endpoints support the UI. The default app binds loopback and uses one backend process. A full adversarial security audit, physical camera test and real-provider integration test are not claimed.

## Phone action invariants

Tests cover dry run without credentials/provider I/O, explicit success/failure, timeout/invalid response as unknown, same-action duplicate dispatch, one in flight, cancellation, grace expiry, cooldown, rolling-hour quota, and restart recovery. Claim commit precedes provider I/O; unknown delivery is never retried automatically. URLs do not carry capability tokens, real credentials/numbers do not enter the frontend, and the request accepts no arbitrary destination. Calls send trusted text metadata only, set Twilio recording false, and do not imply the recipient answered. Native provider setup/retention caveats are documented. No actual phone call was made.

Uncertain camera evidence cancels only automatic actions for that session; it cannot cancel a separately requested manual test. Explicit Disarm/Stop still cancels pending countdowns. Persistence failure disables dispatch until restart, preventing storage recovery from replaying delayed attempts.

## Evaluation, commands and deliverables

- README, LOCAL_SETUP, SAFETY_MODEL_REPORT, SAFETY_EVALUATION, artifact/dependency manifests, benchmark output, and the original PRD/handoff are present. No obsolete deployment workflow or runtime cloud provisioning path remains.
- Local `python -m pytest`, frontend build and Playwright suite pass as recorded in SAFETY_EVALUATION. Existing CI passed on the initial implementation; later commits require their own hosted result.
- Model downloader and isolated setup were exercised. Replay sampling/timestamps, manifest leakage/duplication checks, matching, and frozen-development checks have deterministic tests. Replay/evaluation on a real labeled corpus remains unperformed; empty manifests correctly refuse to produce accuracy metrics.
- A non-contact demo procedure is documented. Its ordinary-gesture → directed motion → incident → clip → dry-run sequence has only synthetic policy/integration evidence, not a completed human demonstration.
- An initial v2 generated-input 30-minute soak completed. The final source-fingerprinted v3 soak is tracked separately; a smoke run is not a 30-minute pass. Generated inputs cannot prove physical-camera performance or human accuracy.
- Thirty held-out positives, sixty benign clips across the specified categories, sixty continuous benign minutes, four participants/multiple setups, accuracy/false-alert targets, onset delay and uncertainty estimates remain unmeasured. No threshold was tuned against a held-out set.
- Model/data licensing conditions remain incomplete. No registration agreement was accepted, restricted dataset downloaded, account contacted, cloud resource modified or number purchased.

## Completion decision

Phases 1, 3–5 have substantial implementation and automated engineering evidence with the limits above. Phase 2's staged-data/licensing gate and Phase 6's held-out/physical-camera evaluation are unmet. The live application can be used experimentally without prerecorded input; that does not establish qualification. Keep the PR a draft, keep automatic real calls unavailable, and keep the overall goal unfinished until those requirements have authoritative evidence.
