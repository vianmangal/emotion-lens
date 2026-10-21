# EmotionLens Live Safety — Product Requirements and Implementation Contract

Version: 1.0 · 2026-10-21 · Status: ready for local implementation

Repository: `vianmangal/emotion-lens`

Inspected baseline: `05b5bb500d4c4864db775345b226c59b6730d6bb`

## 1. Product decision

Extend EmotionLens with a local webcam monitor that flags **possible striking motions between people**, creates an incident record and optional local video clip, and can initiate an ElevenLabs phone alert to one configured recipient.

This is a personal demonstration project. It will run on the owner's computer and will not be hosted or published as a service. Remove the old AWS deployment machinery. Use React, FastAPI, local model inference, SQLite, and local files. ElevenLabs plus its connected telephony provider are the only proposed runtime cloud services, and are optional.

The system recognizes visible action patterns over time. It does not establish intent, prove an assault, or promise to predict violence before contact. Product wording must say **“Possible striking motion — review footage.”** Facial-expression scores must never determine safety alerts.

### Locked user requirements

- Live webcam input; a screenshot classifier is insufficient.
- A visible attempted hit can trigger an action once enough motion evidence exists.
- Add an optional phone call using the owner's ElevenLabs credentials.
- Local operation, with no AWS infrastructure, cloud database, cloud video storage, or public deployment requirement.
- Keep implementation small enough to understand and demonstrate on one computer.

### Defaults chosen for this handoff

- One operator, one active camera, one configured call recipient.
- Desktop Chrome is the first supported browser; document actual tested versions.
- Python 3.11 is the starting environment; benchmark the actual development machine before selecting a model stack.
- SQLite replaces the mandatory PostgreSQL setup for both existing prediction records and new safety records.
- Real phone calls are disabled by default. Dry-run output is fully functional without credentials.
- Event clips are opt-in; microphone capture is always off.
- Existing image upload and webcam snapshot features remain available when their model is configured.

## 2. Scope and definition of success

### Required MVP

1. Local setup that needs no AWS credentials, PostgreSQL service, Docker, or paid APIs.
2. Webcam preview, camera selection, explicit Start/Stop, and explicit Arm/Disarm.
3. Multi-person detection/tracking and temporal classification of possible striking motion.
4. Observable tracking-quality and model-readiness states; uncertain evidence can produce no decision.
5. One incident per continuing episode, a local warning, optional sound, and review history.
6. Optional local pre-event/post-event clip capture.
7. ElevenLabs outbound-call adapter, mocked tests, dry-run mode, and a user-enabled real mode.
8. Reproducible evaluation with measured false alerts, missed actions, and latency.

### Explicitly outside this implementation

- Face recognition, identifying suspects, emotion-based dangerousness scores, or demographic classification.
- Guaranteed prediction before a hit, emergency dispatch, automatic police calls, or physical access control.
- Fall, weapon, fire, theft, and general “anything bad” detection.
- IP cameras/RTSP, multi-camera deployments, accounts/roles, remote access, SMS, mobile apps, and cloud dashboards.
- A complete retraining platform or an AWS replacement architecture.

These are excluded to keep the current feature testable. Zone monitoring can be a later feature, but must not replace the requested striking-motion detector.

## 3. Existing code and required changes

Paths below are relative to the repository root.

