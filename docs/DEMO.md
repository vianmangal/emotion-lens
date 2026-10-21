# Two-person live demo

This walkthrough uses the real webcam and the default experimental trajectory detector. It needs no prerecorded input or phone credentials. Rehearse with the actual participants, camera position and lighting before presenting; human detection accuracy has not been measured.

## Start on this Mac

From the repository root, with the existing dependencies/models installed:

```bash
# Terminal 1: local backend; keep the Mac and display awake while it runs.
caffeinate -di .venv-safety/bin/python scripts/run_local.py
```

```bash
# Terminal 2: local frontend.
npm run dev --prefix deep_fe/frontend -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173**. If the app is already running, use it instead of starting duplicate servers. The backend command selects the documented default trajectory baseline. The optional pretrained comparison is `.venv-model/bin/python scripts/run_local.py --model stgcn`; stop the existing backend before switching. STGCN needs at least three seconds of stable pose history and has not been validated on these participants.

## Before the audience arrives

1. Open **Live Safety**, choose the camera and click **Start camera**. Allow camera permission.
2. Frame both consenting adults from head to hips, with shoulders, elbows and wrists visible. Leave room for arm movement inside the frame. Rehearse non-contact motions with space between participants.
3. Check **Model: Ready**, two observed people and stable tracking. Read any framing/visibility message. Model readiness alone does not establish reliable action recognition.
4. Enable **Save event clips** before arming if you want to show playback. Enable **Local alert sound** if wanted. Select **Phone mode → Dry run**.
5. Click **Arm monitoring** and wait for the temporal window to warm. Rehearse the complete flow below. Keep this browser tab visible; hidden tabs and stale input disarm monitoring.

## Presentation flow

| Step | What to demonstrate |
| --- | --- |
| Live input | Move normally and show the camera preview, pose overlays, people count, actual FPS and frame age. Explain that the feature compares motion over time between two visible people. |
| Motion decision | Perform the rehearsed directed arm motion without contact. If the detector accepts it, the UI shows **Possible striking motion — review footage**. A candidate, occlusion or missed action is not a confirmed detection; describe the actual result. |
| Local incident | Let the motion end and allow roughly five seconds for the available post-event clip to finish. Open **Incident History**, play the clip and apply a review label. Feedback is stored locally; it does not retrain the detector. |
| Phone workflow | Show the dry-run countdown and **Cancel now**, or let it finish and show the recorded intended message. Dry run sends no provider request. **Test dry run** can demonstrate this adapter separately, even if the detector abstains. |
| Episode behavior | One continuous episode produces one incident. After the episode ends, the default cooldown is 30 seconds; repeated motions during that interval need not create another incident. |
| Finish | Click **Disarm**, then **Stop** to release the camera. Delete unwanted event clips from history. |

If the rehearsed action never produces an incident, inspect the people/visibility/history messages and framing before presenting. Report the limitation instead of describing a manual phone test as an automatic detection. A one-person shadowboxing demonstration is expected to abstain because the feature requires two observed people.

## A short explanation to say aloud

> This is a local webcam motion demo. It tracks two people over a sequence of frames and flags possible directed striking motion for review. The alert is experimental: it can miss actions or flag ordinary gestures, and it does not establish intent. Clips and incident feedback stay on this computer. The phone step shown here is a local dry run.

The engineering checks and completed generated-input endurance run are recorded in [SAFETY_EVALUATION.md](SAFETY_EVALUATION.md). They do not replace the rehearsal or a measured human accuracy evaluation. Automatic real calls remain unavailable while detector qualification is unmet.
