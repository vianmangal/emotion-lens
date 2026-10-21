# EmotionLens

A local FastAPI + React app for facial-expression analysis and **experimental live webcam motion monitoring**. It runs on one computer with SQLite and local files. No AWS account, PostgreSQL, Docker, hosting, or paid API is needed.

Live Safety analyzes a sequence of person poses and flags **“Possible striking motion — review footage.”** It does not establish intent or prove an assault. Facial-expression scores never enter safety decisions.

## Start locally

Python 3.11, Node.js 22 or newer, and a desktop Chromium browser are recommended. From the repository root:

```bash
python3.11 -m venv .venv-safety
source .venv-safety/bin/activate
pip install -r backend/requirements-safety.txt
python scripts/download_models.py
python scripts/run_local.py
```

In another terminal:

```bash
cd deep_fe/frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**, select **Live Safety**, click **Start camera**, then **Arm monitoring**. Camera access and microphone capture are off initially; audio capture is never requested. The default detector is an experimental directed-wrist trajectory baseline. For the pretrained temporal classifier:

```bash
# Explicit isolated setup; downloads pinned code and a checksum-verified checkpoint.
.venv-safety/bin/python scripts/setup_temporal.py
# Stop the other backend before starting this one.
.venv-model/bin/python scripts/run_local.py --model stgcn
```

See [Local setup](docs/LOCAL_SETUP.md) for camera recovery, optional expression weights, phone configuration, migrations, and cleanup.

## What is implemented

- Live webcam selection and preview; explicit Start/Stop and Arm/Disarm.
- Local multi-person pose estimation, session-local tracking, and interchangeable temporal models: a trajectory baseline and pretrained STGCN/NTU60 adapter.
- Conservative abstention, candidate/episode/cooldown policy, fresh-frame checks, and one active session with bounded processing.
- SQLite incident history, review labels, and event deletion.
- Opt-in pre/post event VP8/WebM clips, local sound, quota and retention.
- Cancellable phone countdowns; offline dry runs; server-only ElevenLabs native Twilio adapter for explicit tests.
- Restart recovery, persistent call deduplication/cooldown/quota, no automatic retry on ambiguous delivery.
- Original image upload and webcam snapshot views. Optional TensorFlow and local expression weights are loaded only when requested.

**Detector qualification remains unmet.** Live monitoring works experimentally; there is no measured held-out precision/recall or real webcam accuracy claim. Automatic real calls are locked in code. Explicit configured real test calls are available independently. No real call was placed during implementation. See [model feasibility](docs/SAFETY_MODEL_REPORT.md), [actual verification results](docs/SAFETY_EVALUATION.md), the [requirement audit](docs/IMPLEMENTATION_AUDIT.md), and the [30-minute engineering run](docs/SAFETY_SOAK.json).

## Checks

```bash
.venv-safety/bin/python -m pip install -r backend/requirements-test.txt
.venv-safety/bin/python -m pytest
cd deep_fe/frontend
npm run build
npx playwright install chromium
npm run test:e2e
```

Tests use mocks/fake camera input, temporary SQLite databases, and generated media. They never contact the phone provider. Replay/evaluation helpers accept local videos and cannot auto-call:

```bash
.venv-safety/bin/python scripts/replay.py path/to/video.mp4 --output data/replay.json
.venv-model/bin/python scripts/evaluate.py path/to/manifest.json --model stgcn --split development --output data/dev.json
.venv-model/bin/python scripts/evaluate.py path/to/manifest.json --model stgcn --split held_out --development-report data/dev.json --output data/evaluation.json
```

## Architecture

```text
Browser webcam → bounded WebSocket → person poses / tracking → temporal classifier
                                                           → episode policy
                                                           → SQLite incidents
                                                           → optional local clips
                                                           → dry-run action / phone adapter
Uploaded image → face preprocessing → optional TensorFlow CNN → SQLite prediction
```

Backend: `backend/`; UI: `deep_fe/frontend/`; schema changes: `migrations/`; explicit setup/evaluation: `scripts/`; private local runtime data: ignored `data/`.

The original expression report covers 6,236 samples: 61.45% accuracy, 59.03% macro F1, 61.76% weighted F1. These are historical expression results and say nothing about action detection. Original training/evaluation scripts and tracked expression weights are preserved.

The [Live Safety PRD](docs/PRD-LIVE-SAFETY.md) records the requirements; [the original handoff](docs/IMPLEMENTATION-HANDOFF.md) is historical implementation context. Obsolete repository deployment files were removed. No cloud account resources were accessed or changed.
