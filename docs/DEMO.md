# Two-person live demo

The current demo is a single live camera feed with person tracking and possible-hit detection. No prerecorded input, incident-history screen or phone setup is needed.

## Start on this Mac

From the repository root, with the existing dependencies/models installed:

```bash
# Terminal 1: backend and Mac/display keep-awake.
caffeinate -di .venv-safety/bin/python scripts/run_local.py
```

```bash
# Terminal 2: frontend.
npm run dev --prefix deep_fe/frontend -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173**. Use the existing servers if already running.

## Show the live feature

1. Select **Live Safety**, choose a camera, then click **Start camera**. Tracking and detection start together.
2. Place both consenting participants in view, with heads, shoulders, elbows and wrists visible. Each track gets a colored box, skeleton and **Person** label; the footer shows the people count.
3. Rehearse ordinary gestures and a directed arm motion without contact, leaving space between participants. If the detector accepts the motion, the live status shows **Possible hit detected** and highlights the involved tracks. Occlusion or inadequate history shows a tracking/warm-up message instead.
4. Return to ordinary movement. After the alert clears, another motion can be detected without the old incident-history cooldown.
5. Click **Stop** when finished. If a hidden tab or stream interruption pauses detection, return to the page and click **Resume detection**.

Rehearse with the actual participants and lighting before presenting. The detector is experimental and can miss actions or flag ordinary gestures. A single person shadowboxing is not a two-person interaction. There is no simulated detection trigger.

Live-only mode does not save incidents or video clips and does not schedule calls. The [verification report](SAFETY_EVALUATION.md) distinguishes generated/mock checks from unmeasured human accuracy.
