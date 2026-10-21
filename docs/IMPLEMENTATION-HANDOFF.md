# Implementation handoff — EmotionLens Live Safety

Use the following prompt in the implementation task, with this repository open. The complete requirements are in [PRD-LIVE-SAFETY.md](PRD-LIVE-SAFETY.md).

---

Implement `docs/PRD-LIVE-SAFETY.md` in this repository. Read the full PRD and applicable repository instructions first, inspect the current code and local changes, then work through its implementation phases.

The intended product is a local webcam project that detects possible striking motions between two visible people, creates reviewable local incidents/clips, and optionally triggers an ElevenLabs outbound phone alert. It must not use facial emotions as evidence of dangerousness or claim to predict intent.

Important decisions:

- This app will run locally and will never need public hosting. Remove obsolete AWS Terraform, deployment workflow, S3 startup downloads, and cloud instructions from the repository. Use FastAPI + React + SQLite + local models/files. Do not provision or manipulate AWS resources.
- Keep image upload/webcam snapshot features where practical. Make missing expression-model weights independent of safety-mode startup. Two local expression weight files exist under `models/`; preserve them. They are not action models.
- Prove action-model feasibility early on the actual machine. Record exact model/checkpoint licenses, preprocessing, class mapping, versions, and measured latency. Heuristics and mocks cannot be reported as a validated live aggression detector.
- Implement the live feed, bounded temporal pipeline, explicit arm/disarm, abstention, event deduplication, incident history, optional clips, and model evaluation specified in the PRD.
- Use ElevenLabs' native outbound-call integration through a connected telephony provider, initially Twilio. API credentials alone are insufficient: an agent and outbound-capable number are required. The local app initiates outbound HTTPS; no public webhook/server is needed for the initial call submission design.
- Default real calling to off, support dry run without credentials, and implement one allowlisted recipient, a cancellable countdown, persisted deduplication/cooldowns/quotas, and no automatic retries after ambiguous submission. Keep secrets server-side. Never place a real call merely to run tests; implement explicit operator controls for authorized tests/arming.
- Preserve unrelated edits and local data. Do not publish, deploy, buy services, or push/merge code unless separately instructed.

Make routine implementation decisions independently within the PRD. Record justified deviations. If model weights, compatible runtime, evaluation footage, or provider setup are missing, finish independent engineering work, use clearly labeled test doubles for software tests, and report the exact remaining gate. Do not conceal an unmet detection gate or label a simulated demo complete.

Deliver working local code, relevant tests, local setup instructions, the model feasibility report, and the evaluation report. Distinguish measured outcomes from proposed targets and real-provider verification from mocked tests. End with exact run commands and remaining limitations.

---

Authoring note: this handoff is a specification only. No Live Safety implementation, AWS modification, provider setup, or phone call was performed while writing it.
