import asyncio
import base64
import time
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select
from backend.main import create_app
from backend.models.db_models import Prediction
from backend.safety.models import Incident, Action, new_id
from backend.safety.event_policy import Evidence

ORIGIN = {'origin': 'http://localhost:5173', 'host': 'localhost'}


@pytest.fixture
def client(config):
    app = create_app(config)
    with TestClient(app, base_url='http://localhost') as c:
        c.headers['X-Safety-Capability'] = c.get('/safety/bootstrap', headers={'X-EmotionLens-Client': 'local-ui'}).json()['capability']
        yield c, app


def arm_payload(options=None):
    return {'client_now_ms': time.monotonic()*1000, **(options or {})}


def receive_result(ws):
    while True:
        result = ws.receive_json()
        if result.get('type') != 'heartbeat':
            return result


def wait_closed(c, app):
    async def wait():
        for _ in range(100):
            if app.state.safety.session is None:
                return
            await asyncio.sleep(.01)
        assert app.state.safety.session is None
    c.portal.call(wait)


def session(c, source='live', **options):
    r = c.post('/safety/sessions', json={'source': source, **options})
    assert r.status_code == 201, r.text
    return r.json()


def test_local_security_readiness_and_missing_weights(client):
    c, app = client
    h = c.get('/health').json()
    assert h['status'] == 'ok' and not h['safety']['ready']
    assert not c.get('/safety/status').json()['real_auto_calls_available']
    assert c.get('/health', headers={'host':'evil.example'}).status_code == 400
    assert c.get('/safety/bootstrap', headers={'origin':'http://evil.example','X-EmotionLens-Client':'local-ui'}).status_code == 403
    assert c.post('/safety/phone/test', json={'request_id':'abcdefghi'}, headers={'origin':'null'}).status_code == 403
    assert c.get('/safety/bootstrap').status_code == 403
    assert c.post('/safety/sessions', json={}, headers={'X-Safety-Capability':''}).status_code == 403
    assert c.post('/safety/sessions', content='x'*65537).status_code == 413
    s = session(c)
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability':s['capability']}); assert receive_result(ws)['type'] == 'connected'
        assert c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload({}), headers={'X-Session-Capability':s['capability']}).status_code == 409
    wait_closed(c, app)


def test_websocket_origin_capability_and_invalid_payload(client):
    c, app = client
    s = session(c)
    for headers in ({'origin':'http://evil.example', 'host':'localhost'}, {'host':'localhost'}):
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=headers): pass
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
            ws.send_json({'capability':'wrong'}); receive_result(ws)
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability':s['capability']}); receive_result(ws)
        ws.send_text('x'*(1024*1024+1))
        with pytest.raises(WebSocketDisconnect): receive_result(ws)
    wait_closed(c, app)


def test_sqlite_history_review_delete_and_restart(client, config):
    c, app = client
    event_id = new_id()
    async def insert():
        async with app.state.safety.factory() as db:
            db.add(Incident(id=event_id, session_id='test', captured_at=0, model_version='test', score=.8))
            db.add(Prediction(emotion='happy', confidence=.8, all_scores={'happy':.8}))
            await db.commit()
    c.portal.call(insert)
    assert c.patch(f'/safety/events/{event_id}', json={'label':'false_alarm'}).status_code == 200
    assert c.patch(f'/safety/events/{event_id}', json={'label':'proven_assault'}).status_code == 422
    assert c.get('/safety/events').json()['items'][0]['review_label'] == 'false_alarm'
    assert c.post('/safety/phone/test', json={'request_id':'dry-run-one'}).status_code == 202
    c.portal.call(app.state.safety.dispatcher.recover)
    with TestClient(create_app(config), base_url='http://localhost') as other:
        other.headers['X-Safety-Capability'] = other.get('/safety/bootstrap',headers={'X-EmotionLens-Client':'local-ui'}).json()['capability']
        assert other.get('/safety/events').json()['items'][0]['review_label'] == 'false_alarm'
        assert other.get('/safety/phone/actions').json()['items'][0]['state'] == 'cancelled'
        assert other.delete(f'/safety/events/{event_id}').status_code == 200
        assert not other.get('/safety/events').json()['items']