| Existing area | Verified behavior | Required treatment |
| --- | --- | --- |
| `deep_fe/frontend/src/pages/Dashboard.jsx` | Upload and single-frame webcam analysis in one component | Add a separate Live Safety view; avoid embedding the entire feature in this file |
| `deep_fe/frontend/src/components/layouts/sidebar.jsx` | Two tabs; webcam snapshot tab says “Live Webcam” | Rename it to “Webcam Snapshot”; add “Live Safety” and access to incident history |
| `backend/main.py` | Unconditionally loads the expression model in lifespan | Separate feature readiness; missing expression weights must not stop safety mode or health endpoints |
| `backend/models/cnn_model.py` | Imports TensorFlow at module scope | Lazy-load optional expression dependencies so safety-only startup does not require TensorFlow |
| `backend/routers/predict.py` | Saves a record per image to PostgreSQL | Preserve the API contract; use SQLite for local persistence; do not send video frames through this endpoint |
| `backend/database.py`, `backend/config.py` | Async SQLAlchemy with an asyncpg PostgreSQL default | Adopt `sqlite+aiosqlite` with a local data directory and a single backend process |
| `backend/models/db_models.py` | Uses PostgreSQL `UUID` and `JSONB` types | Use portable SQLAlchemy types and verify serialization on SQLite |
| `migrations/versions/0001_initial.py`, `migrations/env.py` | Existing migration chain targets PostgreSQL | Provide a documented fresh SQLite initialization/migration path; do not silently erase any existing local database |
| `backend/entrypoint.sh` | Requires `MODEL_BUCKET` and downloads from S3 | Remove the S3 startup dependency; load explicitly configured local weights |
| `backend/Dockerfile` | Installs AWS CLI and uses the S3 entrypoint | Remove AWS-specific parts; Docker may remain optional if maintained and tested |
| `docker-compose.yml` | Starts PostgreSQL | Remove it or replace with an optional local app setup; normal operation must not require Compose |
| `infra/`, `.github/workflows/deploy.yml`, `DEPLOY.md` | Terraform and AWS deployment instructions/workflow | Remove obsolete deployment files; replace documentation with local operation instructions |

Two approximately 14 MB expression weight files were found locally and appear in `git ls-files`: `models/emotion_cnn_20260530_193721.keras` and `models/emotion_cnn_20260530_193721_best.keras`. They have not been loaded or validated during PRD authoring. They are expression models, not action-recognition models. Preserve them and verify usability only if needed for the legacy feature.

The September shutdown deleted the project's AWS databases, snapshots, buckets, deployed model copy, container repository, load balancer, CloudFront distribution, and secret. ECS was scaled to zero and deployment automation disabled. This is historical context, not a fresh account audit. A stopped EC2 instance and empty/control-plane resources may remain. **Do not provision, restart, or modify AWS while implementing this PRD.** “Delete past AWS stuff” means remove this repository's obsolete AWS code/configuration and runtime dependencies. Any later account cleanup must use a fresh inventory and remain limited to this project.

## 4. User journey and interface

1. Start the local backend and frontend using documented commands.
2. Open Live Safety. See model readiness and the selected camera; the camera is off until Start is clicked.
3. Click Start. Grant browser camera permission. Preview begins in **Disarmed** state.
4. Position both participants so their upper bodies are visible. The UI shows boxes, optional pose landmarks, and tracking quality.
5. Choose whether event clips and local sound are enabled. The UI explains clip retention before enabling it.
6. Select phone mode: **Off**, **Dry run**, or **Real calls**. Real mode requires validated configuration and recipient acknowledgement.
7. Click Arm. The system warms up its temporal window before showing Monitoring.
8. A candidate motion shows “Checking movement…” without calling anyone. Sufficient evidence creates one incident and a visible review alert.
9. If real calls are armed, show a cancellable countdown before initiating one outbound call. Dry run records the intended action without contacting a provider.
10. Review the clip and mark the event “Relevant”, “False alarm”, or “Unclear”. Labels are feedback, not proof of what occurred.
11. Disarm prevents new alerts and cancels pending calls; Stop additionally releases the camera and clears transient video buffers.

Required screen elements: live preview, Start/Stop, Arm/Disarm, sound mute, clip toggle, visible phone mode, masked recipient, model readiness, capture/inference rate, frame age, tracking status, event list, and storage usage. Use the existing dark UI style. Alerts must use text/icons as well as color, and all controls must work by keyboard.

Camera denial, missing weights, unsupported codecs, disconnected backend, full storage, and failed calls must have distinct messages. A frozen preview must never look like active monitoring. Show “No event detected” instead of claiming “Safe”.

## 5. Detection requirements

### D1 — Temporal evidence

Analyze a sliding sequence of frames/poses, not one image. Detect and track multiple people, retaining only session-local track IDs. For an inter-person striking alert, require two sufficiently observed people and evidence of a directed interaction. A lone person shadowboxing can show a diagnostic motion label but must not trigger an inter-person phone alert.

A pose/trajectory rule may be used as a baseline or candidate filter. It must not be presented as a validated violence detector. Prefer evaluating a pretrained temporal action model that already includes relevant interaction classes. MMAction2 provides skeleton-recognition examples and an NTU60 class map containing punching/slapping, pushing, and kicking [S1, S2]. Those classes establish a candidate starting point, not webcam accuracy.

### D2 — Model feasibility gate

Before building the full alert integration:

