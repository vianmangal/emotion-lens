# EmotionLens

A demo app for **live two-person tracking and possible-hit detection**, with optional facial-expression analysis for images and webcam snapshots.

Built with React, FastAPI, MediaPipe and SQLite. No cloud account or paid API is needed for the live feed.

## Features

- Live camera feed with person boxes and labels.
- **Possible hit detected** alerts from a learned RGB video model.
- An optional test panel to compare staged attempts with ordinary gestures.

## Run locally

Use Python 3.11, Node.js 22+ and a Chromium-based browser. Run these commands from the repository root.

**Terminal 1 — backend**

```bash
python3.11 -m venv .venv-visual
source .venv-visual/bin/activate
pip install -r backend/requirements-visual.txt
python scripts/download_models.py --visual
python scripts/run_local.py
```

**Terminal 2 — frontend**

```bash
cd deep_fe/frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open **http://127.0.0.1:5173** → **Live Safety** → **Start camera**.

Keep both people's shoulders, elbows and hands in view. Use staged motions that stop short of contact. Click **Stop** to release the camera, or **Resume detection** if monitoring pauses.

## Current limitations

Hit detection is experimental: it can miss motions or flag ordinary gestures. An alert does not establish contact or intent. Facial-expression scores are separate from hit detection.

The Live Safety screen does **not** save incident history or video clips, or make phone calls.

## Hosted demo

The owner-access deployment is at **https://cnn.vian1.tech**. The browser captures the camera locally and sends frames over an authenticated HTTPS/WebSocket connection to the AWS detection backend. Hosted inference adds network latency. Camera preview and tracking rates are shown separately. The hosted demo supports one active camera session at a time.

Deployment details and update instructions are in [DEPLOY_AWS.md](docs/DEPLOY_AWS.md). Calling remains off in Live Safety; separately requested manual test calls use the protected backend API. The detector is still experimental and automatic real calls remain unavailable.

## More information

- [Setup and troubleshooting](docs/LOCAL_SETUP.md)
- [Demo and accuracy testing](docs/DEMO.md)
- [Verification results and test commands](docs/SAFETY_EVALUATION.md)
- [Detector and model details](docs/SAFETY_MODEL_REPORT.md)
- [Current visual model and development measurements](docs/VISUAL_STRIKE_MODEL.md)
- [Explain exported trial results](docs/DETECTION_QUALITY.md)