def test_real_test_requires_ack_and_no_arbitrary_recipient(client):
    c, app = client
    assert c.post('/safety/phone/test', json={'mode':'real','request_id':'real-test'}).status_code == 409
    assert c.post('/safety/phone/test', json={'request_id':'arbitrary','to_number':'+15551234567'}).status_code == 422
    assert c.get('/safety/events/..%2F..%2Fetc%2Fpasswd/clip').status_code == 404


def test_slow_worker_bounded_queue_hidden_disarm_and_replay_lock(client, monkeypatch):
    c, app = client
    detector = app.state.safety.detector
    detector.ready = True
    def slow(t, frame):
        time.sleep(.15)
        return Evidence(True, .99, True, 2), []
    monkeypatch.setattr(detector, 'process', slow)
    raw = base64.b64encode(cv2.imencode('.jpg', np.zeros((48,64,3),np.uint8))[1]).decode()
    s = session(c, 'replay')
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability':s['capability']}); receive_result(ws)
        h = {'X-Session-Capability':s['capability']}
        assert c.post(f'/safety/sessions/{s["id"]}/arm',json=arm_payload({'phone_mode':'real'}),headers=h).status_code == 403
        assert c.post(f'/safety/sessions/{s["id"]}/arm',json=arm_payload({'phone_mode':'dry_run'}),headers=h).status_code == 200
        for i in range(15):
            ws.send_json({'v':1,'session_id':s['id'],'frame_id':i,'captured_ms':time.monotonic()*1000,'jpeg':raw})
        result = receive_result(ws)
        assert result['dropped_frames'] > 0
        assert not app.state.safety.action_allowed(None, 'real')
        ws.send_json({'v':1,'type':'pause'})
        time.sleep(.05)
        assert not app.state.safety.session.policy.armed
        assert c.get('/safety/phone/actions').json()['items'] == []
    wait_closed(c, app)


def test_original_upload_persists_real_sqlite(client, monkeypatch):
    from backend.models import cnn_model
    from backend.services import face_detect
    from io import BytesIO
    from PIL import Image
    c, app = client
    class Cascade:
        def detectMultiScale(self, gray, **kwargs): return np.array([[2,3,40,40]])
    class Model:
        def predict(self, tensor, verbose=0): return np.array([[.1,.1,.6,.1,.1]])
    monkeypatch.setattr(face_detect, '_get_cascade', lambda: Cascade())
    monkeypatch.setattr(cnn_model, 'get_model', lambda: Model())
    output=BytesIO();Image.new('RGB',(64,64),'white').save(output,format='PNG')
    response=c.post('/predict',files={'image':('face.png',output.getvalue(),'image/png')})
    assert response.status_code == 200, response.text
    async def check():
        async with app.state.safety.factory() as db:
            prediction=await db.scalar(select(Prediction))
            assert prediction.id and prediction.all_scores['happy'] == .6
    c.portal.call(check)


@pytest.mark.parametrize('failure', ['jpeg', 'nan', 'backwards', 'gap'])
def test_malformed_or_unreliable_stream_disarms(client, monkeypatch, failure):
    c, app = client
    app.state.safety.detector.ready = True
    monkeypatch.setattr(app.state.safety.detector, 'process', lambda t,f:(Evidence(False), []))
    s=session(c)
    raw=base64.b64encode(cv2.imencode('.jpg',np.zeros((48,64,3),np.uint8))[1]).decode()
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream',headers=ORIGIN) as ws:
        ws.send_json({'capability':s['capability']});receive_result(ws)
        assert c.post(f'/safety/sessions/{s["id"]}/arm',json=arm_payload({}),headers={'X-Session-Capability':s['capability']}).status_code==200
        t=time.monotonic()*1000
        ws.send_json({'v':1,'session_id':s['id'],'frame_id':0,'captured_ms':t,'jpeg':raw});receive_result(ws)
        payload={'v':1,'session_id':s['id'],'frame_id':1,'captured_ms':t+100,'jpeg':raw}
        if failure=='jpeg':payload['jpeg']='invalid-base64'
        elif failure=='nan':payload['captured_ms']=float('nan')
        elif failure=='backwards':payload['captured_ms']=t-10
        else:payload['captured_ms']=t+2000
        ws.send_json(payload)
        if failure in ('jpeg','nan'):
            with pytest.raises(WebSocketDisconnect):receive_result(ws)
        else:
            assert receive_result(ws)['state']=='unavailable'
            assert not app.state.safety.session.policy.armed
    wait_closed(c, app)