- Identify exact detector, tracker, pose estimator if used, temporal classifier, and compatible checkpoint.
- Verify code and checkpoint licenses, download source, checksum, input resolution, keypoint ordering, temporal sample rate/window, normalization, and class mapping.
- Record actual hardware, OS, versions, CPU/GPU execution path, throughput, memory, and sample results.
- Compare at least one meaningful temporal model with a simple baseline on staged positive and benign clips.
- Use a lightweight adapter interface so the chosen model can change without rewriting the UI or call logic.
- If no candidate is usable on the machine, continue implementing the local UI, replay/evaluation harness, and dry-run actions; explicitly mark the detection gate unmet. Do not quietly substitute random labels, hardcoded outputs, an emotion model, or a single-frame heuristic and declare completion.

Avoid installing incompatible model frameworks into the existing environment blindly. Use an isolated environment, pin a tested dependency set, and avoid requiring CUDA for basic operation. Apple acceleration is optional and must be tested if advertised.

### D3 — Abstention and false-alert control

- Low-quality pose, missing participants, occlusion, track-ID changes, stale frames, and inadequate temporal history produce an **Insufficient evidence** state.
- A model's highest class score is not necessarily an event; require a supported action class, adequate visibility, and a calibrated acceptance rule.
- Treat scores as model scores, not probabilities that someone is violent.
- Aggregate evidence across time with configurable entry/exit thresholds and durations. Select these on a development set, then freeze them for held-out evaluation.
- Handle track loss without converting an event into “everything is safe”. Reset incompatible history after a camera switch or major tracking discontinuity.
- Do not estimate physical distances or impact force from uncalibrated 2D pixel distances.

### D4 — Event lifecycle

Use explicit states: `disarmed`, `warming_up`, `monitoring`, `candidate`, `alert_active`, `cooldown`, and `unavailable`. Health/visibility reasons are exposed separately.

- `candidate` is a diagnostic state and cannot initiate a phone call.
- Transition to `alert_active` creates a stable event ID exactly once for the episode.
- An ongoing episode updates that event; every frame must not create a new incident.
- End the episode after a configured quiet interval. Default event cooldown: 30 seconds, measured using monotonic time.
- A frame gap over the documented model tolerance invalidates temporal history. Initial default: 1 second; tune in the feasibility report.
- Camera stop, backend failure, and browser disconnect disarm detection and cancel pending automatic calls.
- Browser backgrounding/sleep can throttle capture. If the tab is hidden or fresh frames stop arriving, show monitoring paused/unavailable and cancel pending calls; require explicit re-arming after recovery.
- Simulation/replay mode must be unmistakably labeled and must never auto-call a phone number.

## 6. Local architecture and persistence

```text
Browser camera -> bounded frame transport -> local FastAPI backend
                                          -> person/pose tracking
                                          -> temporal action classifier
                                          -> event policy
                                              |-> UI + optional local sound
                                              |-> SQLite incident/action records
                                              |-> optional local event clips
                                              `-> optional ElevenLabs outbound call
                                                   -> connected telephony provider
                                                   -> configured recipient
