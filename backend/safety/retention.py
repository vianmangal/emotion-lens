import time
from sqlalchemy import select, delete
from backend.safety.models import Incident, Action


async def cleanup(factory, store, config, now=None):
    now = time.time() if now is None else now
    async with factory() as db:
        events = (await db.scalars(select(Incident))).all()
        for event in events:
            expired_metadata = now - event.created_at > config.SAFETY_METADATA_RETENTION_DAYS * 86400
            expired_clip = now - event.created_at > config.SAFETY_CLIP_RETENTION_HOURS * 3600
            if expired_metadata or expired_clip:
                try:
                    store.delete(event.clip_name)
                except (OSError, ValueError):
                    # Keep metadata so a failed file deletion can be retried and surfaced.
                    event.clip_status = 'delete_failed'
                    continue
                event.clip_name = None
                event.clip_status = 'expired' if expired_clip else event.clip_status
                if expired_metadata:
                    await db.delete(event)
        # Call quota/dedup survives event deletion. Never prune in-flight actions.
        await db.execute(delete(Action).where(Action.created_at < now - max(config.SAFETY_METADATA_RETENTION_DAYS * 86400, 3600), Action.state.notin_(['countdown', 'submitting'])))
        await db.commit()
        referenced = set((await db.scalars(select(Incident.clip_name).where(Incident.clip_name.is_not(None)))).all())
    # Interrupted encodes can leave orphan files. No live encoder runs during startup cleanup.
    for path in store.directory.glob('*.webm'):
        if path.name not in referenced and not path.is_symlink() and now - path.stat().st_mtime > 600:
            try:
                store.delete(path.name)
            except (OSError, ValueError):
                pass
