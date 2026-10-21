import asyncio
import anyio
import json
import secrets
import time
from fastapi import APIRouter, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select, func
from backend.safety.schemas import SessionOptions, ArmOptions, FrameMessage, Review, PhoneTest
from backend.safety.frame_buffer import MAX_MESSAGE
from backend.safety.models import Incident, Action
from backend.safety.actions.elevenlabs import configured

router = APIRouter(prefix='/safety', tags=['safety'])


def runtime(request: Request):
    return request.app.state.safety


def authorized(request: Request):
    rt = runtime(request)
    if not secrets.compare_digest(request.headers.get('x-safety-capability', ''), rt.capability):
        raise HTTPException(403, 'Local capability required; reload the approved local UI')
    return rt


def get_session(rt, session_id, capability):
    s = rt.session
    if not s or s.id != session_id:
        raise HTTPException(404, 'Session not found')
    if time.monotonic() > s.expires:
        raise HTTPException(403, 'Session expired; stop and restart camera')
    if not secrets.compare_digest(capability, s.capability):
        raise HTTPException(403, 'Session capability required')
    return s


@router.get('/bootstrap')
async def bootstrap(request: Request):
    # Custom header cannot be added by a cross-origin browser without an approved preflight.
    if request.headers.get('x-emotionlens-client') != 'local-ui':
        raise HTTPException(403, 'Open the approved local frontend')
    return {'capability': runtime(request).capability, 'v': 1}


@router.get('/status')
async def status(rt=Depends(authorized)):
    return rt.status()


@router.post('/sessions', status_code=201)
async def create_session(options: SessionOptions, rt=Depends(authorized)):
    async with rt.control_lock:
        try:
            s = await rt.create(options.source)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    return {'id': s.id, 'capability': s.capability, 'expires_in_seconds': rt.config.SAFETY_SESSION_TTL_SECONDS, 'source': s.source}


@router.post('/sessions/{session_id}/arm')
async def arm(session_id: str, options: ArmOptions, request: Request, rt=Depends(authorized)):
    s = get_session(rt, session_id, request.headers.get('x-session-capability', ''))
    try:
        await rt.arm(options, expected_session=s)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'state': s.policy.state, 'generation': s.generation}


@router.post('/sessions/{session_id}/disarm')
async def disarm(session_id: str, request: Request, rt=Depends(authorized)):
    s = get_session(rt, session_id, request.headers.get('x-session-capability', ''))
    await rt.disarm(expected_session=s)
    return {'state': 'disarmed'}


@router.delete('/sessions/{session_id}')
async def end_session(session_id: str, request: Request, rt=Depends(authorized)):
    # Expired sessions can still be ended by their owner.
    s = rt.session
    if s and s.id == session_id and secrets.compare_digest(request.headers.get('x-session-capability', ''), s.capability):
        await rt.end(expected_session=s)
    return {'state': 'disarmed'}


@router.websocket('/sessions/{session_id}/stream')
async def stream(ws: WebSocket, session_id: str):
    rt = ws.app.state.safety
    if ws.headers.get('origin') not in rt.config.CORS_ALLOW_ORIGINS:
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        # Capability is in the first message, never in a URL/access log.
        auth_raw = await asyncio.wait_for(ws.receive_text(), timeout=5)
        if len(auth_raw) > 1024:
            raise ValueError('Authentication payload too large')
        auth = json.loads(auth_raw)
        if not isinstance(auth, dict) or set(auth) != {'capability'}:
            raise ValueError('Invalid authentication')
        s = get_session(rt, session_id, str(auth['capability']))
        if s.connected:
            raise ValueError('Session already connected')
        s.connected = True
        s.last_frame = time.monotonic()
        await ws.send_json({'v': 1, 'type': 'connected', 'state': 'disarmed', 'source': s.source})
    except (ValueError, HTTPException, asyncio.TimeoutError, WebSocketDisconnect, TypeError):
        await ws.close(code=1008)
        return
    queue = asyncio.Queue(maxsize=1)
    dropped = False
    send_lock = asyncio.Lock()

    async def send(payload):
        async with send_lock:
            await ws.send_json(payload)

    async def receive():
        nonlocal dropped
        while True:
            raw = await ws.receive_text()
            if len(raw.encode('utf-8')) > MAX_MESSAGE:
                raise ValueError('WebSocket message exceeds 1 MiB')
            if time.monotonic() > s.expires or s is not rt.session:
                raise ValueError('Session expired or closed')
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload == {'v': 1, 'type': 'pause'}:
                await rt.disarm('Browser hidden or capture paused; explicitly re-arm', expected_session=s)
                continue
            frame = FrameMessage.model_validate(payload)
            if frame.session_id != s.id or frame.frame_id <= s.last_id:
                raise ValueError('Session mismatch or non-increasing frame ID')
            if time.monotonic() > s.expires or s is not rt.session:
                raise ValueError('Session expired or closed')
            s.last_id = frame.frame_id
            if not s.policy.armed:
                continue
            s.last_frame = time.monotonic()
            if queue.full():
                queue.get_nowait()
                dropped = True
                s.dropped += 1
                s.last_evidence = None
            queue.put_nowait((frame, s.last_frame, s.generation))

    async def process():
        nonlocal dropped
        while True:
            frame, received_at, generation = await queue.get()
            if generation != s.generation:
                continue
            was_dropped, dropped = dropped, False
            result = await rt.process(s, frame, received_at, was_dropped)
            await send({**result, 'generation': generation})

    async def heartbeat():
        while True:
            await asyncio.sleep(.5)
            if s is not rt.session:
                return
            await send({'v': 1, 'type': 'heartbeat', 'session_id': s.id,
                        'state': s.policy.state, 'reason': s.reason, 'generation': s.generation})

    tasks = [asyncio.create_task(receive()), asyncio.create_task(process()), asyncio.create_task(heartbeat())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, RuntimeError, ValueError, ValidationError):
        pass
    finally:
        with anyio.CancelScope(shield=True):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if rt.session is s:
                await rt.end(expected_session=s)
            try:
                await ws.close(code=1000)
            except RuntimeError:
                pass