```

### Capture and processing

- Browser owns webcam access through `getUserMedia`; microphone is disabled.
- Initial transport target: JPEG frames, maximum 640×480, approximately 10 FPS. Preserve preview smoothness independently of inference.
- Use a session-scoped WebSocket for frames/results. Version the message schema; include `session_id`, increasing `frame_id`, and monotonic capture timestamp.
- Bound messages to 1 MiB, compressed images to 512 KiB, and validate decoded pixel dimensions. Reject malformed/oversized payloads before inference.
- Bound pending work to one newest frame plus the active inference job. Never accumulate an unbounded stale-frame queue. Track dropped frames and preserve real timestamps for temporal sampling.
- Use a bounded time-based history for the model and optional clip buffer. Resample according to the model's actual required cadence; invalidate a window when gaps make it unreliable.
- Run inference outside the async request/event loop. One worker owns ordered tracker/model state for the one active session. Call dispatch and clip encoding must not stall it.
- Results identify the frame/window they describe. Transform coordinates correctly for resize/letterboxing and mirrored previews. Suppress overlays that are too stale.
- The browser stops sending on disarm if continued inference is unnecessary; Stop always stops all media tracks and releases resources.

### Database and files

- SQLite database under `data/`; use SQLAlchemy with `aiosqlite`, bounded writes, and a single app process. No Redis, message broker, RDS, or PostgreSQL required.
- Persist incidents and actions, not every frame. Use a local worker/outbox for phone dispatch, with crash recovery rules in section 8.
- Incident fields: UUID, session ID, capture/creation times, event type, status, model/version, model score and threshold version, observation reasons, temporary track IDs, review label, optional clip reference/status.
- Action fields: UUID, event ID, action type/mode, recipient alias, state, attempt time, provider IDs, error category, and deduplication key. Redact secrets and full phone numbers from logs.
- Settings persist locally except credentials; real-call arming resets to off on process restart.
- Clip files live below a configured data directory. Never accept arbitrary client filesystem paths. Delete through event IDs, constrain resolved paths, and prevent traversal/symlink escapes.
- Retention defaults: clips 24 hours; metadata 7 days; clip quota 500 MiB. Run cleanup at startup and periodically, and apply the quota before admitting new clip writes. Preserve UI alerts if storage is unavailable.
- Keep data, clips, credentials, and downloaded new model artifacts out of Git. Preserve existing tracked model files.

### Clip behavior

- Default off. When enabled, keep a bounded in-memory buffer of up to 5 seconds before the trigger and capture up to 5 seconds after it.
- Encode an independently playable clip from timestamped frames. Do not concatenate arbitrary browser MediaRecorder chunks and assume the result is playable.
- Probe available codecs; document one tested browser-playable format. A codec failure disables recording with an explicit message, not detection.
- If a session ends before the post-event interval completes, finalize a shorter clip and mark it partial.
- Annotate actual sampling/gaps; clips are an aid to review, not forensic proof. No audio and no continuous disk recording.

## 7. Local API outline

Finalize schemas and status codes before UI integration; retain these responsibilities even if endpoint names change.

| Endpoint | Responsibility |
| --- | --- |
| `GET /health` | Process liveness plus separate feature readiness; missing expression weights do not crash the app |
| `GET /safety/status` | Detector readiness, mode, capabilities, recording/phone availability |
| `POST /safety/sessions` | Create the one active local session and a short-lived session capability |
| `WS /safety/sessions/{id}/stream` | Bounded frames, readiness, tracking results, event notifications, heartbeat |
| `POST /safety/sessions/{id}/arm` | Arm validated settings; real calls require explicit opt-in |
| `POST /safety/sessions/{id}/disarm` | Cancel pending actions and stop new event creation |
| `DELETE /safety/sessions/{id}` | End session, clear buffers, finalize partial clips |
| `GET /safety/events` | Paginated local history |
| `PATCH /safety/events/{id}` | Review/acknowledgement label |
| `GET /safety/events/{id}/clip` | Serve a retained clip by ID |
| `DELETE /safety/events/{id}` | Remove the local event and associated clip; preserve only minimal call-dedup metadata until its expiry |
| `POST /safety/events/{id}/actions/cancel` | Cancel a queued/countdown call; describe limits if already submitted |
| `POST /safety/phone/test` | Explicit user-triggered test to the configured allowlisted recipient; dry-run by default |

Bind to `127.0.0.1`, not all interfaces. Restrict HTTP Host/Origin and WebSocket Origin to configured local frontend origins; do not rely on CORS alone for write protection. Protect state-changing/call endpoints with a local capability token delivered only through the approved local UI. Do not allow arbitrary origins to obtain it. A session capability is checked when opening the WebSocket and is never logged. No user account system is needed for this single-user local scope.

## 8. ElevenLabs phone alerts

### Feasibility and dependency

**Possible:** ElevenLabs exposes `POST https://api.elevenlabs.io/v1/convai/twilio/outbound-call` with `agent_id`, `agent_phone_number_id`, and `to_number` [S3]. Native integration connects an outbound-capable Twilio number or verified caller ID to ElevenLabs [S4]. An ElevenLabs API key alone does not supply a phone line.

Use the native integration as the initial implementation. The local backend initiates an outbound HTTPS request; ElevenLabs/provider infrastructure handles the call. The app does not need a public URL merely to submit this request. This design intentionally avoids the separate custom TwiML/webhook integration, which would introduce an inbound public endpoint.

Real calls need internet and can incur ElevenLabs and telephony charges. Verify destination support and account restrictions during setup; do not promise every country/number works. No subscription, number purchase, or real call is authorized merely by implementing this document. Implement the adapter and mocks first; an operator's explicit Send Test Call / Enable Real Calls action is the runtime authorization.

