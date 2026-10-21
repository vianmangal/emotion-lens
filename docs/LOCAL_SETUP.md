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

1. Select Live Safety. Start the camera and allow camera permission; microphone permission is never requested.
2. Keep both participants' upper bodies and arms visible. Camera switching requires Stop, select another device, then Start.
3. Sound/clip preferences persist in local browser storage; phone arming never persists. Choose local sound, optional clips, and Off/Dry run phone mode before arming. Clip defaults: up to 5 seconds before and 5 seconds after an incident; no audio; 24-hour retention; 500 MiB quota. Metadata defaults to 7 days. The UI reports current storage.
4. Arm and wait for a stable temporal window. Unknown/occluded/lone-person evidence abstains. Candidate movement cannot call anyone.
5. Review an incident as Relevant, False alarm, or Unclear. Play the available clip or delete both event and clip.
6. Disarm cancels countdowns. Stop releases camera/WebSocket/buffers. Switching to another tab/view also releases the camera.

Hidden browser tabs, frame/inference gaps over 1 second, frozen preview, and disconnects pause/disarm monitoring. Returning to a visible tab never re-arms it automatically. A session expires after 30 minutes; stop/start it to renew. Insufficient evidence is distinct from a negative decision. Monitoring never claims the scene is safe.

## Optional expression feature

```bash
.venv-safety/bin/python -m pip install -r backend/requirements-expression.txt
```

Set `MODEL_PATH=models/emotion_cnn_20260530_193721_best.keras` in a root `.env`. Existing tracked expression weights are preserved. `/predict` retains its multipart `image` and response contract; `/health` reports expression configuration separately. TensorFlow is lazy and optional, so missing expression dependencies/weights cannot prevent safety startup. The physical weight files were not validated during this implementation; legacy preprocessing/API behavior is tested with an inference mock.

## ElevenLabs (optional)

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

After restarting the backend, check the recipient acknowledgement box and click **Send real test call** to authorize one paid test. Cancel its countdown if needed. No real call is part of installation/tests. Automatic real mode remains locked because detector qualification is unmet.

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
- Frame age/stale result: stop competing CPU work and re-arm. Capture targets 10 FPS at at most 640×480. UI frame age is relative to a monotonic first-frame clock alignment; it is not an independently synchronized absolute network delay measurement.
- Recording unavailable: the startup VP8/WebM encode/decode probe failed, or the local directory is unwritable. Detection can continue with recording off.
- Quota/storage warning: free local disk or delete incidents. Clip admission reserves a conservative uncompressed upper bound, so quota rejection can happen before the actual compressed quota is full.
- Backend disconnected: start/restart the local API, then Start and Arm explicitly. Nothing automatically resumes real actions.

## Non-contact demonstration

With two consenting adults, show an ordinary gesture, then a slow rehearsed **non-contact** directed arm motion with both upper bodies visible. The baseline or STGCN may abstain or miss the action; do not treat an unsuccessful demonstration as a passed detector test. If policy fires, inspect the possible-motion warning and clip, review-label the incident, and verify a dry-run record. Cancel/disarm before the countdown finishes to demonstrate cancellation. A single person shadowboxing must not generate an inter-person event. This is a live demo; replay is an optional engineering/evaluation tool.
