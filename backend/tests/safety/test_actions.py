import asyncio
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from backend.safety.actions.elevenlabs import ElevenLabs
from backend.safety.actions.dispatcher import Dispatcher
from backend.safety.models import Action, Incident, new_id


class Provider:
    def __init__(self): self.calls = 0
    async def send(self, **kwargs):
        self.calls += 1
        return 'submitted', {'callSid': 'mock-call'}, None


def credentials(config):
    config.ELEVENLABS_API_KEY = SecretStr('test-only-secret')
    config.ELEVENLABS_AGENT_ID = 'mock-agent'
    config.ELEVENLABS_AGENT_PHONE_NUMBER_ID = 'mock-phone'
    config.SAFETY_ALERT_TO_NUMBER = SecretStr('+15551234567')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected', [('ok','submitted'),('false','failed'),('reject','failed'),('timeout','delivery_unknown'),('server','delivery_unknown'),('invalid','delivery_unknown')])
async def test_provider_contract(config, kind, expected):
    credentials(config)
    def handle(request):
        import json
        body = json.loads(request.content)
        assert body['to_number'] == '+15551234567'
        assert body['call_recording_enabled'] is False
        assert 'test-only-secret' not in request.content.decode()
        assert 'explicitly requested test' in body['conversation_initiation_client_data']['dynamic_variables']['emotionlens_message']
        if kind == 'timeout': raise httpx.ReadTimeout('unknown')
        if kind == 'invalid': return httpx.Response(200, text='not json')
        return httpx.Response(422 if kind == 'reject' else 500 if kind == 'server' else 200, json={'success': kind == 'ok', 'conversation_id': 'mock'})
    state, ids, error = await ElevenLabs(config, httpx.MockTransport(handle)).send(is_test=True)
    assert state == expected
    assert 'test-only-secret' not in str((state, ids, error))


@pytest.mark.asyncio
async def test_duplicate_dispatch_cancel_and_unknown_restart(factory, config):
    credentials(config); clock = [1000.]; provider = Provider()
    d = Dispatcher(factory, config, lambda *_: True, provider, lambda: clock[0])
    aid = await d.enqueue('real', request_id='request-one')
    assert await d.enqueue('real', request_id='request-one') == aid
    clock[0] += 1
    await asyncio.gather(d.dispatch(aid), d.dispatch(aid))
    assert provider.calls == 1
    b = await d.enqueue('real', request_id='request-two')
    await d.cancel(action_id=b)
    clock[0] += 1; await d.dispatch(b)
    assert provider.calls == 1
    async with factory() as db:
        db.add(Action(id=new_id(), dedup_key='crash', mode='real', state='submitting', due_at=clock[0], attempt_at=clock[0]))
        await db.commit()
    pending = await d.enqueue('real', request_id='pending-restart')
    await d.recover()
    async with factory() as db:
        assert (await db.scalar(select(Action).where(Action.dedup_key == 'crash'))).state == 'delivery_unknown'
        assert (await db.get(Action, pending)).state == 'cancelled'
    clock[0] += 10; await d.tick()
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cooldown_quota_and_event_deletion(factory, config):
    credentials(config); config.SAFETY_CALL_COOLDOWN_SECONDS = 10
    clock = [1000.]; provider = Provider()
    d = Dispatcher(factory, config, lambda *_: True, provider, lambda: clock[0])
    e = Incident(id=new_id(), session_id='test', captured_at=0, model_version='test', score=.9)
    async with factory() as db: db.add(e); await db.commit()
    aid = await d.enqueue('real', event_id=e.id)
    clock[0] += 1; await d.dispatch(aid)
    async with factory() as db:
        await db.delete(await db.get(Incident, e.id)); await db.commit()
        assert (await db.get(Action, aid)).event_id is None
    b = await d.enqueue('real', request_id='cooldown')
    clock[0] += 1; await d.dispatch(b)
    async with factory() as db: assert (await db.get(Action, b)).error_category == 'recipient_cooldown'
    for i in range(3):
        clock[0] += 12
        a = await d.enqueue('real', request_id=f'quota-{i}')
        clock[0] += 1; await d.dispatch(a)
    assert provider.calls == 3
    async with factory() as db:
        last = await db.get(Action, a)
        assert last.error_category == 'hourly_quota'


@pytest.mark.asyncio
async def test_dry_run_needs_no_credentials_and_never_calls(factory, config):
    clock = [1000.]; provider = Provider()
    d = Dispatcher(factory, config, lambda *_: True, provider, lambda: clock[0])
    aid = await d.enqueue('dry_run', request_id='dry-run')
    clock[0] += 1; await d.dispatch(aid)
    assert provider.calls == 0
    async with factory() as db: assert (await db.get(Action, aid)).state == 'dry_run'


@pytest.mark.asyncio
async def test_freshness_rechecked_and_no_catchup(factory, config):
    clock = [1000.]; provider = Provider()
    e = Incident(id=new_id(), session_id='test', captured_at=0, model_version='test', score=.9)
    async with factory() as db: db.add(e); await db.commit()
    d = Dispatcher(factory, config, lambda *_: False, provider, lambda: clock[0])
    a = await d.enqueue('real', event_id=e.id)
    clock[0] += 1; await d.dispatch(a)
    async with factory() as db: assert (await db.get(Action, a)).state == 'cancelled'
    b = await d.enqueue('real', request_id='expired')
    clock[0] += 10; await d.dispatch(b)
    assert provider.calls == 0
    async with factory() as db: assert (await db.get(Action, b)).error_category == 'expired_countdown'


@pytest.mark.asyncio
async def test_only_one_in_flight(factory, config):
    credentials(config); clock = [1000.]; release = asyncio.Event(); entered = asyncio.Event()
    class SlowProvider(Provider):
        async def send(self, **kwargs):
            self.calls += 1; entered.set(); await release.wait()
            return 'submitted', {}, None
    provider = SlowProvider()
    d = Dispatcher(factory, config, lambda *_: True, provider, lambda: clock[0])
    a = await d.enqueue('real', request_id='inflight-one'); b = await d.enqueue('real', request_id='inflight-two')
    clock[0] += 1
    task = asyncio.create_task(d.dispatch(a)); await entered.wait()
    await d.dispatch(b)
    await d.cancel(action_id=a)  # Cannot roll back a durable submission claim.
    release.set(); await task
    assert provider.calls == 1
    async with factory() as db: assert (await db.get(Action, b)).error_category == 'call_in_flight'