### Server-only configuration

Document placeholders, never real credentials:

```dotenv
SAFETY_CALL_MODE=off
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
ELEVENLABS_AGENT_PHONE_NUMBER_ID=
SAFETY_ALERT_TO_NUMBER=
SAFETY_CALL_GRACE_SECONDS=10
SAFETY_CALL_COOLDOWN_SECONDS=300
SAFETY_CALL_MAX_PER_HOUR=3
```

The single recipient must be an operator-configured E.164 number belonging to the owner or a consenting contact. The event/call API must not accept an arbitrary destination. Never put provider credentials in `VITE_*`, source control, screenshots, browser storage, or logs. The backend only needs the ElevenLabs credentials/IDs for this native path; do not require duplicating Twilio credentials locally after provider setup.

### Action policy

- Phone modes: `off`, `dry_run`, `real`. Default off; dry run records intended payload and state without any provider request.
- Live auto-calling requires a qualified detector, a fresh visible event, explicit session arming, configured recipient, and no active call/cooldown/quota block.
- Start a 10-second cancellable countdown after an event is confirmed. Provide Disarm and Cancel now. “Confirmed” refers to passing the software policy, not proof of violence.
- Recheck arming, session health, event cancellation, cooldown, and quota immediately before dispatch.
- At most one automatic call attempt per event, one in flight, a five-minute global recipient cooldown, and at most three attempts per rolling hour. Persist limits across restarts and event deletion; explicit tests also consume quota.
- Save the dispatch claim atomically before making the network request. Use a unique event/action key to prevent duplicate workers or messages from calling twice.
- The provider endpoint does not establish an exactly-once guarantee. A timeout or crash after submission may leave delivery unknown. Mark `delivery_unknown`; do not automatically retry or replay that attempt after restart. Reconcile using documented provider data when available, otherwise ask for human review in the UI.
- No delayed catch-up calls when internet returns, the app restarts, or a recording is replayed. Pending countdowns expire on disconnect/restart. Test mode and model simulations never become real alerts automatically.
- Manual “Send Test Call” is allowed before detector qualification, but only as an explicitly labeled test with the same recipient and quotas.
- A successful submission is not proof the recipient answered. Show `submitted`, `failed`, or `delivery_unknown` based on actual responses. Only show answered/completed if verified through a supported provider status API. Polling is optional; public callbacks are unnecessary for MVP.
- Once submitted, cancellation cannot be guaranteed; the UI must say so. Keep calls short and configure the agent's maximum duration, ending behavior, and tools during setup.
- Camera failures, poor tracking, and storage problems produce local status warnings, not physical-aggression calls.

Suggested agent message, populated with trusted local event metadata only:

> This is an automated alert from your local EmotionLens demo. Possible striking motion was flagged by the webcam at [time]. This may be a false alarm. Please check the local application.

Do not tell the recipient an assault is proven or that anyone is injured. Send a short event summary/time to ElevenLabs, not camera footage, face images, or biometric embeddings. Set `call_recording_enabled=false`; review ElevenLabs agent transcript/audio retention separately because disabling Twilio recording alone does not establish zero provider retention. Show that calls use an external service and may cost money when real mode is enabled.

## 9. Proposed code organization

Names are guidance; preserve separation of responsibilities.

```text
backend/safety/
  schemas.py, sessions.py, frame_buffer.py
  detector.py, tracking.py, temporal_model.py, event_policy.py
  recording.py, retention.py
  actions/base.py, actions/dry_run.py, actions/elevenlabs.py, actions/dispatcher.py
backend/routers/safety.py
backend/tests/safety/
deep_fe/frontend/src/pages/LiveSafety.jsx
deep_fe/frontend/src/components/safety/
deep_fe/frontend/src/hooks/useSafetySession.js
deep_fe/frontend/src/api/safety.js
docs/LOCAL_SETUP.md
docs/SAFETY_MODEL_REPORT.md
docs/SAFETY_EVALUATION.md
scripts/                 # documented local setup/model/evaluation helpers
data/                    # ignored database, clips, local settings
```

Use a small provider adapter for calls; no general automation platform. Keep model downloads explicit and checksum-verified; no surprise downloads on every startup. Once dependencies/weights are installed, detection, review, and dry-run actions work without internet.

