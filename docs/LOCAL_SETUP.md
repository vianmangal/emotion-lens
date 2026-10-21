# Local setup and operation

Test environment, 2026-10-21: Apple M4, 16 GiB RAM, macOS 27.0.1 arm64, Python 3.11.15, Node 24.19.0. Browser verification uses Chromium 156.0.8078.4 (Playwright 1.64.1). Physical webcam quality/accuracy has not been evaluated.

## Installation

Run commands from the repository root. Keep the existing `.venv` and local data/model files intact; the safety stack has a separate environment.

```bash
python3.11 -m venv .venv-safety
source .venv-safety/bin/activate
pip install -r backend/requirements-safety.txt
python scripts/download_models.py
python scripts/run_local.py
```

The explicit downloader writes below `data/models/`, checks exact sizes and SHA256, and prints nonsecret model configuration. Startup never downloads anything. Without configured artifacts the API/preview/history/dry-run tests remain usable and monitoring reports unavailable.

For the pretrained CPU temporal model, stop the first backend and run:

```bash
.venv-safety/bin/python scripts/setup_temporal.py
.venv-model/bin/python scripts/run_local.py --model stgcn
```

This creates `.venv-model`, installs the tested dependency pins, checks out the exact MMAction2 revision under ignored `data/vendor/`, and downloads the optional checkpoint. It avoids CUDA, the incomplete PyPI MMAction2 wheel, and the generic decord dependency without macOS ARM wheels. Do not install that generic model stack into the existing expression environment. The tested source version and artifacts are in the model report.

Frontend, second terminal:

```bash
cd deep_fe/frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173 in Chrome/Chromium. The Vite proxy includes WebSockets. An optional `VITE_API_URL=http://127.0.0.1:8000` points directly at the same API. Never put phone credentials in any `VITE_*` setting. Approved origins are localhost/127.0.0.1 on port 5173; custom origins must be explicitly configured in backend settings. API and UI bind to loopback. Use one backend worker. Do not expose the local API through a tunnel.

Plain `uvicorn backend.main:app --host 127.0.0.1 --port 8000 --ws-max-size 1048576 --ws-max-queue 1` also works, but model paths/checksums then need configuration in a root `.env` (see `.env.example`). The run helper configures downloaded local models automatically.

## Live use

1. Select Live Safety, choose a camera and click **Start camera**. Video, person tracking and motion detection start together; microphone permission is never requested.
2. Keep both participants' upper bodies and arms visible. Labeled boxes and skeletons identify session-local tracks. Fewer than two visible people, uncertain limbs or insufficient history cannot establish a striking interaction.
3. Watch for **Possible hit detected** in the live status. Camera selection, Start and Stop are the main controls. **Resume detection** appears only after a pause; returning to a visible tab does not silently resume analysis.
4. Stop releases the camera and connection. Switching to another application view also releases them. Camera switching requires Stop, select another device, then Start.

The simplified live view has no incident history, clips, sound/phone settings or separate arming step. It requests `live_only: true`: incident writes, recording and phone actions are disabled for that session, and the incident-notification cooldown is removed. Existing local data and the older backend APIs are preserved. A session still expires after one hour by default; Stop/Start renews it.

See [DEMO.md](DEMO.md) for the two-person walkthrough. Detection is experimental and human accuracy remains unmeasured.

## Optional expression feature

```bash
.venv-safety/bin/python -m pip install -r backend/requirements-expression.txt
```

Set `MODEL_PATH=models/emotion_cnn_20260530_193721_best.keras` in a root `.env`. Existing tracked expression weights are preserved. `/predict` retains its multipart `image` and response contract; `/health` reports expression configuration separately. TensorFlow is lazy and optional, so missing expression dependencies/weights cannot prevent safety startup. The physical weight files were not validated during this implementation; legacy preprocessing/API behavior is tested with an inference mock.

## ElevenLabs adapter (backend only, deferred from the live view)

Dry runs need no credentials or internet. A real test needs an ElevenLabs agent, a native connected outbound-capable Twilio phone number/verified caller ID, and a consenting recipient. An API key alone is not a phone line. Follow [native integration prerequisites](https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/native-integration/).

Put placeholders like these in the root `.env`, never in frontend files:

```dotenv
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
ELEVENLABS_AGENT_PHONE_NUMBER_ID=
SAFETY_ALERT_TO_NUMBER=
SAFETY_CALL_GRACE_SECONDS=10
SAFETY_CALL_COOLDOWN_SECONDS=300
SAFETY_CALL_MAX_PER_HOUR=3
```

