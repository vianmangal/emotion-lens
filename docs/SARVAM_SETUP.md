# Sarvam demo calling

> Shutdown verified on 2026-10-28: the demo caller number was archived and permanently deleted with owner confirmation. Sarvam showed zero numbers, no inbound deployments and no outbound campaigns. Local calling is disabled and the released caller-number setting is cleared.

Calling is disabled by default and the demo no longer has a rented caller number. The optional Live Safety phone alerts and operator-requested phone test API support Sarvam hosted Voice Agents instead of ElevenLabs/Twilio. The setup below is retained for a future deliberately configured installation; it does not describe an active service.

## Account setup

In Sarvam Voice Agents, complete Individual KYC, rent a number, and create an agent. Set an English AI-demo greeting and instructions to deliver the notification, invoke **End Interaction**, and finish. Use a one-minute maximum, disable voicemail, nudges and call forwarding, then **commit** a version. The backend pins that committed version, so editing a newer draft does not change calls.

Open **Deploy with code → Instant outbound**, select the agent, committed version, connection and rented caller number. The generated recipe supplies the organisation, workspace, agent and connection IDs. Create a workspace API key under **Settings → API Key**. Store it only in the ignored local `.env`, never in browser code or a commit.

```dotenv
SAFETY_CALL_PROVIDER=sarvam
SARVAM_API_KEY=
SARVAM_ORG_ID=
SARVAM_WORKSPACE_ID=
SARVAM_AGENT_ID=
SARVAM_AGENT_VERSION=1
SARVAM_CONNECTION_ID=
SARVAM_AGENT_PHONE_NUMBER=
SAFETY_ALERT_TO_NUMBER=
SAFETY_CALL_MODE=off
```

Both phone numbers use E.164 format, including `+` and country code. `SARVAM_AGENT_PHONE_NUMBER` is the rented caller number; `SAFETY_ALERT_TO_NUMBER` is the recipient. Restart the backend to load changes. Credentials for the unselected provider are never used as a fallback.

## Explicit phone tests

`POST /safety/phone/test` retains its local capability requirement, recipient/charge acknowledgement, cancelable countdown, cooldown and three-attempt hourly limit. Use a fresh request ID for a deliberately requested test. `dry_run` never contacts either provider. A `real` test must be explicitly requested by the operator and sets `recipient_acknowledged: true`. Call messages distinguish an operator test from a possible motion alert.

The adapter uses Sarvam's **Instant Outbound** API with a per-call `initial_bot_message` override and records the returned `attempt_id`. `submitted` means Sarvam accepted the request; it does not prove the recipient answered or heard the message. Unknown responses, redirects and network failures are never automatically retried.

Owner-requested automatic alerts require `SAFETY_CALL_MODE=real` and a private `SAFETY_CALL_OWNER_KEY`, plus the configured Sarvam credentials and recipient. Enter the owner code in Live Safety before starting the camera. 1.5 seconds of sustained positive detection starts a two-second cancellation countdown. Optional `SAFETY_DEMO_AUTO_CALLS=true` bypasses the owner-code form and arms calls with Start camera only when real mode and a provider are configured; keep it false for normal local use. The detector remains experimental; owner activation is separate from model qualification. See the README for cancellation behavior and call limits.

Sarvam's outbound API has no documented per-call recording-disable flag. Recording/transcript retention must be checked in the Sarvam workspace; this integration does not claim to disable provider recording. No video frames or poses are sent to Sarvam.

Official references: [Instant Outbound API](https://docs.sarvam.ai/voice-agents/api/instant-outbound/create), [Rent from Sarvam](https://docs.sarvam.ai/voice-agents/deploy/telephony/rent-from-sarvam), [API Key](https://docs.sarvam.ai/voice-agents/settings/api-key).
