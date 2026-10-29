"""Sarvam hosted Voice Agents outbound calls; no automatic retries."""
import re
from urllib.parse import quote

import httpx

from backend.safety.actions.elevenlabs import trusted_message

API_ROOT = 'https://apps.sarvam.ai/api/outbounds/v1'


def configured(config):
    identifiers = (config.SARVAM_ORG_ID, config.SARVAM_WORKSPACE_ID,
                   config.SARVAM_AGENT_ID, config.SARVAM_CONNECTION_ID)
    numbers = (config.SARVAM_AGENT_PHONE_NUMBER.get_secret_value(),
               config.SAFETY_ALERT_TO_NUMBER.get_secret_value())
    return bool(config.SARVAM_API_KEY.get_secret_value()
                and all(re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in identifiers)
                and all(re.fullmatch(r'\+[1-9]\d{7,14}', value) for value in numbers)
                and config.SARVAM_AGENT_VERSION >= 1)


class Sarvam:
    def __init__(self, config, transport=None):
        self.config, self.transport = config, transport

    async def send(self, is_test=False, event_time=None):
        cfg = self.config
        if not configured(cfg):
            return 'failed', {}, 'phone_not_configured'
        endpoint = (f'{API_ROOT}/orgs/{quote(cfg.SARVAM_ORG_ID, safe="")}'
                    f'/workspaces/{quote(cfg.SARVAM_WORKSPACE_ID, safe="")}/outbounds')
        message = 'Hello, this is the EmotionLens AI demo assistant. ' + trusted_message(is_test, event_time)
        payload = {
            'app_config': {
                'app_id': cfg.SARVAM_AGENT_ID,
                'app_version': cfg.SARVAM_AGENT_VERSION,
                'connection_config': {
                    'connection_id': cfg.SARVAM_CONNECTION_ID,
                    'agent_phone_number': cfg.SARVAM_AGENT_PHONE_NUMBER.get_secret_value(),
                },
                'app_overrides': {'initial_bot_message': message},
            },
            'user_config': {'user_phone_number': cfg.SAFETY_ALERT_TO_NUMBER.get_secret_value()},
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5),
                                         transport=self.transport, follow_redirects=False) as client:
                response = await client.post(endpoint, headers={'X-API-Key': cfg.SARVAM_API_KEY.get_secret_value()}, json=payload)
            if 400 <= response.status_code < 500:
                return 'failed', {}, 'provider_rejected'
            if response.status_code != 200:
                return 'delivery_unknown', {}, 'provider_status_unknown'
            body = response.json()
            attempt = body.get('attempt_id')
            if not isinstance(attempt, str) or not attempt.strip() or len(attempt) > 200:
                return 'delivery_unknown', {}, 'provider_response_unknown'
            # Accepted by Sarvam is not proof that the recipient answered.
            return 'submitted', {'attempt_id': attempt}, None
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            # A timed-out request might already have dialed. Do not retry.
            return 'delivery_unknown', {}, 'network_or_response_unknown'
