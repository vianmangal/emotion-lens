import json

import httpx
import pytest
from pydantic import SecretStr

from backend.safety.actions.dispatcher import Dispatcher
from backend.safety.actions.provider import configured, create_provider, masked_recipient
from backend.safety.actions.sarvam import Sarvam
from backend.safety.models import Action


def sarvam_credentials(config):
    config.SAFETY_CALL_PROVIDER = 'sarvam'
    config.SARVAM_API_KEY = SecretStr('sarvam-test-secret')
    config.SARVAM_ORG_ID = 'org-test'
    config.SARVAM_WORKSPACE_ID = 'workspace-test'
    config.SARVAM_AGENT_ID = 'agent-test'
    config.SARVAM_AGENT_VERSION = 2
    config.SARVAM_CONNECTION_ID = 'connection-test'
    config.SARVAM_AGENT_PHONE_NUMBER = SecretStr('+15550001111')
    config.SAFETY_ALERT_TO_NUMBER = SecretStr('+15550002222')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected', [
    ('accepted', 'submitted'), ('reject', 'failed'), ('rate_limit', 'failed'),
    ('server', 'delivery_unknown'), ('timeout', 'delivery_unknown'),
    ('invalid_json', 'delivery_unknown'), ('missing_id', 'delivery_unknown'),
    ('list', 'delivery_unknown'), ('redirect', 'delivery_unknown'),
])
async def test_sarvam_outbound_contract(config, kind, expected):
    sarvam_credentials(config)
    requests = []

    def handle(request):
        requests.append(request)
        assert str(request.url) == 'https://apps.sarvam.ai/api/outbounds/v1/orgs/org-test/workspaces/workspace-test/outbounds'
        assert request.headers['X-API-Key'] == 'sarvam-test-secret'
        body = json.loads(request.content)
        assert body['app_config']['app_version'] == 2
        assert body['app_config']['connection_config'] == {
            'connection_id': 'connection-test', 'agent_phone_number': '+15550001111',
        }
        assert body['user_config'] == {'user_phone_number': '+15550002222'}
        assert 'AI demo assistant' in body['app_config']['app_overrides']['initial_bot_message']
        assert 'explicitly requested test' in body['app_config']['app_overrides']['initial_bot_message']
        assert 'sarvam-test-secret' not in request.content.decode()
        if kind == 'timeout':
            raise httpx.ReadTimeout('ambiguous delivery')
        if kind == 'invalid_json':
            return httpx.Response(200, text='invalid')
        if kind == 'list':
            return httpx.Response(200, json=[])
        status = {'reject': 422, 'rate_limit': 429, 'server': 500, 'redirect': 307}.get(kind, 200)
        return httpx.Response(status, json={} if kind == 'missing_id' else {'attempt_id': 'attempt-test'},
                              headers={'location': 'https://example.com/never-follow'})

    result = await Sarvam(config, httpx.MockTransport(handle)).send(is_test=True)
    assert result[0] == expected
    assert len(requests) == 1  # No retry after a possibly submitted call, including 429/500/timeouts.
    assert 'sarvam-test-secret' not in str(result)
    assert result[1] == ({'attempt_id': 'attempt-test'} if kind == 'accepted' else {})


@pytest.mark.asyncio
async def test_event_message_is_distinct_from_test(config):
    sarvam_credentials(config)

    def handle(request):
        message = json.loads(request.content)['app_config']['app_overrides']['initial_bot_message']
        assert 'Possible striking motion' in message
        assert '2026-10-23T10:00:00+00:00' in message
        assert 'false alarm' in message
        assert 'requested test' not in message
        return httpx.Response(200, json={'attempt_id': 'event-test'})

    assert (await Sarvam(config, httpx.MockTransport(handle)).send(event_time='2026-10-23T10:00:00+00:00'))[0] == 'submitted'


@pytest.mark.asyncio
async def test_selected_sarvam_never_falls_back_to_elevenlabs(config):
    config.ELEVENLABS_API_KEY = SecretStr('legacy-key')
    config.ELEVENLABS_AGENT_ID = 'legacy-agent'
    config.ELEVENLABS_AGENT_PHONE_NUMBER_ID = 'legacy-phone'
    config.SAFETY_ALERT_TO_NUMBER = SecretStr('+15550002222')
    config.SAFETY_CALL_PROVIDER = 'sarvam'
    assert not configured(config)
    assert isinstance(create_provider(config), Sarvam)
    assert masked_recipient(config) == 'Not configured'

    def unexpected_request(request):
        pytest.fail('Unconfigured Sarvam must not contact a provider')

    assert await Sarvam(config, httpx.MockTransport(unexpected_request)).send(is_test=True) == ('failed', {}, 'phone_not_configured')
    sarvam_credentials(config)
    assert configured(config)
    assert masked_recipient(config) == '•••• 2222'
    config.SARVAM_ORG_ID = '../other-org'
    assert not configured(config)


@pytest.mark.asyncio
async def test_sarvam_dispatch_preserves_dedup_cooldown_and_dry_run(factory, config):
    sarvam_credentials(config)
    now = [1000.]
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={'attempt_id': 'once'})

    d = Dispatcher(factory, config, lambda *_: True, Sarvam(config, httpx.MockTransport(handle)), lambda: now[0])
    dry = await d.enqueue('dry_run', request_id='sarvam-preview')
    now[0] += 1
    await d.dispatch(dry)
    async with factory() as db:
        action = await db.get(Action, dry)
        assert action.state == 'dry_run'
        assert action.provider_ids['dry_run_payload']['external_service'] == 'Sarvam hosted Voice Agents (not contacted)'
        assert action.provider_ids['dry_run_payload']['call_recording_enabled'] is None
    assert not calls
    aid = await d.enqueue('real', request_id='sarvam-one')
    assert await d.enqueue('real', request_id='sarvam-one') == aid
    now[0] += 1
    await d.dispatch(aid)
    await d.dispatch(aid)
    blocked = await d.enqueue('real', request_id='sarvam-cooldown')
    now[0] += 1
    await d.dispatch(blocked)
    assert len(calls) == 1
    async with factory() as db:
        assert (await db.get(Action, aid)).state == 'submitted'
        assert (await db.get(Action, blocked)).error_category == 'recipient_cooldown'
