import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import secrets
import time
from collections import deque
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from backend.safety.detector import Detector
from backend.safety.event_policy import EventPolicy, threshold_version
from backend.safety.frame_buffer import FrameBuffer, decode_frame
from backend.safety.recording import RecordingStore
from backend.safety.models import Incident, new_id
from backend.safety.actions.dispatcher import Dispatcher
from backend.safety.actions.provider import configured, masked_recipient, provider_label
from backend.safety.retention import cleanup


@dataclass
class Session:
    id: str = field(default_factory=new_id)
    capability: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    source: str = 'live'
    live_only: bool = False
    created_monotonic: float = field(default_factory=time.monotonic)
    expires: float = field(default_factory=lambda: time.monotonic() + 3600)
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
        self.persistence_ready = True

    def storage_failed(self, reason):
        self.storage_warning = reason
        self.persistence_ready = False
        if self.session:
            self.session.phone_mode = 'off'

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
        try:
            await self.dispatcher.recover()
        except SQLAlchemyError:
            self.storage_failed('Local database unavailable; check disk space/permissions and restart. Phone actions are disabled.')
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
                'persistence_ready': self.persistence_ready,
                'clip_retention_hours': self.config.SAFETY_CLIP_RETENTION_HOURS,
                'metadata_retention_days': self.config.SAFETY_METADATA_RETENTION_DAYS, 'phone_configured': configured(self.config),
                'event_policy': self.config.event_policy_options(),
                'threshold_version': threshold_version(self.config.event_policy_options()),
                'recipient': masked_recipient(self.config), 'phone_provider': provider_label(self.config), 'real_auto_calls_available': False,
                'real_test_available': configured(self.config) and self.persistence_ready, 'call_grace_seconds': self.config.SAFETY_CALL_GRACE_SECONDS}

    async def create(self, source, live_only=False):
        if self.session:
            raise ValueError('A camera session is already active. Stop it first.')
        await self.work(self.detector.reset)
        policy_options = self.config.event_policy_options()
        if live_only:
            # The live feed must recognize the next motion without the incident
            # history's 30-second notification cooldown.
            policy_options['cooldown'] = 0
        self.session = Session(source=source, live_only=live_only, policy=EventPolicy(**policy_options),
                               expires=time.monotonic() + self.config.SAFETY_SESSION_TTL_SECONDS)
        return self.session

    async def disarm(self, reason='Disarmed', expected_session=None):
        async with self.control_lock:
            if expected_session is not None and self.session is not expected_session:
                return False
            await self._disarm(reason)
            return True

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
        event_id, s.event_id = s.event_id, None
        self.finalize(s, partial=True)
        try:
            if not s.live_only:
                await self.dispatcher.cancel(reason=reason)
            if event_id:
                async with self.factory() as db:
                    event = await db.get(Incident, event_id)
                    if event:
                        event.status = 'interrupted'
                        await db.commit()
        except SQLAlchemyError:
            self.storage_failed('Storage unavailable during disarm; monitoring stopped. Check local disk.')
        finally:
            await self.work(self.detector.reset)

    async def end(self, expected_session=None):
        async with self.control_lock:
            if expected_session is not None and self.session is not expected_session:
                return False
            await self._end()
            return True

    async def _end(self):
        s = self.session
        if s:
            await self._disarm('Camera stopped or disconnected')
            s.connected = False
            self.session = None

    async def arm(self, options, expected_session=None):
        received_at = time.monotonic()
        async with self.control_lock:
            if expected_session is not None and self.session is not expected_session:
                raise ValueError('Session changed; start and arm the current camera explicitly')
            await self._arm(options, received_at)

    async def _arm(self, options, received_at):
        s = self.session
        if not s or not s.connected:
            raise ValueError('Start the camera stream first')
        if not self.detector.ready:
            raise ValueError(self.detector.reason)
        if s.live_only and (options.phone_mode != 'off' or options.clips):
            raise ValueError('Live-only sessions support tracking and detection without clips or phone actions')
        if options.phone_mode == 'real':
            raise ValueError('Automatic real calls are locked: detector qualification is unmet. Use dry run or an explicit phone test.')
        if options.client_now_ms is None:
            raise ValueError('A fresh client monotonic timestamp is required when arming; reload the local UI')
        if options.clips and not self.store.available:
            raise ValueError(self.store.reason)
        if options.phone_mode != 'off' and not self.persistence_ready:
            raise ValueError('Phone actions need writable local storage. Use Off for local monitoring or fix storage and restart.')
        await self._disarm()
        s.last_frame = time.monotonic()
        s.phone_mode, s.clips = options.phone_mode, options.clips
        s.policy.arm()
        s.reason = 'Warming temporal window'
        s.last_capture = -1
        s.last_evidence = None
        s.clock_offset = received_at - options.client_now_ms / 1000

    def action_allowed(self, event, mode):
        s = self.session
        if not (self.persistence_ready and s and not s.live_only and event and event.session_id == s.id and s.connected and s.policy.armed and s.source == 'live' and s.phone_mode == mode and time.monotonic() - s.last_frame < 1 and time.monotonic() - s.evidence_at < 1 and s.last_evidence and s.last_evidence.ready and s.last_evidence.people >= 2):
            return False
        return mode == 'dry_run' or self.detector.qualified

    def finalize(self, s, partial=False):
        if s.recording_id:
            frames, event_id = s.recording, s.recording_id
            s.recording, s.recording_id, s.recording_bytes = [], None, 0
            self.spawn(self.encode(event_id, frames, partial or s.recording_truncated, s.recording_trigger))

    async def encode(self, event_id, frames, partial, trigger):
        async with self.clip_lock:
            async with self.factory() as db:
                if await db.get(Incident, event_id) is None:
                    return  # A queued encoder must not recreate a deleted event's file.
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
            if s is not self.session or s.generation != generation or not s.policy.armed:
                return {'v': 1, 'state': 'disarmed', 'reason': s.reason}
            s.policy.invalidate()
            s.last_evidence = None
            await self.cancel_automatic(s, 'Dropped frames invalidated temporal history')
        now = time.monotonic()
        t = message.captured_ms / 1000
        if s.clock_offset is None:
            await self.disarm('Capture clock unavailable; explicitly re-arm', expected_session=s)
            return {'v': 1, 'state': 'unavailable', 'reason': s.reason}
        age = now - t - s.clock_offset
        if age > 1 or age < -.15 or now - received_at > 1:
            await self.disarm('Stale or inconsistent capture timestamps; explicitly re-arm', expected_session=s)
            return {'v': 1, 'state': 'unavailable', 'reason': s.reason}
        if s.last_capture >= 0 and (t <= s.last_capture or t - s.last_capture > 1):
            await self.disarm('Frame gap invalidated monitoring; explicitly re-arm', expected_session=s)
            return {'v': 1, 'state': 'unavailable', 'reason': s.reason}
        s.last_capture = t
        raw, frame = await self.work(decode_frame, message.jpeg)
        if s is not self.session or s.generation != generation or not s.policy.armed:
            return {'v': 1, 'state': 'disarmed', 'reason': s.reason}
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
            await self.cancel_automatic(s, 'Insufficient fresh evidence')
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
        if created and not s.live_only:
            event_id = new_id()
            try:
                async with self.factory() as db:
                    db.add(Incident(id=event_id, session_id=s.id, captured_at=t, model_version=self.detector.temporal.version,
                                    threshold_version=threshold_version(self.config.event_policy_options()),
                                    score=evidence.score, reasons=list(evidence.reasons), track_ids=list(evidence.track_ids) or [p['id'] for p in tracks], source=s.source,
                                    clip_status='buffering' if s.clips else 'off'))
                    await db.commit()
            except SQLAlchemyError:
                self.storage_failed('Incident storage failed; local warning remains active. No phone action scheduled.')
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
                try:
                    await self.dispatcher.enqueue(s.phone_mode, event_id=event_id)
                except SQLAlchemyError:
                    self.storage_failed('Phone action storage failed; incident remains visible. No call scheduled.')
        elif s.event_id:
            try:
                async with self.factory() as db:
                    event = await db.get(Incident, s.event_id)
                    if event:
                        event.updated_at = time.time()
                        event.score = max(event.score, evidence.score)
                        if ended:
                            event.status = 'ended'
                        await db.commit()
            except SQLAlchemyError:
                self.storage_failed('Incident update failed; local alert remains active. Check local disk.')
            if ended:
                s.event_id = None
        s.reason = '; '.join(evidence.reasons) if evidence.reasons else 'No event detected'
        return {'v': 1, 'session_id': s.id, 'frame_id': message.frame_id, 'captured_ms': message.captured_ms,
                'state': s.policy.state, 'reason': s.reason, 'tracking': 'observed' if evidence.ready else 'insufficient_evidence',
                'people': len(tracks), 'tracks': tracks, 'score': evidence.score, 'event_id': s.event_id,
                'interaction_track_ids': list(evidence.track_ids),
                'new_event': created, 'live_only': s.live_only,
                'frame_age_ms': round(age * 1000), 'dropped_frames': s.dropped,
                'processing_ms': round((time.monotonic() - now) * 1000), 'source': s.source,
                'storage_warning': self.storage_warning}

    async def cancel_automatic(self, session, reason):
        if self.persistence_ready and not session.live_only:
            try:
                await self.dispatcher.cancel(session_id=session.id, reason=reason)
            except SQLAlchemyError:
                self.storage_failed('Phone action storage unavailable; automatic actions disabled until restart. Local monitoring continues.')

    async def calls(self):
        while True:
            try:
                if self.persistence_ready:
                    await self.dispatcher.tick()
            except SQLAlchemyError:
                self.storage_failed('Phone action storage failed; dispatch paused until restart. Check local disk.')
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
                await self.end(expected_session=s)
            elif s and s.policy.armed and time.monotonic() - s.last_frame > 1:
                await self.disarm('Fresh frames stopped; explicitly re-arm', expected_session=s)
            count += 1
            if count % 240 == 0:
                try:
                    async with self.clip_lock:
                        await cleanup(self.factory, self.store, self.config)
                except Exception:
                    if s:
                        s.reason = 'Storage cleanup failed; check local disk'
