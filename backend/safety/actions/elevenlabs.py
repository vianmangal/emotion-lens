import re
import httpx

ENDPOINT = 'https://api.elevenlabs.io/v1/convai/twilio/outbound-call'


def configured(config):
    return bool(config.ELEVENLABS_API_KEY.get_secret_value() and config.ELEVENLABS_AGENT_ID and config.ELEVENLABS_AGENT_PHONE_NUMBER_ID and re.fullmatch(r'\+[1-9]\d{7,14}', config.SAFETY_ALERT_TO_NUMBER.get_secret_value()))


def masked_recipient(config):
    number = config.SAFETY_ALERT_TO_NUMBER.get_secret_value()
    return f'•••• {number[-4:]}' if configured(config) else 'Not configured'


def trusted_message(is_test=False, event_time=None):
    return ('This is an explicitly requested test call from your local EmotionLens demo.' if is_test else
                   f'Possible striking motion was flagged by the local webcam at {event_time}. This may be a false alarm. Please check the local application.')


class ElevenLabs:
    def __init__(self, config, transport=None):
        self.config, self.transport = config, transport

    async def send(self, is_test=False, event_time=None):
        cfg = self.config
        message = trusted_message(is_test, event_time)
        payload = {'agent_id': cfg.ELEVENLABS_AGENT_ID, 'agent_phone_number_id': cfg.ELEVENLABS_AGENT_PHONE_NUMBER_ID,
                   'to_number': cfg.SAFETY_ALERT_TO_NUMBER.get_secret_value(), 'call_recording_enabled': False,
                   'conversation_initiation_client_data': {'dynamic_variables': {'emotionlens_message': message}}}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), transport=self.transport, follow_redirects=False) as client:
                response = await client.post(ENDPOINT, headers={'xi-api-key': cfg.ELEVENLABS_API_KEY.get_secret_value()}, json=payload)
            if 400 <= response.status_code < 500:
                return 'failed', {}, 'provider_rejected'
            if response.status_code != 200:
                return 'delivery_unknown', {}, 'provider_status_unknown'
            body = response.json()
            if body.get('success') is not True:
                return 'failed', {}, 'provider_rejected'
            ids = {k: str(body[k])[:200] for k in ('conversation_id', 'callSid') if body.get(k)}
            return 'submitted', ids, None
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            # An ambiguous request may already have dialed. Never retry it automatically.
            return 'delivery_unknown', {}, 'network_or_response_unknown'
