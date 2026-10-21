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


def session(c, source='live'):
    r = c.post('/safety/sessions', json={'source': source})
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
        assert c.post(f'/safety/sessions/{s["id"]}/arm',json=arm_payload({'phone_mode':'real'}),headers=h).status_code == 409
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
