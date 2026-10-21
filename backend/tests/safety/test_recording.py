import uuid
import cv2
import numpy as np
import pytest
from backend.safety.recording import RecordingStore
from backend.safety.frame_buffer import decode_frame, FrameBuffer
from backend.safety.models import Incident, Action
from backend.safety.retention import cleanup


def jpeg():
    return cv2.imencode('.jpg', np.zeros((48, 64, 3), np.uint8))[1].tobytes()


def test_limits_and_bounded_buffer():
    import base64
    assert decode_frame(base64.b64encode(jpeg()).decode())[1].shape == (48, 64, 3)
    for raw in [b'garbage', b'x' * (512 * 1024 + 1), cv2.imencode('.jpg', np.zeros((480, 641, 3), np.uint8))[1].tobytes()]:
        with pytest.raises(ValueError): decode_frame(base64.b64encode(raw).decode())
    with pytest.raises(ValueError): decode_frame('!invalidbase64')
    b = FrameBuffer()
    for i in range(18000): b.append(i / 10, jpeg())
    assert len(b.frames) <= 60 and b.frames[-1][0] - b.frames[0][0] <= 5


def test_webm_partial_quota_and_path_escape(config, tmp_path):
    store = RecordingStore(config)
    assert store.available, store.reason
    name, status, details = store.encode(str(uuid.uuid4()), [(i / 10, jpeg()) for i in range(10)], partial=True)
    assert status == 'partial' and details['audio'] is False
    cap = cv2.VideoCapture(str(store.path(name)))
    assert cap.read()[0]; cap.release()
    for path in ['../outside.webm', '/tmp/outside.webm']:
        with pytest.raises(ValueError): store.path(path)
    outside = tmp_path / 'outside.webm'; outside.write_bytes(b'keep')
    (store.directory / 'escape.webm').symlink_to(outside)
    with pytest.raises(ValueError): store.delete('escape.webm')
    assert outside.read_bytes() == b'keep'
    store.quota = 1
    assert store.encode(str(uuid.uuid4()), [(0, jpeg())])[1] == 'quota_exceeded'
    store.delete(name)
    assert not store.path(name).exists()


@pytest.mark.asyncio
async def test_retention_keeps_quota_records(factory, config):
    store = RecordingStore(config)
    eid = str(uuid.uuid4())
    name, _, _ = store.encode(eid, [(i / 10, jpeg()) for i in range(3)])
    async with factory() as db:
        db.add(Incident(id=eid, session_id='test', captured_at=0, created_at=10, model_version='test', score=.9, clip_name=name, clip_status='ready'))
        await db.commit()
        db.add(Action(id='action', event_id=eid, dedup_key='deleted', mode='real', state='submitted', created_at=8 * 86400, attempt_at=8 * 86400, due_at=8 * 86400))
        await db.commit()
    await cleanup(factory, store, config, now=8 * 86400)
    async with factory() as db:
        assert await db.get(Incident, eid) is None
        assert (await db.get(Action, 'action')).event_id is None
    assert not store.path(name).exists()
