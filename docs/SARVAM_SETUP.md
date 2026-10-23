# Sarvam demo calling

The live camera view stays focused on tracking and detection. It does not schedule phone calls. The existing operator-requested phone test API can use Sarvam hosted Voice Agents instead of ElevenLabs/Twilio.

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

The adapter uses Sarvam's **Instant Outbound** API with a per-call `initial_bot_message` override and records the returned `attempt_id`. `submitted` means Sarvam accepted the request; it does not prove the recipient answered or heard the message. Unknown responses, redirects and network failures are never automatically retried. The existing real automatic-call qualification gate remains in place.

Sarvam's outbound API has no documented per-call recording-disable flag. Recording/transcript retention must be checked in the Sarvam workspace; this integration does not claim to disable provider recording. No video frames or poses are sent to Sarvam.

Official references: [Instant Outbound API](https://docs.sarvam.ai/voice-agents/api/instant-outbound/create), [Rent from Sarvam](https://docs.sarvam.ai/voice-agents/deploy/telephony/rent-from-sarvam), [API Key](https://docs.sarvam.ai/voice-agents/settings/api-key).
