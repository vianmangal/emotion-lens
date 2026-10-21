import asyncio
import threading
import time
import pytest
from sqlalchemy.exc import OperationalError
from backend.routers.safety import delete_event
from backend.safety.models import Incident, new_id
from backend.safety.sessions import Runtime
from backend.safety.schemas import ArmOptions
from test_recording import jpeg


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['arm', 'disarm', 'end'])
async def test_delayed_control_cannot_change_replacement_session(factory, config, operation):
    rt = Runtime(config, factory)
    await rt.start()
    try:
        rt.detector.ready = True
        old = await rt.create('live'); old.connected = True
        await rt.control_lock.acquire()
        if operation == 'arm':
            pending = asyncio.create_task(rt.arm(ArmOptions(), expected_session=old))
        else:
            pending = asyncio.create_task(getattr(rt, operation)(expected_session=old))
        await asyncio.sleep(0)
        await rt._end()
        current = await rt.create('live'); current.connected = True; current.policy.arm()
        rt.control_lock.release()
        if operation == 'arm':
            with pytest.raises(ValueError, match='Session changed'): await pending
        else:
            assert await pending is False
        assert rt.session is current and current.policy.armed
    finally:
        if rt.control_lock.locked(): rt.control_lock.release()
        await rt.close()


@pytest.mark.asyncio
async def test_storage_failure_cannot_prevent_camera_session_cleanup(factory, config, monkeypatch):
    rt = Runtime(config, factory)
    await rt.start()
    try:
        s = await rt.create('live'); s.connected = True; s.policy.arm()
        s.buffer.append(0, jpeg())
        async def fail(**kwargs): raise OperationalError('write', {}, Exception('disk unavailable'))
        monkeypatch.setattr(rt.dispatcher, 'cancel', fail)
        await rt.end(expected_session=s)
        assert rt.session is None and not s.policy.armed and not s.connected
        assert not s.buffer.frames
        assert 'Storage unavailable' in rt.storage_warning
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_deletion_waits_for_encoder_and_removes_completed_file(factory, config, monkeypatch):
    rt = Runtime(config, factory)
    await rt.start()
    release = threading.Event(); written = threading.Event()
    eid = new_id()
    async with factory() as db:
        db.add(Incident(id=eid, session_id='test', captured_at=0, model_version='test', score=.9, clip_status='buffering'))
        await db.commit()
    original = rt.store.encode
    def delayed_encode(*args):
        result = original(*args)
        written.set()
        if not release.wait(5): raise AssertionError('Encode was not released')
        return result
    monkeypatch.setattr(rt.store, 'encode', delayed_encode)
    encode = asyncio.create_task(rt.encode(eid, [(i/10, jpeg()) for i in range(5)], False, .2))
    try:
        assert await asyncio.to_thread(written.wait, 5)
        deletion = asyncio.create_task(delete_event(eid, rt))
        await asyncio.sleep(.02)
        assert not deletion.done()
        release.set()
        await encode
        await deletion
        async with factory() as db: assert await db.get(Incident, eid) is None
        assert not list(rt.store.directory.glob('*.webm'))
    finally:
        release.set()
        await asyncio.gather(encode, return_exceptions=True)
        await rt.close()


@pytest.mark.asyncio
async def test_queued_encoding_does_not_write_after_incident_deletion(factory, config, monkeypatch):
    rt = Runtime(config, factory)
    await rt.start()
    eid = new_id()
    try:
        s = await rt.create('live')
        s.recording_id = eid
        s.recording = [(0, jpeg())]
        async with factory() as db:
            db.add(Incident(id=eid, session_id=s.id, captured_at=0, model_version='test', score=.9, clip_status='buffering'))
            await db.commit()
        await delete_event(eid, rt)
        def unexpected(*args): raise AssertionError('Deleted incident must not be encoded')
        monkeypatch.setattr(rt.store, 'encode', unexpected)
        await rt.encode(eid, [(0, jpeg())], True, 0)
        assert s.recording_id is None and not s.recording
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_old_decoded_frame_cannot_repopulate_new_session_tracker(factory, config, monkeypatch):
    import numpy as np
    from backend.safety.frame_buffer import decode_frame
    from backend.safety.schemas import FrameMessage
    rt = Runtime(config, factory)
    await rt.start()
    entered, release = asyncio.Event(), asyncio.Event()
    original = rt.work
    async def work(fn, *args):
        if fn is decode_frame:
            entered.set(); await release.wait()
            return jpeg(), np.zeros((48, 64, 3), np.uint8)
        return await original(fn, *args)
    monkeypatch.setattr(rt, 'work', work)
    def unexpected(*args): raise AssertionError('Old frame reached the replacement tracker')
    monkeypatch.setattr(rt.detector, 'process', unexpected)
    try:
        old = await rt.create('live'); old.connected = True; old.policy.arm(); old.clock_offset = 0
        frame = FrameMessage(v=1, session_id=old.id, frame_id=0, captured_ms=time.monotonic()*1000, jpeg='unused')
        pending = asyncio.create_task(rt.process(old, frame, time.monotonic()))
        await entered.wait()
        await rt.end(expected_session=old)
        current = await rt.create('live'); current.connected = True; current.policy.arm()
        release.set()
        assert (await pending)['state'] == 'disarmed'
        assert rt.session is current and current.policy.armed
    finally:
        release.set()
        await rt.close()


@pytest.mark.asyncio
async def test_background_dispatch_storage_failure_stops_further_attempts(factory, config, monkeypatch):
    rt = Runtime(config, factory)
    await rt.start()
    attempted = asyncio.Event()
    calls = []
    async def fail():
        calls.append(1); attempted.set()
        raise OperationalError('claim', {}, Exception('disk full'))
    monkeypatch.setattr(rt.dispatcher, 'tick', fail)
    try:
        await asyncio.wait_for(attempted.wait(), 2)
        assert not rt.persistence_ready and 'dispatch paused' in rt.storage_warning
        await asyncio.sleep(.3)
        assert len(calls) == 1
    finally:
        await rt.close()