def test_live_episode_persists_one_event_clip_and_dry_action(client, monkeypatch):
    c, app = client
    app.state.safety.detector.ready=True
    monkeypatch.setattr(app.state.safety.detector,'process',lambda t,f:(Evidence(True,.9,True,2,('Synthetic policy integration test',)), []))
    s=session(c)
    raw=base64.b64encode(cv2.imencode('.jpg',np.zeros((48,64,3),np.uint8))[1]).decode()
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream',headers=ORIGIN) as ws:
        ws.send_json({'capability':s['capability']});receive_result(ws)
        headers={'X-Session-Capability':s['capability']}
        assert c.post(f'/safety/sessions/{s["id"]}/arm',json=arm_payload({'phone_mode':'dry_run','clips':True}),headers=headers).status_code==200
        created=0;event_ids=set()
        for i in range(18):
            ws.send_json({'v':1,'session_id':s['id'],'frame_id':i,'captured_ms':time.monotonic()*1000,'jpeg':raw})
            result=receive_result(ws);created+=int(result.get('new_event',False))
            if result.get('event_id'):event_ids.add(result['event_id'])
            time.sleep(.1)
        assert created==1 and len(event_ids)==1
        assert c.post(f'/safety/sessions/{s["id"]}/disarm',json={},headers=headers).status_code==200
    wait_closed(c, app)
    async def wait_clip():
        for _ in range(100):
            async with app.state.safety.factory() as db:
                e=await db.get(Incident,next(iter(event_ids)))
                if e.clip_status=='partial':return
            await asyncio.sleep(.01)
        raise AssertionError('Clip was not finalized')
    c.portal.call(wait_clip)
    rows=c.get('/safety/events').json()['items'];assert len(rows)==1
    assert rows[0]['actions'][0]['state']=='dry_run'
    assert rows[0]['clip_status']=='partial'
    response=c.get(f'/safety/events/{rows[0]["id"]}/clip')
    assert response.status_code==200 and response.headers['content-type']=='video/webm'


def test_idle_stream_reports_server_disarm_without_new_frames(client):
    c, app = client
    app.state.safety.detector.ready = True
    s = session(c)
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability': s['capability']}); receive_result(ws)
        response = c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload({}), headers={'X-Session-Capability': s['capability']})
        generation = response.json()['generation']
        for _ in range(8):
            message = ws.receive_json()
            assert message['type'] == 'heartbeat'
            if message['state'] == 'disarmed':
                assert message['generation'] > generation
                assert 'Fresh frames stopped' in message['reason']
                break
        else:
            raise AssertionError('Server disarm was not delivered on the idle stream')


def test_uncertain_camera_evidence_does_not_cancel_explicit_phone_test(client, monkeypatch):
    c, app = client
    app.state.safety.detector.ready = True
    monkeypatch.setattr(app.state.safety.detector, 'process', lambda *_: (Evidence(False, reasons=('Occluded',)), []))
    s = session(c)
    raw = base64.b64encode(cv2.imencode('.jpg', np.zeros((48,64,3), np.uint8))[1]).decode()
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability': s['capability']}); receive_result(ws)
        c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload({}), headers={'X-Session-Capability': s['capability']})
        action = c.post('/safety/phone/test', json={'request_id': 'manual-with-camera'}).json()['action_id']
        ws.send_json({'v': 1, 'session_id': s['id'], 'frame_id': 0, 'captured_ms': time.monotonic()*1000, 'jpeg': raw})
        assert receive_result(ws)['tracking'] == 'insufficient_evidence'
        rows = c.get('/safety/phone/actions').json()['items']
        assert next(a for a in rows if a['id'] == action)['state'] == 'countdown'


def test_unusable_database_path_preserves_health_and_reports_storage(config, tmp_path):
    blocked = tmp_path/'blocked'
    blocked.write_text('preserve this existing file')
    cfg = config.model_copy(update={'DATABASE_URL': f'sqlite+aiosqlite:///{blocked}/local.db'})
    with TestClient(create_app(cfg), base_url='http://localhost') as c:
        health = c.get('/health')
        assert health.status_code == 200 and not health.json()['persistence']['ready']
        token = c.get('/safety/bootstrap', headers={'X-EmotionLens-Client': 'local-ui'}).json()['capability']
        c.headers['X-Safety-Capability'] = token
        assert c.get('/safety/status').status_code == 200
        response = c.get('/safety/events')
        assert response.status_code == 503 and 'Local storage unavailable' in response.json()['detail']
        assert str(blocked) not in response.text
        assert c.post('/safety/phone/test', json={'request_id': 'no-storage-test'}).status_code == 503
    assert blocked.read_text() == 'preserve this existing file'