## 10. Removing legacy AWS dependencies

Perform this as an implementation phase, with an inventory and a Git diff:

1. Remove the obsolete tracked `infra/` Terraform files, including the provider lockfile and secrets configuration. Do not expose values from ignored state, local environment files, or credentials while auditing.
2. Remove `.github/workflows/deploy.yml` and its AWS OIDC permissions, ECR pushes, ECS updates, S3 syncs, and CloudFront invalidations. An optional replacement CI workflow may only lint/test/build; no deployment, provider calls, or real phone calls.
3. Replace `DEPLOY.md` with local setup/operation documentation, and update README architecture/setup claims. The existing project is no longer an AWS deployment.
4. Remove `MODEL_BUCKET`, S3 model fetches, AWS CLI installation, and mandatory cloud startup behavior from scripts/container configuration.
5. Make SQLite the default and eliminate mandatory `asyncpg`/PostgreSQL/Compose dependencies. Use portable schema types and test real SQLite persistence. Preserve existing local data; document an export/migration path if any is found.
6. Remove misleading hosted-domain labels from the UI. Keep GitHub source links where useful.
7. Retain only optional local Docker files if they provide a tested benefit; otherwise remove them. Do not add infrastructure to compensate for deleted infrastructure.
8. Audit tracked runtime code and docs for remaining AWS requirements. Historical text explaining removal may remain; runnable AWS provisioning/deployment paths must not.

The previous cloud shutdown is already complete as recorded in this conversation. Do not run Terraform destroy against an unknown state, reinstall cloud resources, change unrelated AWS resources, or delete the user's local model/data files during code cleanup.

## 11. Evaluation and acceptance criteria

### Engineering acceptance — required

| ID | Acceptance check |
| --- | --- |
| A1 | Fresh documented local setup starts with SQLite and no AWS/PostgreSQL credentials; original upload tests pass with local persistence |
| A2 | Missing expression weights do not prevent safety startup; missing safety weights produce unavailable status and no safety calls |
| A3 | Start/Stop and tab changes clean up camera tracks, WebSocket, buffers, sound, and timers; camera denial is recoverable |
| A4 | Disarmed, low-visibility, stale-frame, lone-person, replay, and simulation states cannot initiate automatic real calls |
| A5 | One continuous positive sequence produces one incident; normal activity after the cooldown can lead to a distinct subsequent incident |
| A6 | HTTP/WebSocket payload limits, malformed images, Origin/Host checks, session capability, and path traversal protections are tested |
| A7 | Slow inference drops queued stale work without unbounded memory growth; dropped frames invalidate unreliable temporal windows |
| A8 | Opt-in clips play in the supported browser, contain available pre/post context, obey quota/retention, and delete with the event |
| A9 | Event history and review labels survive restart; startup never re-arms real calls or replays pending calls |
| A10 | Mocked ElevenLabs tests cover success, explicit failure, timeout/unknown delivery, duplicate dispatch, cancel, cooldown, quota, and restart recovery |
| A11 | Real credentials never enter frontend bundles/logs; missing credentials leave dry run usable; tests never dial real numbers |
| A12 | README/local setup, model provenance, limitations, and evaluation report match the final implementation; no deploy workflow remains |

### Model evaluation — separate from engineering tests

Create a manifest of legally usable evaluation clips with source/license, subject/session grouping, camera angle, lighting, class labels, and event onset times. Use consenting adults for any new staged recordings and perform non-contact motions only. Do not require genuine violence or collisions.

Include positive staged strikes directed toward a second visible participant and hard negatives: waving, high-fives, hugs, handshakes, pointing, reaching, stretching, dancing, shadowboxing, people passing, occlusion, and camera movement. Record whether a second person or relevant limbs are off-screen.

Split development and held-out evaluation by participant/session where possible; never split adjacent frames from one recording across sets. Record unavoidable dataset overlap or pretrained-data overlap uncertainty. Tune thresholds on development data only. Synthetic keypoints validate software policy, not real-world model accuracy.

Initial demonstration targets (requirements to measure, **not achieved claims**):