The destination is E.164 (`+` followed by country code and number). Only the configured destination can be called. The UI reveals its last four digits. Configure the agent to speak its trusted `emotionlens_message` dynamic variable, keep calls short, end after the message, and disable unnecessary tools; configure maximum duration in ElevenLabs. The adapter uses [the native outbound-call endpoint](https://elevenlabs.io/docs/api-reference/integrations/twilio/outbound-call), sets `call_recording_enabled=false`, and sends a brief trusted message with no images, video, or embeddings. Review agent transcript/audio retention separately; that flag controls Twilio recording, not all provider retention.

The current Live Safety screen exposes no phone tests or real-call controls. Live-only sessions reject phone modes and clips. The server adapter and its tests remain for a later phase; no real call is part of installation/tests, and automatic real mode remains locked while qualification is unmet.

A submitted request does not establish that anyone answered. `failed` means explicit rejection; timeout/ambiguous provider responses become `delivery_unknown` without retry. At most one submission is in flight, with 5-minute recipient cooldown and 3 real attempts per rolling hour, including real tests. Deleting an event preserves minimal call accounting/dedup for at least that horizon. Restart cancels countdowns and marks interrupted submissions unknown. Submitted calls cannot be recalled by this app.

## SQLite and preservation

Default database: `data/emotion-lens.db`. New tables initialize automatically without dropping existing data. Optional versioned schema tracking:

```bash
.venv-safety/bin/alembic upgrade head
```

The SQLite branch of `0001_initial` creates portable prediction records; `0002_safety` adds incidents/actions. Both tolerate an already initialized local schema. Repeated upgrades and round-trip JSON/UUID storage have been tested. Do not run downgrade as a data-preserving operation.

Before changing an existing SQLite installation, stop the app and back up the database using Python's `sqlite3.Connection.backup` API (or SQLite CLI `.backup`), plus the clips directory. WAL files may exist while the API is running. Startup never resets the database. A legacy PostgreSQL database is not automatically converted: preserve an export first, restore it separately with its legacy tooling, then map prediction IDs, filenames, scores JSON, and timestamps into a new SQLite copy and verify row counts. This implementation never connects to an old cloud database and never deletes an existing database/model.

Clips are served only by incident ID with a capability. Arbitrary paths and symlink escapes are rejected. Cleanup runs on startup and every minute; an interrupted encoder's orphan files are removed after a ten-minute grace period. Storage/codec/quota failures are exposed separately from detection.

## Troubleshooting

- Permission denied: allow camera access for the localhost origin, then Start again.
- Camera busy/disconnected: close other camera users, reconnect, Stop and Start.
- Missing weights/dependencies/checksum mismatch: use the matching environment and explicit downloader; read the model report. No automatic download/fallback silently changes an explicitly selected model.
- No visible tracks: improve framing/lighting; show both upper bodies. The simple tracker can lose IDs during crossings.
- Frame age/stale result: stop competing CPU work and re-arm. Capture targets 10 FPS at at most 640×480. The UI computes age from browser capture to returned result on the same monotonic clock. Each Arm request supplies `client_now_ms` for server freshness checks; it is never inferred from the first image. Server age still has one-way clock-alignment uncertainty, and neither measure is physical sensor latency.
- Recording unavailable: the startup VP8/WebM encode/decode probe failed, or the local directory is unwritable. Detection can continue with recording off.
- Quota/storage warning: free local disk or delete incidents. Clip admission reserves a conservative uncompressed upper bound, so quota rejection can happen before the actual compressed quota is full.
- Backend disconnected: start/restart the local API, then Start and Arm explicitly. Nothing automatically resumes real actions.

## Two-person demonstration

Use [DEMO.md](DEMO.md) for the current Start → track both people → possible-hit warning → Stop flow. The earlier incident/clip/phone presentation flow is superseded by the owner's request for a simpler first milestone.

## Policy tuning and sustained runtime check

The server exposes experimental entry/exit scores, candidate duration, quiet interval and cooldown through the `SAFETY_EVENT_*` values in `.env.example`. Entry must exceed exit; scores must be finite. Live and replay use the same settings. The full backend event/evaluation paths record a stable threshold-version fingerprint. Live-only mode overrides the incident cooldown to zero and does not persist incidents. These controls do not qualify a model or enable real automatic calls.

WebSocket heartbeats report server state every 500 ms; they never count as fresh inference. Disarm/Stop and delayed HTTP responses are tied to their original camera session. A delayed response cannot re-arm a stopped/hidden camera, and queued frames from a previous arming generation are discarded.

A generated-input engineering soak can run independently of the real camera:

```bash
.venv-model/bin/python scripts/soak_test.py --model stgcn --seconds 1800 --output data/SAFETY_SOAK.json
```

It creates a temporary SQLite app on an ephemeral loopback port, clears call credentials, uses replay/off mode, sends generated high-entropy JPEGs at approximately 10 FPS, enables the bounded clip ring, and samples actual process RSS. It does not open a camera, establish action accuracy, or block the user's separate live app. The report includes its exact input/measurement scope and completion state; a running/failed report is not a passed check. RSS is sampled every 30 seconds. Its raw growth metric compares the sampled run peak against the initial two-minute peak; inspect the samples for later transient spikes and sustained trends. The completed reference run and this distinction are recorded in `SAFETY_SOAK.json` and `SAFETY_EVALUATION.md`.

If local database initialization or writes fail, `/health` remains available and exposes separate persistence readiness. Local preview/warnings can continue; event/history/action operations report a storage-specific 503 where needed. Phone dispatch stays disabled until storage is repaired and the backend is restarted, preventing delayed catch-up attempts. The simplified live screen creates no alert-audio context. Stop and view changes release capture; hidden tabs pause analysis until Resume detection.