def test_storage_read_failure_is_distinct_from_backend_disconnect(client, monkeypatch):
    from contextlib import asynccontextmanager
    from sqlalchemy.exc import OperationalError
    c, app = client
    @asynccontextmanager
    async def unavailable():
        raise OperationalError('read', {}, Exception('unavailable'))
        yield
    monkeypatch.setattr(app.state.safety, 'factory', unavailable)
    response = c.get('/safety/events')
    assert response.status_code == 503 and 'Local storage unavailable' in response.json()['detail']
    assert c.get('/health').status_code == 200
    assert not c.get('/safety/status').json()['persistence_ready']


def test_stale_first_frame_cannot_establish_a_false_fresh_clock(client, monkeypatch):
    c, app = client
    app.state.safety.detector.ready = True
    def unexpected(*args): raise AssertionError('Stale first frame reached inference')
    monkeypatch.setattr(app.state.safety.detector, 'process', unexpected)
    s = session(c)
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability': s['capability']}); receive_result(ws)
        headers = {'X-Session-Capability': s['capability']}
        assert c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload(), headers=headers).status_code == 200
        ws.send_json({'v': 1, 'session_id': s['id'], 'frame_id': 0, 'captured_ms': time.monotonic()*1000-2000, 'jpeg': 'unused'})
        result = receive_result(ws)
        assert result['state'] == 'unavailable' and 'Stale' in result['reason']


@pytest.mark.parametrize('options', [{'clips': True}, {'phone_mode': 'dry_run'}, {'phone_mode': 'real'}])
def test_live_only_sessions_reject_recording_and_phone_actions(client, options):
    c, app = client
    app.state.safety.detector.ready = True
    s = session(c, live_only=True)
    assert s['live_only'] is True
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability': s['capability']}); receive_result(ws)
        response = c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload(options),
                          headers={'X-Session-Capability': s['capability']})
        assert response.status_code == (403 if options.get('phone_mode') == 'real' else 409)
        assert not app.state.safety.session.policy.armed
    wait_closed(c, app)


def test_live_only_detects_two_episodes_without_history_writes_or_incident_cooldown(client, monkeypatch):
    c, app = client
    rt = app.state.safety
    rt.detector.ready = True
    rt.config.SAFETY_EVENT_ENTRY_SECONDS = .1
    rt.config.SAFETY_EVENT_QUIET_SECONDS = .2
    evidence = Evidence(True, .95, True, 2, ('Synthetic live-only test',), (1, 2))
    tracks = [{'id': i, 'box': [.1, .1, .4, .9], 'points': [[.2, .2, .9]]} for i in (1, 2)]
    monkeypatch.setattr(rt.detector, 'process', lambda t, f: (evidence, tracks))
    original_factory = rt.factory
    def forbidden_storage():
        raise AssertionError('Live-only capture must not access incident storage')
    monkeypatch.setattr(rt, 'factory', forbidden_storage)
    s = session(c, live_only=True)
    raw = base64.b64encode(cv2.imencode('.jpg', np.zeros((48, 64, 3), np.uint8))[1]).decode()
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability': s['capability']}); receive_result(ws)
        assert c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload(),
                      headers={'X-Session-Capability': s['capability']}).status_code == 200
        assert rt.session.policy.cooldown == 0
        created = 0
        for i in range(15):
            if i == 5: evidence = Evidence(True, 0, False, 2)
            if i == 10: evidence = Evidence(True, .95, True, 2, (), (2, 1))
            ws.send_json({'v': 1, 'session_id': s['id'], 'frame_id': i,
                          'captured_ms': time.monotonic()*1000, 'jpeg': raw})
            result = receive_result(ws)
            assert result['live_only'] is True and result['event_id'] is None
            assert result['people'] == 2
            created += int(result['new_event'])
            if result['new_event']:
                assert result['state'] == 'alert_active'
                assert result['interaction_track_ids'] == ([1, 2] if i < 5 else [2, 1])
            time.sleep(.1)
        assert created == 2
    wait_closed(c, app)
    async def check_empty():
        async with original_factory() as db:
            assert await db.scalar(select(Incident)) is None
            assert await db.scalar(select(Action)) is None
    c.portal.call(check_empty)


