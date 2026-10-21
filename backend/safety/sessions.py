import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import secrets
import time
from collections import deque
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from backend.safety.detector import Detector
from backend.safety.event_policy import EventPolicy
from backend.safety.frame_buffer import FrameBuffer, decode_frame
from backend.safety.recording import RecordingStore
from backend.safety.models import Incident, new_id
from backend.safety.actions.dispatcher import Dispatcher
from backend.safety.actions.elevenlabs import configured, masked_recipient
from backend.safety.retention import cleanup


@dataclass
class Session:
    id: str = field(default_factory=new_id)
    capability: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    source: str = 'live'
    created_monotonic: float = field(default_factory=time.monotonic)
    expires: float = field(default_factory=lambda: time.monotonic() + 1800)
    policy: EventPolicy = field(default_factory=EventPolicy)
    connected: bool = False
    phone_mode: str = 'off'
    clips: bool = False
    last_frame: float = 0
    last_capture: float = -1
    last_id: int = -1
    clock_offset: float | None = None
    last_evidence: object = None
    evidence_at: float = 0
    dropped: int = 0
    generation: int = 0
    event_id: str | None = None
    reason: str = 'Disarmed'
    buffer: FrameBuffer = field(default_factory=FrameBuffer)
    recording: list = field(default_factory=list)
    recording_id: str | None = None
    recording_until: float = 0
    recording_bytes: int = 0
    recording_trigger: float = 0
    recording_truncated: bool = False


