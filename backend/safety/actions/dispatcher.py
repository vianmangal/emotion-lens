import asyncio
import time
from datetime import datetime, timezone
from sqlalchemy import select, update, func, or_
from sqlalchemy.exc import IntegrityError
from backend.safety.models import Action, Incident, new_id
from backend.safety.actions.elevenlabs import ElevenLabs, configured, trusted_message, masked_recipient


class Dispatcher:
    def __init__(self, factory, config, allowed, provider=None, clock=time.time):
        self.factory, self.config, self.allowed = factory, config, allowed
        self.provider = provider or ElevenLabs(config)
        self.clock = clock
        self.lock = asyncio.Lock()

    async def recover(self):
        async with self.factory() as db:
            await db.execute(update(Action).where(Action.state == 'countdown').values(state='cancelled', error_category='process_restart'))
            await db.execute(update(Action).where(Action.state == 'submitting').values(state='delivery_unknown', error_category='process_restart'))
            await db.execute(update(Incident).where(Incident.status == 'active').values(status='interrupted'))
            await db.execute(update(Incident).where(Incident.clip_status == 'buffering').values(clip_status='interrupted'))
            await db.commit()

    async def enqueue(self, mode, event_id=None, request_id=None):
        if mode == 'off':
            return None
        now = self.clock()
        action_id = new_id()
        key = f'event:{event_id}:phone' if event_id else f'test:{request_id}'
        async with self.factory() as db:
            existing = await db.scalar(select(Action).where(Action.dedup_key == key))
            if existing:
                return existing.id
            event = await db.get(Incident, event_id) if event_id else None
            if event_id and event is None:
                return None  # An incident deleted during creation cannot become a test call.
            event_time = datetime.fromtimestamp(event.created_at, timezone.utc).isoformat() if event else None
            preview = {'dry_run_payload': {'summary': trusted_message(event_id is None, event_time),
                       'recipient': masked_recipient(self.config), 'call_recording_enabled': False,
                       'external_service': 'ElevenLabs native Twilio (not contacted)'}} if mode == 'dry_run' else {}
            db.add(Action(id=action_id, event_id=event_id, dedup_key=key, mode=mode, provider_ids=preview,
                          due_at=now + self.config.SAFETY_CALL_GRACE_SECONDS))
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                duplicate = await db.scalar(select(Action).where(Action.dedup_key == key))
                if duplicate:
                    return duplicate.id
                raise
        return action_id

    async def cancel(self, event_id=None, reason='operator_cancelled', action_id=None, session_id=None):
        async with self.factory() as db:
            query = update(Action).where(Action.state == 'countdown')
            if event_id is not None:
                query = query.where(Action.event_id == event_id)
            if action_id is not None:
                query = query.where(Action.id == action_id)
            if session_id is not None:
                query = query.where(Action.event_id.in_(select(Incident.id).where(Incident.session_id == session_id)))
            await db.execute(query.values(state='cancelled', error_category=reason))
            await db.commit()

    async def dispatch(self, action_id):
        # Only claim inside the lock; provider I/O is outside it, so disarm/cancel remains responsive.
        async with self.lock:
            now = self.clock()
            async with self.factory() as db:
                action = await db.get(Action, action_id)
                if not action or action.state != 'countdown' or now < action.due_at:
                    return
                event = await db.get(Incident, action.event_id) if action.event_id else None
                reason = None
                if now - action.due_at > 5:
                    reason = 'expired_countdown'
                elif action.event_id and not self.allowed(event, action.mode):
                    reason = 'session_not_armed_or_fresh'
                elif action.mode == 'real':
                    if not configured(self.config):
                        reason = 'phone_not_configured'
                    else:
                        attempts = (await db.scalars(select(Action).where(Action.mode == 'real', Action.attempt_at >= now - 3600))).all()
                        inflight = await db.scalar(select(func.count()).select_from(Action).where(Action.state == 'submitting'))
                        if inflight:
                            reason = 'call_in_flight'
                        elif len(attempts) >= self.config.SAFETY_CALL_MAX_PER_HOUR:
                            reason = 'hourly_quota'
                        elif any(now - a.attempt_at < self.config.SAFETY_CALL_COOLDOWN_SECONDS for a in attempts):
                            reason = 'recipient_cooldown'
                target = 'cancelled' if reason else ('dry_run' if action.mode == 'dry_run' else 'submitting')
                values = {'state': target, 'error_category': reason}
                if target == 'submitting':
                    values['attempt_at'] = now
                claim = await db.execute(update(Action).where(Action.id == action.id, Action.state == 'countdown').values(**values))
                await db.commit()  # Durable claim before any network request; no automatic retry.
                if not claim.rowcount or target != 'submitting':
                    return
                event_time = datetime.fromtimestamp(event.created_at, timezone.utc).isoformat() if event else None
                is_test = event is None
        try:
            state, ids, error = await self.provider.send(is_test=is_test, event_time=event_time)
        except Exception:
            state, ids, error = 'delivery_unknown', {}, 'provider_exception_unknown'
        async with self.factory() as db:
            await db.execute(update(Action).where(Action.id == action_id, Action.state == 'submitting').values(state=state, provider_ids=ids, error_category=error))
            await db.commit()

    async def tick(self):
        async with self.factory() as db:
            ids = (await db.scalars(select(Action.id).where(Action.state == 'countdown', Action.due_at <= self.clock()).limit(10))).all()
        for action_id in ids:
            await self.dispatch(action_id)