- At least 30 held-out staged positive events, 60 benign short clips across the negative categories, and 60 minutes of continuous benign footage. Seek at least four participants and multiple camera setups; document shortfalls.
- Event-level precision at least 90%, recall at least 80%, and at most two false incident alerts per hour of benign continuous video.
- Match predicted and labeled events one-to-one using a documented temporal matching rule; duplicate alerts count as false positives.
- For detected held-out events, median onset-to-alert delay at most 2 seconds and p95 at most 4 seconds. Report model-window delay and capture/processing/transport delay separately. Do not claim a warning precedes contact unless that timing was measured.
- Webcam inference target approximately 10 analyzed FPS at 640×480 with p95 capture-to-result age under 500 ms, excluding the evidence window. If not feasible, document the operating point and its effect on detection before claiming success.
- A 30-minute continuous session has bounded buffers and no unbounded memory/storage growth.

Report counts, confusion examples, visibility coverage/abstention, and uncertainty intervals where feasible. Small staged tests do not establish deployment-grade safety performance. If targets are unmet, label the detector experimental, leave automatic real calls unavailable, and report the gap; explicit test calls and dry runs remain usable. Never change thresholds on the held-out set just to pass.

## 12. Implementation sequence and completion gates

### Phase 1 — Local foundation and AWS cleanup

Inventory current code; preserve unrelated changes and existing model/data files. Remove cloud dependencies, adopt SQLite, separate expression/safety readiness, and document local startup. Gate: local app and legacy tests work without AWS or PostgreSQL.

### Phase 2 — Model feasibility and replay harness

Evaluate candidate action stacks on the actual machine; document artifacts, licenses, preprocessing, performance, and false positives. Implement deterministic replay of timestamped clips through the real pipeline. Gate: a defensible model decision and explicit limitations. An unmet model gate must remain visible while independent engineering work continues.

### Phase 3 — Live capture and event policy

Implement one camera session, bounded transport/processing, tracking overlays, temporal policy, readiness states, and start/stop/arm/disarm. Gate: real video and replay use the same detection/policy path; policy tests pass without paid services.

### Phase 4 — Incidents, clips, and local actions

Add SQLite events, optional sound, pre/post clips, review labels, cancellation, retention, and storage failures. Gate: one complete local incident can be created, reviewed, and deleted.

### Phase 5 — ElevenLabs adapter

Implement configuration validation, dry runs, server-only integration, dispatch deduplication, budgets, and unknown-delivery handling. Gate: mocked call tests and setup docs pass. A real test call is a separate explicitly authorized runtime action to the configured recipient; absence of credentials must not block local feature completion.

### Phase 6 — Evaluation and handoff

Run engineering checks and held-out model evaluation. Produce a report distinguishing completed engineering, detector qualification, and any unperformed live-provider test. Record exact local commands and tested environment. Mark the overall detector feature unfinished if its required model/evaluation gate remains unmet; do not present UI scaffolding as working action detection.

## 13. Deliverables

- Local working app with Live Safety, incident review, dry-run phone actions, and optional real-call adapter.
- Removal of legacy AWS deployment code and replacement local documentation.
- Tested SQLite setup/migrations and preservation of existing user data.
- Tests for detection policy, lifecycle/resource cleanup, recording, persistence, and action dispatch.
- `docs/SAFETY_MODEL_REPORT.md` with model artifacts, licensing, setup, hardware, and baseline comparison.
- `docs/SAFETY_EVALUATION.md` with actual results, false positives, limitations, and qualification decision.
- A short non-contact demo script: ordinary gesture -> no event; staged directed strike -> possible-motion event -> clip -> dry-run call; disarm/cancel -> no call.
- No hosting, cloud resources, purchased phone numbers, or unsolicited real calls as part of implementation.

## 14. Sources and verification boundary

These sources were checked while preparing this PRD. Recheck APIs/package compatibility at implementation time; do not assume example checkpoints satisfy the evaluation targets.

- **S1:** [MMAction2 skeleton action labels](https://github.com/open-mmlab/mmaction2/blob/main/tools/data/skeleton/label_map_ntu60.txt).
- **S2:** [MMAction2 demo documentation and model examples](https://github.com/open-mmlab/mmaction2/blob/main/demo/README.md).
- **S3:** [ElevenLabs native outbound-call API](https://elevenlabs.io/docs/eleven-agents/api-reference/twilio/outbound-call).
- **S4:** [ElevenLabs native Twilio integration and prerequisites](https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/native-integration/).

Authoring verified source structure and local weight-file presence. It did not validate model accuracy, inspect ElevenLabs credentials/accounts, place calls, or re-audit the AWS account.