def action_json(action):
    return {**{k: getattr(action, k) for k in ('id', 'mode', 'state', 'due_at', 'attempt_at', 'recipient_alias', 'error_category')},
            'preview': action.provider_ids.get('dry_run_payload') if action.mode == 'dry_run' else None}


def event_json(event):
    return {k: getattr(event, k) for k in ('id', 'session_id', 'created_at', 'updated_at', 'captured_at', 'event_type', 'status', 'model_version', 'score', 'threshold_version', 'reasons', 'track_ids', 'review_label', 'source', 'clip_status', 'clip_details')}


@router.get('/events')
async def events(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), rt=Depends(authorized)):
    async with rt.factory() as db:
        rows = (await db.scalars(select(Incident).order_by(Incident.created_at.desc()).offset(offset).limit(limit))).all()
        actions = (await db.scalars(select(Action).where(Action.event_id.in_([e.id for e in rows])))).all() if rows else []
        count = await db.scalar(select(func.count()).select_from(Incident))
    return {'items': [{**event_json(e), 'actions': [action_json(a) for a in actions if a.event_id == e.id]} for e in rows], 'total': count, 'offset': offset, 'limit': limit}


@router.patch('/events/{event_id}')
async def review(event_id: str, body: Review, rt=Depends(authorized)):
    async with rt.factory() as db:
        e = await db.get(Incident, event_id)
        if not e:
            raise HTTPException(404, 'Incident not found')
        e.review_label = body.label
        await db.commit()
        return event_json(e)


@router.get('/events/{event_id}/clip')
async def clip(event_id: str, rt=Depends(authorized)):
    async with rt.factory() as db:
        e = await db.get(Incident, event_id)
        if not e or not e.clip_name:
            raise HTTPException(404, 'Clip unavailable or expired')
        try:
            path = rt.store.path(e.clip_name)
            if not path.is_file():
                raise ValueError('Missing clip')
        except (ValueError, OSError):
            raise HTTPException(404, 'Clip unavailable')
    return FileResponse(path, media_type='video/webm', filename=f'incident-{event_id}.webm')


@router.delete('/events/{event_id}')
async def delete_event(event_id: str, rt=Depends(authorized)):
    await rt.dispatcher.cancel(event_id=event_id, reason='event_deleted')
    async with rt.control_lock:
        s = rt.session
        if s and s.recording_id == event_id:
            s.recording_id = None
            s.recording = []
            s.recording_bytes = 0
    # Share the encoder's lock: a completed encode cannot commit a clip reference
    # after deletion has already removed the corresponding incident.
    async with rt.clip_lock:
        async with rt.factory() as db:
            e = await db.get(Incident, event_id)
            if not e:
                raise HTTPException(404, 'Incident not found')
            try:
                await asyncio.to_thread(rt.store.delete, e.clip_name)
            except (OSError, ValueError):
                raise HTTPException(409, 'Clip deletion failed; metadata retained to retry')
            await db.delete(e)
            await db.commit()
    return {'deleted': True, 'call_note': 'Submitted calls cannot be recalled; quota records are retained'}


@router.post('/events/{event_id}/actions/cancel')
async def cancel_event(event_id: str, rt=Depends(authorized)):
    await rt.dispatcher.cancel(event_id=event_id)
    return {'message': 'Pending calls cancelled. Submitted calls cannot be recalled.'}


@router.get('/phone/actions')
async def phone_actions(rt=Depends(authorized)):
    async with rt.factory() as db:
        rows = (await db.scalars(select(Action).order_by(Action.created_at.desc()).limit(30))).all()
        return {'items': [action_json(a) for a in rows]}


@router.post('/phone/actions/{action_id}/cancel')
async def cancel_phone(action_id: str, rt=Depends(authorized)):
    await rt.dispatcher.cancel(action_id=action_id)
    return {'message': 'Pending call cancelled. Submitted calls cannot be recalled.'}


@router.post('/phone/test', status_code=202)
async def phone_test(options: PhoneTest, rt=Depends(authorized)):
    if not rt.persistence_ready:
        raise HTTPException(503, 'Phone actions require writable local storage. Check disk space/permissions and restart.')
    if options.mode == 'real' and (not options.recipient_acknowledged or not configured(rt.config)):
        raise HTTPException(409, 'Real test requires configured recipient and explicit acknowledgement of consent and charges')
    return {'action_id': await rt.dispatcher.enqueue(options.mode, request_id=options.request_id), 'state': 'countdown'}