def enable_owner_calls(rt):
    from pydantic import SecretStr
    from test_actions import credentials, Provider
    credentials(rt.config)
    rt.config.SAFETY_CALL_MODE = 'real'
    rt.config.SAFETY_CALL_OWNER_KEY = SecretStr('owner-test-key')
    rt.detector.ready = True
    rt.dispatcher.provider = Provider()
    return {'X-Safety-Owner': 'owner-test-key'}


def test_automatic_calls_require_owner_live_session_and_acknowledgement(client):
    c, app = client
    rt = app.state.safety
    owner = enable_owner_calls(rt)
    assert c.get('/safety/status').json()['real_auto_calls_available']
    assert not c.get('/safety/status').json()['qualified']
    assert c.get('/safety/owner/status').status_code == 403
    assert c.get('/safety/owner/status', headers={'X-Safety-Owner': 'wrong'}).status_code == 403
    assert c.get('/safety/owner/status', headers=owner).status_code == 200
    assert 'owner-test-key' not in c.get('/safety/status').text
    for source, live_only in [('live', False), ('live', True), ('replay', False)]:
        s = session(c, source, live_only=live_only)
        h = {'X-Session-Capability': s['capability']}
        with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
            ws.send_json({'capability': s['capability']}); receive_result(ws)
            path = f'/safety/sessions/{s["id"]}/arm'
            options = arm_payload({'phone_mode': 'real', 'recipient_acknowledged': True})
            assert c.post(path, json=options, headers=h).status_code == 403
            assert c.post(path, json={**options, 'recipient_acknowledged': False}, headers={**h, **owner}).status_code == 409
            response = c.post(path, json=options, headers={**h, **owner})
            assert response.status_code == (200 if source == 'live' and not live_only else 409)
            if response.status_code == 200:
                assert rt.session.policy.entry_seconds == .3
                assert rt.session.call_policy.entry_seconds == 1.5
                assert c.get('/safety/status').json()['event_policy']['entry_seconds'] == .3
            rt.config.SAFETY_CALL_MODE = 'off'
            assert c.post(path, json=options, headers={**h, **owner}).status_code == 409
            rt.config.SAFETY_CALL_MODE = 'real'
        wait_closed(c, app)
    assert rt.dispatcher.provider.calls == 0


@pytest.mark.parametrize('outcome', ['dispatch', 'cancel', 'pause', 'tracking_loss', 'disable'])
def test_one_point_five_second_owner_call_end_to_end_with_mock_provider(client, monkeypatch, outcome):
    c, app = client
    rt = app.state.safety
    owner = enable_owner_calls(rt)
    clock = [1000.]
    rt.dispatcher.clock = lambda: clock[0]
    evidence = Evidence(True, .95, True, 2, ('Synthetic owner-call test',), (1, 2))
    monkeypatch.setattr(rt.detector, 'process', lambda t, f: (evidence, []))
    s = session(c)
    h = {**owner, 'X-Session-Capability': s['capability']}
    raw = base64.b64encode(cv2.imencode('.jpg', np.zeros((48, 64, 3), np.uint8))[1]).decode()
    path = f'/safety/sessions/{s["id"]}/phone-actions'
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability': s['capability']}); receive_result(ws)
        assert c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload({'phone_mode': 'real', 'recipient_acknowledged': True}), headers=h).status_code == 200
        assert c.get(path, headers=owner).status_code == 403
        assert c.get(path, headers={'X-Session-Capability': s['capability']}).status_code == 403
        started = time.monotonic()
        first_capture = None
        created = 0
        for i in range(36):
            captured = time.monotonic()
            if first_capture is None: first_capture = captured
            ws.send_json({'v': 1, 'session_id': s['id'], 'frame_id': i, 'captured_ms': captured * 1000, 'jpeg': raw})
            result = receive_result(ws)
            if captured - first_capture < .3:
                assert not result.get('new_event')
            if captured - first_capture < 1.5:
                assert not c.get(path, headers=h).json()['items']
            created += bool(result.get('new_event'))
            if c.get(path, headers=h).json()['items']: break
            time.sleep(.1)
        assert created == 1 and time.monotonic() - started >= 1.5
        actions = c.get(path, headers=h).json()['items']
        assert len(actions) == 1 and actions[0]['state'] == 'countdown'
        assert rt.dispatcher.provider.calls == 0
        aid = actions[0]['id']
        if outcome == 'cancel':
            assert c.post(f'{path}/{aid}/cancel', headers=h).status_code == 200
        elif outcome == 'pause':
            assert c.post(f'/safety/sessions/{s["id"]}/disarm', headers=h).status_code == 200
        elif outcome == 'tracking_loss':
            evidence = Evidence(False)
            ws.send_json({'v': 1, 'session_id': s['id'], 'frame_id': 100, 'captured_ms': time.monotonic()*1000, 'jpeg': raw})
            receive_result(ws)
        elif outcome == 'disable':
            rt.config.SAFETY_CALL_MODE = 'off'
        clock[0] += 1
        c.portal.call(rt.dispatcher.tick)
        assert rt.dispatcher.provider.calls == (1 if outcome == 'dispatch' else 0)
        actions = c.get(path, headers=h).json()['items']
        assert actions[0]['state'] == ('submitted' if outcome == 'dispatch' else 'cancelled')
        c.portal.call(rt.dispatcher.tick)
        assert rt.dispatcher.provider.calls == (1 if outcome == 'dispatch' else 0)
    wait_closed(c, app)


