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

## Measure detection with the live camera

Open **Test detection accuracy** below the feed. The panel is optional and starts with no accuracy results. Keep the detector settings unchanged for the whole test.

1. Start the camera and wait for exactly two people to be clearly tracked. Let any previous alert clear.
2. Select **Staged hit attempt** or **Ordinary gesture**, then **Start trial**. Stay still during the two-second countdown. Perform one action during the six-second **MOVE NOW** window shown on the video. For a staged attempt, stop short with space between people; no contact is needed. For ordinary gestures, vary waves, reaching, turning and mimed high-fives.
3. After the window, **Confirm action & save** only if that selected action was actually performed during MOVE NOW. Otherwise **Discard trial**. A second observer can check the action/timing if one is available.
4. Aim for at least 10 attempts and 10 ordinary gestures, alternate trial types and swap roles halfway. Test different natural speeds, positions and distances. Do not keep only attempts that worked. Include missed motions even when tracking became unclear.
5. Read the counts and **Export test results** before reloading or navigating away. The export contains trial labels, detections, detector settings and tracking coverage; it contains no video, poses or incident history.

Each confirmed trial counts once, even if the warning spans many frames:

- **Hit recall** = detected staged attempts / all staged attempts. Misses remain in this denominator when tracking was poor.
- **Alert precision** = detected staged attempts / all alerted trials, including false alerts during ordinary gestures.
- **Trial accuracy** = correct hit and ordinary-gesture results / all scored trials. This stays blank until both trial types are represented. Precision stays blank if no alert occurred; recall stays blank if no staged attempt was tested.
- **Clear two-person tracking** measures the portion of the trial covered by fresh, observed two-person inference, holding an observation for at most 500 ms until the next result. It helps explain failures and is separate from detection accuracy.

Trials interrupted by Stop, a hidden tab, a long browser stall or no fresh inference are unscored. An alert starting before MOVE NOW also makes the planned trial unscored so it cannot carry into a hit trial as a success. Discarded/interrupted trials remain in the export with a reason. Alerts outside timed windows are not included in the accuracy metrics; make a separate note of them during rehearsal.

Twenty staged trials provide a preliminary demo check for those participants and conditions. They do not establish general real-world accuracy, intent, contact, or injury. Automated tests validate the scoring software with generated inputs; only the participant trials measure live human detection.