class Runtime:
    def __init__(self, config, factory):
        self.config, self.factory = config, factory
        self.capability = secrets.token_urlsafe(32)
        self.session = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ordered-safety-inference')
        self.detector = None
        self.store = None
        self.dispatcher = Dispatcher(factory, config, self.action_allowed)
        self.tasks = set()
        self.clip_lock = asyncio.Lock()
        self.control_lock = asyncio.Lock()
        self.storage_warning = None

    async def work(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, fn, *args)

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        def completed(task):
            self.tasks.discard(task)
            if not task.cancelled() and task.exception():
                self.storage_warning = 'Clip storage failed; detection continues. Check local disk.'
        task.add_done_callback(completed)
        return task

    async def start(self):
        self.detector = await self.work(Detector, self.config)
        self.store = await asyncio.to_thread(RecordingStore, self.config)
        await self.dispatcher.recover()
        try:
            await cleanup(self.factory, self.store, self.config)
        except (OSError, SQLAlchemyError):
            self.storage_warning = 'Storage cleanup failed; check local disk'
        self.maintenance = asyncio.create_task(self.maintain())
        self.call_worker = asyncio.create_task(self.calls())

    async def close(self):
        await self.end()
        self.maintenance.cancel()
        self.call_worker.cancel()
        await asyncio.gather(self.maintenance, self.call_worker, return_exceptions=True)
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.work(self.detector.close)
        self.executor.shutdown(wait=True)

    def status(self):
        s = self.session
        return {'v': 1, 'ready': self.detector.ready, 'qualified': self.detector.qualified,
                'model': self.detector.temporal.version, 'reason': self.detector.reason,
                'state': s.policy.state if s else 'disarmed', 'recording_available': self.store.available,
                'recording_reason': self.store.reason, 'storage_bytes': self.store.usage(),
                'storage_quota_bytes': self.store.quota, 'storage_warning': self.storage_warning,
                'clip_retention_hours': self.config.SAFETY_CLIP_RETENTION_HOURS,
                'metadata_retention_days': self.config.SAFETY_METADATA_RETENTION_DAYS, 'phone_configured': configured(self.config),
                'recipient': masked_recipient(self.config), 'real_auto_calls_available': False,
                'real_test_available': configured(self.config), 'call_grace_seconds': self.config.SAFETY_CALL_GRACE_SECONDS}

    async def create(self, source):
        if self.session:
            raise ValueError('A camera session is already active. Stop it first.')
        await self.work(self.detector.reset)
        self.session = Session(source=source)
        return self.session

    async def disarm(self, reason='Disarmed'):
        async with self.control_lock:
            await self._disarm(reason)

    async def _disarm(self, reason='Disarmed'):
        s = self.session
        if not s:
            return
        s.generation += 1
        s.policy.disarm()
        s.phone_mode = 'off'
        s.last_evidence = None
        s.reason = reason
        s.buffer.clear()
        await self.dispatcher.cancel(reason=reason)
        if s.event_id:
            async with self.factory() as db:
                event = await db.get(Incident, s.event_id)
                if event:
                    event.status = 'interrupted'
                    await db.commit()
            s.event_id = None
        self.finalize(s, partial=True)
        await self.work(self.detector.reset)

    async def end(self):
        async with self.control_lock:
            await self._end()

    async def _end(self):
        s = self.session
        if s:
            await self._disarm('Camera stopped or disconnected')
            s.connected = False
            self.session = None

    async def arm(self, options):
        async with self.control_lock:
            await self._arm(options)

    async def _arm(self, options):
        s = self.session
        if not s or not s.connected:
            raise ValueError('Start the camera stream first')
        if not self.detector.ready:
            raise ValueError(self.detector.reason)
        if options.phone_mode == 'real':
            raise ValueError('Automatic real calls are locked: detector qualification is unmet. Use dry run or an explicit phone test.')
        if options.clips and not self.store.available:
            raise ValueError(self.store.reason)
        await self._disarm()
        s.last_frame = time.monotonic()
        s.phone_mode, s.clips = options.phone_mode, options.clips
        s.policy.arm()
        s.reason = 'Warming temporal window'
        s.last_capture = -1
        s.last_evidence = None
        s.clock_offset = None

    def action_allowed(self, event, mode):
        s = self.session
        if not (s and event and event.session_id == s.id and s.connected and s.policy.armed and s.source == 'live' and s.phone_mode == mode and time.monotonic() - s.last_frame < 1 and time.monotonic() - s.evidence_at < 1 and s.last_evidence and s.last_evidence.ready and s.last_evidence.people >= 2):
            return False
        return mode == 'dry_run' or self.detector.qualified

    def finalize(self, s, partial=False):
        if s.recording_id:
            frames, event_id = s.recording, s.recording_id
            s.recording, s.recording_id, s.recording_bytes = [], None, 0
            self.spawn(self.encode(event_id, frames, partial or s.recording_truncated, s.recording_trigger))

    async def encode(self, event_id, frames, partial, trigger):
        async with self.clip_lock:
            name, status, details = await asyncio.to_thread(self.store.encode, event_id, frames, partial)
            if frames:
                details.update(pre_event_seconds=max(0, trigger - frames[0][0]), post_event_seconds=max(0, frames[-1][0] - trigger))
            async with self.factory() as db:
                event = await db.get(Incident, event_id)
                if event:
                    event.clip_name, event.clip_status, event.clip_details = name, status, details
                    await db.commit()
                elif name:
                    await asyncio.to_thread(self.store.delete, name)

    async def process(self, s, message, received_at, was_dropped=False):
        generation = s.generation
        if s is not self.session or not s.policy.armed:
            return {'v': 1, 'state': 'disarmed', 'reason': s.reason}
        if was_dropped:
            await self.work(self.detector.reset)
            s.policy.invalidate()
            s.last_evidence = None
            await self.dispatcher.cancel(reason='Dropped frames invalidated temporal history')
        now = time.monotonic()
        t = message.captured_ms / 1000
        if s.clock_offset is None:
            s.clock_offset = received_at - t
        age = now - t - s.clock_offset
        if age > 1 or age < -.15 or now - received_at > 1:
            await self.disarm('Stale or inconsistent capture timestamps; explicitly re-arm')
            return {'v': 1, 'state': 'unavailable', 'reason': s.reason}
        if s.last_capture >= 0 and (t <= s.last_capture or t - s.last_capture > 1):
            await self.disarm('Frame gap invalidated monitoring; explicitly re-arm')
            return {'v': 1, 'state': 'unavailable', 'reason': s.reason}
        s.last_capture = t
        raw, frame = await self.work(decode_frame, message.jpeg)
        evidence, tracks = await self.work(self.detector.process, t, frame)
        async with self.control_lock:
            return await self.apply_result(s, message, generation, t, now, raw, frame, evidence, tracks)

    async def apply_result(self, s, message, generation, t, now, raw, frame, evidence, tracks):
        if s is not self.session or s.generation != generation or not s.policy.armed:
            return {'v': 1, 'state': 'disarmed', 'reason': s.reason}
        # The completed result can also be stale even when its input was fresh.
        age = time.monotonic() - t - s.clock_offset
        if age > 1:
            await self._disarm('Inference result stale; explicitly re-arm')
            return {'v': 1, 'state': 'unavailable', 'reason': s.reason}
        s.last_evidence = evidence
        s.evidence_at = time.monotonic()
        if not evidence.ready:
            await self.dispatcher.cancel(reason='Insufficient fresh evidence')
        created, ended = s.policy.step(t, evidence)
        if s.clips:
            s.buffer.append(t, raw)
            if s.recording_id and len(s.recording) < 120 and s.recording_bytes + len(raw) <= 24 * 1024 * 1024:
                s.recording.append((t, raw))
                s.recording_bytes += len(raw)
            elif s.recording_id:
                s.recording_truncated = True
            if s.recording_id and t >= s.recording_until:
                self.finalize(s)
        if created:
            event_id = new_id()
            try:
                async with self.factory() as db:
                    db.add(Incident(id=event_id, session_id=s.id, captured_at=t, model_version=self.detector.temporal.version,
                                    score=evidence.score, reasons=list(evidence.reasons), track_ids=[p['id'] for p in tracks], source=s.source,
                                    clip_status='buffering' if s.clips else 'off'))
                    await db.commit()
            except SQLAlchemyError:
                self.storage_warning = 'Incident storage failed; local warning remains active. No phone action scheduled.'
                return {'v': 1, 'session_id': s.id, 'frame_id': message.frame_id, 'state': 'alert_active',
                        'reason': self.storage_warning, 'new_event': True, 'event_id': event_id,
                        'tracks': tracks, 'tracking': 'observed', 'people': len(tracks), 'source': s.source}
            s.event_id = event_id
            if s.clips:
                s.recording_id = event_id
                s.recording = list(s.buffer.frames)
                s.recording_bytes = sum(len(raw) for _, raw in s.recording)
                s.recording_until = t + 5
                s.recording_trigger = t
                s.recording_truncated = False
            if s.source == 'live':
                await self.dispatcher.enqueue(s.phone_mode, event_id=event_id)
        elif s.event_id:
            async with self.factory() as db:
                event = await db.get(Incident, s.event_id)
                if event:
                    event.updated_at = time.time()
                    event.score = max(event.score, evidence.score)
                    if ended:
                        event.status = 'ended'
                    await db.commit()
            if ended:
                s.event_id = None
        s.reason = '; '.join(evidence.reasons) if evidence.reasons else 'No event detected'
        return {'v': 1, 'session_id': s.id, 'frame_id': message.frame_id, 'captured_ms': message.captured_ms,
                'state': s.policy.state, 'reason': s.reason, 'tracking': 'observed' if evidence.ready else 'insufficient_evidence',
                'people': len(tracks), 'tracks': tracks, 'score': evidence.score, 'event_id': s.event_id,
                'new_event': created, 'frame_age_ms': round(age * 1000), 'dropped_frames': s.dropped,
                'processing_ms': round((time.monotonic() - now) * 1000), 'source': s.source}

    async def calls(self):
        while True:
            try:
                await self.dispatcher.tick()
            except Exception:
                # No retries of claimed provider submissions; countdowns expire rather than catch up.
                pass
            await asyncio.sleep(.25)

    async def maintain(self):
        count = 0
        while True:
            await asyncio.sleep(.25)
            s = self.session
            if s and (time.monotonic() > s.expires or (not s.connected and time.monotonic() - s.created_monotonic > 10)):
                await self.end()
            elif s and s.policy.armed and time.monotonic() - s.last_frame > 1:
                await self.disarm('Fresh frames stopped; explicitly re-arm')
            count += 1
            if count % 240 == 0:
                try:
                    async with self.clip_lock:
                        await cleanup(self.factory, self.store, self.config)
                except Exception:
                    if s:
                        s.reason = 'Storage cleanup failed; check local disk'
