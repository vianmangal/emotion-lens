# Two-person live demo

The current demo is a single live camera feed with person tracking and possible-hit detection. No prerecorded input, incident-history screen or phone setup is needed.

## Start on this Mac

From the repository root, with the existing dependencies/models installed:

```bash
# Terminal 1: backend and Mac/display keep-awake.
caffeinate -di .venv-model/bin/python scripts/run_local.py
```

```bash
# Terminal 2: frontend.
npm run dev --prefix deep_fe/frontend -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173**. Use the existing servers if already running.

This uses the learned RGB model. For a fresh installation, follow [LOCAL_SETUP.md](LOCAL_SETUP.md) to install `requirements-visual.txt` and run `download_models.py --visual`. The old `.venv-safety` environment alone cannot run this model.

## Show the live feature

1. Select **Live Safety**, choose a camera, then click **Start camera**. Tracking and detection start together.
2. Place both consenting participants in view, with their bodies and arm motions visible. Each track gets a colored box and **Person** label; the footer shows the people count. Allow about three seconds of clear two-person video for the action window to fill.
3. Rehearse ordinary gestures and a directed arm motion without contact, leaving space between participants. If the detector accepts the motion, the live status shows **Possible hit detected** and highlights the involved tracks. Occlusion or inadequate history shows a tracking/warm-up message instead.
4. Return to ordinary movement. After the alert clears, another motion can be detected without the old incident-history cooldown.
5. Click **Stop** when finished. If a hidden tab or stream interruption pauses detection, return to the page and click **Resume detection**.

Rehearse with the actual participants and lighting before presenting. The detector is experimental and can miss actions or flag ordinary gestures. A single person shadowboxing is not a two-person interaction. There is no simulated detection trigger.

If the page shows **Only one person tracked**, move the camera farther back and keep both people away from the side edges. If it shows a warm-up message, hold that framing until the RGB window fills. The person detector is separate from joint visibility, so a hidden wrist does not make a detected person disappear. Occluded action, overlapping bodies, small people or another person in the frame can still prevent useful analysis. The model reports a possible interaction; it does not identify which person initiated it or establish contact or intent.

Live-only mode does not save incidents or video clips and does not schedule calls. The [verification report](SAFETY_EVALUATION.md) distinguishes generated/mock checks from unmeasured human accuracy.

For a separately requested phone-notification demo, see [Sarvam setup](SARVAM_SETUP.md). Calling is independent of the live accuracy trials.

## Measure detection with the live camera

Open **Test detection accuracy** below the feed. The panel is optional and starts with no accuracy results. Keep the detector settings unchanged for the whole test.

1. Start the camera and wait for exactly two people to be clearly tracked. Let any previous alert clear.
2. Select **Staged hit attempt** or **Ordinary gesture**, then **Start trial**. For the learned video model, stay still during the four-second countdown. Perform one action during the six-second **MOVE NOW** window, then stay still during the two-second **Hold still** response window. For a staged attempt, stop short with space between people; no contact is needed. For ordinary gestures, vary waves, reaching, turning and mimed high-fives. The baseline retains its shorter two-second countdown.
3. After the response window, **Confirm action & save** only if that selected action was actually performed during MOVE NOW and no new action was performed during Hold still. Otherwise **Discard trial**. A second observer can check the action/timing if one is available.
4. Aim for at least 10 attempts and 10 ordinary gestures, alternate trial types and swap roles halfway. Test different natural speeds, positions and distances. Do not keep only attempts that worked. Include missed motions even when tracking became unclear.
5. Read the counts and **Export test results** before reloading or navigating away. The export contains trial labels, detections, detector settings and tracking coverage; it contains no video, poses or incident history.

Each confirmed trial counts once, even if the warning spans many frames:

- **Hit recall** = detected staged attempts / all staged attempts. Misses remain in this denominator when tracking was poor.
- **Alert precision** = detected staged attempts / all alerted trials, including false alerts during ordinary gestures.
- **Trial accuracy** = correct hit and ordinary-gesture results / all scored trials. This stays blank until both trial types are represented. Precision stays blank if no alert occurred; recall stays blank if no staged attempt was tested.
- **Clear two-person tracking** measures the portion of the trial covered by fresh, observed two-person inference, holding an observation for at most 500 ms until the next result. It helps explain failures and is separate from detection accuracy.

Trials interrupted by Stop, a hidden tab, a long browser stall or no fresh inference are unscored. An alert starting before MOVE NOW also makes the planned trial unscored so it cannot carry into a hit trial as a success. Discarded/interrupted trials remain in the export with a reason. Alerts outside timed windows are not included in the accuracy metrics; make a separate note of them during rehearsal.

Twenty staged trials provide a preliminary demo check for those participants and conditions. They do not establish general real-world accuracy, intent, contact, or injury. Automated tests validate the scoring software with generated inputs. Real public interaction videos additionally exercise recognition without needing a friend or camera; [the model report](VISUAL_STRIKE_MODEL.md) separates those development checks from participant webcam measurements.
