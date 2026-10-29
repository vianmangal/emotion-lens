# EmotionLens

> Hosted demo restoration requested on 2026-10-29 after the 2026-10-28 shutdown. The latest app is live at https://cnn.vian1.tech. Phone calls remain disabled; the previously deleted Sarvam caller number has not been replaced.

A demo app for **live two-person tracking and possible-hit detection**, with optional facial-expression analysis for images and webcam snapshots.

Built with React, FastAPI, MediaPipe and SQLite. No cloud account or paid API is needed for the live feed.

## Features

- Live camera feed with person boxes and labels.
- **Possible hit detected** alerts from a learned RGB video model.
- An optional test panel to compare staged attempts with ordinary gestures.
- Recovery from transient video stalls in optional demo mode, with bounded frame queues and duplicate person-box filtering.
- Optional owner or demo phone alerts with a 1.5-second trigger and two-second cancellation countdown; disabled by default.

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

By default, Live Safety does not save incident history or video clips, or make phone calls. Owner-enabled phone sessions save incident metadata and can call the configured recipient; video recording remains off.

## Demo phone alerts

With `SAFETY_DEMO_AUTO_CALLS=true` and a configured provider, Live Safety enables calls automatically with **Start camera**. The retired hosted demo used this mode at the owner’s request; when configured, there is no access-code or activation form. The 1.5-second sustained-detection trigger, two-second cancellation countdown, three-attempt hourly limit and five-minute cooldown apply. **Disable calls and stop camera** switches calls off for the current page.

## Owner phone alerts

Configure the phone provider and recipient, set `SAFETY_CALL_MODE=real` and a private `SAFETY_CALL_OWNER_KEY`, then restart the backend. In Live Safety, enter the owner code under **Phone alerts**, select **Enable calls**, and start the camera. The code stays in browser memory and is sent in a request header, never in a URL or saved browser storage. Ordinary public sessions cannot enable paid calls.

On-screen hit alerts use the normal 300 ms confirmation; enabling calls does not delay those alerts. A separate timer requiring 1.5 continuous seconds of positive possible-strike evidence starts a cancelable countdown (2 seconds by default). Interrupted or insufficient evidence resets the 1.5-second trigger. This is motion classification, not verified physical contact. Action analysis supports approximately 3 FPS or faster arriving video, resampling the same 3.1-second window. The screen explains warm-up, slow video and insufficient two-person coverage separately. The detector remains experimental; enabling owner calls does not qualify its accuracy. The interface shows the countdown and provider outcome. Provider acceptance does not prove delivery or that the recipient answered.

**Cancel call**, **Stop**, pausing, hiding the tab, losing tracking, or disconnecting cancels pending calls. Submitted calls cannot be recalled. Calls retain a five-minute cooldown and maximum three attempts per hour; uncertain delivery is never automatically retried. Accuracy-test controls are hidden while real calls are enabled. Disable calls before running staged accuracy trials.

## Hosted demo

The demo was restored at **https://cnn.vian1.tech** on AWS in Mumbai. It opens without a login and supports one active camera session. Browser video frames are transmitted over HTTPS/WebSocket for server inference; the native camera preview stays local. Paid phone calls remain disabled.

The previous deployment was fully removed on 2026-10-28. [DEPLOY_AWS.md](docs/DEPLOY_AWS.md) records the replacement and retained architecture. GitHub Actions runs checks only; deployments are performed separately.

## More information

- [Setup and troubleshooting](docs/LOCAL_SETUP.md)
- [Demo and accuracy testing](docs/DEMO.md)
- [Verification results and test commands](docs/SAFETY_EVALUATION.md)
- [Detector and model details](docs/SAFETY_MODEL_REPORT.md)
- [Current visual model and development measurements](docs/VISUAL_STRIKE_MODEL.md)
- [Explain exported trial results](docs/DETECTION_QUALITY.md)