def test_short_hit_still_alerts_with_owner_calls_without_scheduling_a_call(client, monkeypatch):
    c, app = client
    rt = app.state.safety
    owner = enable_owner_calls(rt)
    evidence = Evidence(True, .95, True, 2, (), (1, 2))
    monkeypatch.setattr(rt.detector, 'process', lambda t, f: (evidence, []))
    s = session(c)
    h = {**owner, 'X-Session-Capability': s['capability']}
    raw = base64.b64encode(cv2.imencode('.jpg', np.zeros((48, 64, 3), np.uint8))[1]).decode()
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability': s['capability']}); receive_result(ws)
        assert c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload({'phone_mode': 'real', 'recipient_acknowledged': True}), headers=h).status_code == 200
        alerts = 0
        for i in range(12):
            if i == 6: evidence = Evidence(True, .1, False, 2)
            ws.send_json({'v': 1, 'session_id': s['id'], 'frame_id': i, 'captured_ms': time.monotonic()*1000, 'jpeg': raw})
            result = receive_result(ws)
            alerts += bool(result.get('new_event'))
            time.sleep(.1)
        assert alerts == 1
        assert c.get(f'/safety/sessions/{s["id"]}/phone-actions', headers=h).json()['items'] == []
        assert rt.dispatcher.provider.calls == 0
    wait_closed(c, app)


def test_demo_starts_real_calls_without_owner_code_and_keeps_session_capability(client):
    from pydantic import SecretStr
    c, app = client
    rt = app.state.safety
    enable_owner_calls(rt)
    rt.config.SAFETY_DEMO_AUTO_CALLS = True
    rt.config.SAFETY_CALL_OWNER_KEY = SecretStr('')
    status = c.get('/safety/status').json()
    assert status['demo_auto_calls'] and status['real_auto_calls_available']
    assert c.get('/safety/owner/status').status_code == 200
    s = session(c)
    h = {'X-Session-Capability': s['capability']}
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability': s['capability']}); receive_result(ws)
        response = c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload({'phone_mode': 'real', 'recipient_acknowledged': True}), headers=h)
        assert response.status_code == 200
        assert rt.session.phone_mode == 'real' and rt.session.phone_authorized
        assert c.get('/safety/status').json()['live_diagnostics']['phone_mode'] == 'real'
        path = f'/safety/sessions/{s["id"]}/phone-actions'
        assert c.get(path).status_code == 403
        assert c.get(path, headers=h).status_code == 200
        assert rt.dispatcher.provider.calls == 0
    wait_closed(c, app)


def test_faster_websocket_than_arm_http_does_not_pause_fresh_video(client, monkeypatch):
    c, app = client
    rt = app.state.safety
    rt.detector.ready = True
    monkeypatch.setattr(rt.detector, 'process', lambda t, f: (Evidence(True, .1, False, 2), []))
    s = session(c)
    raw = base64.b64encode(cv2.imencode('.jpg', np.zeros((48, 64, 3), np.uint8))[1]).decode()
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream', headers=ORIGIN) as ws:
        ws.send_json({'capability': s['capability']}); receive_result(ws)
        assert c.post(f'/safety/sessions/{s["id"]}/arm', json=arm_payload(), headers={'X-Session-Capability': s['capability']}).status_code == 200
        # Reproduce an arm HTTP request taking 600 ms longer than video upload.
        rt.session.clock_offset += .6
        for i in range(3):
            ws.send_json({'v': 1, 'session_id': s['id'], 'frame_id': i, 'captured_ms': time.monotonic()*1000, 'jpeg': raw})
            result = receive_result(ws)
            assert result['state'] not in ('unavailable', 'disarmed')
            assert result['tracking'] == 'observed'
            assert rt.session.policy.armed
            time.sleep(.05)
    wait_closed(c, app)


