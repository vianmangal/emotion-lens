from dataclasses import dataclass
import hashlib
import json


def threshold_version(options):
    encoded = json.dumps(options, sort_keys=True, separators=(',', ':')).encode()
    return f'experimental-{hashlib.sha256(encoded).hexdigest()[:12]}'


@dataclass(frozen=True)
class Evidence:
    ready: bool
    score: float = 0.0
    directed: bool = False
    people: int = 0
    reasons: tuple = ()
    track_ids: tuple = ()


class EventPolicy:
    """Monotonic hysteresis. An uncertain frame cannot open or close an episode."""
    def __init__(self, entry=.75, exit=.35, entry_seconds=.3, quiet_seconds=2, cooldown=30):
        self.entry, self.exit = entry, exit
        self.entry_seconds, self.quiet_seconds, self.cooldown = entry_seconds, quiet_seconds, cooldown
        self.disarm()

    def disarm(self):
        self.armed = False
        self.state = 'disarmed'
        self.event_open = False
        self.candidate_since = None
        self.quiet_since = None
        self.cooldown_until = 0
        self.last_t = None

    def arm(self):
        self.disarm()
        self.armed = True
        self.state = 'warming_up'

    def invalidate(self):
        self.candidate_since = self.quiet_since = None
        if self.armed:
            self.state = 'alert_active' if self.event_open else 'warming_up'

    def step(self, t, evidence):
        if not self.armed:
            return False, False
        if self.last_t is not None and (t <= self.last_t or t - self.last_t > 1):
            self.invalidate()
            self.last_t = t
            return False, False
        self.last_t = t
        if not evidence.ready or evidence.people < 2:
            self.invalidate()
            return False, False
        if self.event_open:
            self.state = 'alert_active'
            if evidence.score <= self.exit:
                self.quiet_since = t if self.quiet_since is None else self.quiet_since
                if t - self.quiet_since >= self.quiet_seconds:
                    self.event_open = False
                    self.cooldown_until = t + self.cooldown
                    self.state = 'cooldown'
                    return False, True
            else:
                self.quiet_since = None
            return False, False
        if t < self.cooldown_until:
            self.state = 'cooldown'
            return False, False
        if evidence.directed and evidence.score >= self.entry:
            self.candidate_since = t if self.candidate_since is None else self.candidate_since
            self.state = 'candidate'
            if t - self.candidate_since >= self.entry_seconds:
                self.event_open = True
                self.state = 'alert_active'
                return True, False
        else:
            self.candidate_since = None
            self.state = 'monitoring'
        return False, False
