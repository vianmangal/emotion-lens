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

Open **http://127.0.0.1:5173**, select **Live Safety** and click **Start camera**. This starts the video feed, person tracking and motion detection together. **Stop** releases the camera. If detection pauses after a hidden tab or an interrupted stream, click **Resume detection**.

## Current live view

- One camera feed with labeled person boxes and skeletons.
- A live people count, with a request to show two people when fewer are visible.
- A **Possible hit detected** warning when directed striking motion passes the temporal detector.
- Camera selection, Start, Stop and recovery through Resume detection.

The current view has no incident history, phone controls, recording controls or separate Arm step. Live-only sessions do not save incidents/clips or schedule phone actions. Existing local records are preserved. The older backend incident/phone APIs remain available for later work, outside this simplified view.

The default detector is an experimental directed-wrist trajectory baseline over multiple pose frames. It requires two visible people and relevant arm landmarks; occluded or stale input is insufficient evidence. Human accuracy has not been measured, so the warning describes possible motion rather than proven contact or intent.

For the planned two-person presentation, follow the [live demo walkthrough](docs/DEMO.md). See [local setup](docs/LOCAL_SETUP.md) for dependencies and camera recovery. The original upload and webcam-snapshot views remain available separately.

An optional pretrained temporal comparison is also installed independently:

```bash
.venv-safety/bin/python scripts/setup_temporal.py
# Stop the other backend before starting this one.
.venv-model/bin/python scripts/run_local.py --model stgcn
```

See [model feasibility](docs/SAFETY_MODEL_REPORT.md) and [verification results](docs/SAFETY_EVALUATION.md) for measurements and their limits. The [original PRD](docs/PRD-LIVE-SAFETY.md) describes the earlier, broader scope; the owner's latest request prioritizes the simple live view above.

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
                                                           → motion policy
                                                           → live tracks / possible-hit status

Older full API mode → SQLite incidents / optional clips / phone adapter
Uploaded image → face preprocessing → optional TensorFlow CNN → SQLite prediction
```

Backend: `backend/`; UI: `deep_fe/frontend/`; schema changes: `migrations/`; explicit setup/evaluation: `scripts/`; private local runtime data: ignored `data/`.

The original expression report covers 6,236 samples: 61.45% accuracy, 59.03% macro F1, 61.76% weighted F1. These are historical expression results and say nothing about action detection. Original training/evaluation scripts and tracked expression weights are preserved.

The [Live Safety PRD](docs/PRD-LIVE-SAFETY.md) records the earlier broader roadmap; [the original handoff](docs/IMPLEMENTATION-HANDOFF.md) is historical implementation context. Obsolete repository deployment files were removed. No cloud account resources were accessed or changed.