def test_replacing_adjacent_queued_frames_preserves_action_history(client, monkeypatch):
    c, app = client
    rt = app.state.safety
    rt.detector.ready = True
    def process(t, f):
        time.sleep(.05)
        return Evidence(True, .1, False, 2), []
    monkeypatch.setattr(rt.detector, 'process', process)
    s = session(c, live_only=True)
    raw = base64.b64encode(cv2.imencode('.jpg', np.zeros((48,64,3),np.uint8))[1]).decode()
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream',headers=ORIGIN) as ws:
        ws.send_json({'capability':s['capability']});receive_result(ws)
        assert c.post(f'/safety/sessions/{s["id"]}/arm',json=arm_payload(),headers={'X-Session-Capability':s['capability']}).status_code==200
        ws.send_json({'v':1,'session_id':s['id'],'frame_id':0,'captured_ms':time.monotonic()*1000,'jpeg':raw});receive_result(ws)
        resets=[]
        monkeypatch.setattr(rt.detector,'reset',lambda:resets.append(1))
        for i in range(1,9):
            ws.send_json({'v':1,'session_id':s['id'],'frame_id':i,'captured_ms':time.monotonic()*1000,'jpeg':raw})
        for _ in range(9):
            result=receive_result(ws)
            if result.get('frame_id')==8:break
        else:raise AssertionError('Newest queued frame was not processed')
        assert result['dropped_frames']>0 and resets==[]
        assert rt.session.policy.armed
    wait_closed(c,app)


def test_demo_waits_for_arm_response_before_first_video_frame(client, monkeypatch):
    c, app = client
    rt=app.state.safety
    rt.config.SAFETY_DEMO_AUTO_CALLS=True
    rt.detector.ready=True
    monkeypatch.setattr(rt.detector,'process',lambda t,f:(Evidence(True,.1,False,2),[]))
    s=session(c,live_only=True)
    raw=base64.b64encode(cv2.imencode('.jpg',np.zeros((48,64,3),np.uint8))[1]).decode()
    with c.websocket_connect(f'/safety/sessions/{s["id"]}/stream',headers=ORIGIN) as ws:
        ws.send_json({'capability':s['capability']});receive_result(ws)
        assert c.post(f'/safety/sessions/{s["id"]}/arm',json=arm_payload(),headers={'X-Session-Capability':s['capability']}).status_code==200
        time.sleep(1.3)
        assert rt.session.policy.armed
        ws.send_json({'v':1,'session_id':s['id'],'frame_id':0,'captured_ms':time.monotonic()*1000,'jpeg':raw})
        result=receive_result(ws)
        assert result['state'] not in ('disarmed','unavailable') and result['tracking']=='observed'
    wait_closed(c,app)


def test_demo_start_replaces_old_session_and_cancels_pending_actions(client):
    c,app=client
    rt=app.state.safety
    rt.config.SAFETY_DEMO_AUTO_CALLS=True
    old=session(c)
    action=c.post('/safety/phone/test',json={'request_id':'replace-demo-pending'}).json()['action_id']
    new=c.post('/safety/sessions',json={'source':'live','replace_existing':True})
    assert new.status_code==201 and new.json()['id']!=old['id']
    assert rt.session.id==new.json()['id']
    actions=c.get('/safety/phone/actions').json()['items']
    assert next(a for a in actions if a['id']==action)['state']=='cancelled'
    # A late close from the old tab cannot stop its replacement.
    assert c.delete(f'/safety/sessions/{old["id"]}',headers={'X-Session-Capability':old['capability']}).status_code==200
    assert rt.session.id==new.json()['id']


def test_session_replacement_is_not_implicitly_enabled_outside_demo(client):
    c,app=client
    old=session(c)
    r=c.post('/safety/sessions',json={'replace_existing':True})
    assert r.status_code==409 and app.state.safety.session.id==old['id']
