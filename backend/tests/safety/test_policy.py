from backend.safety.event_policy import EventPolicy, Evidence

POS = Evidence(True, .9, True, 2)
NEG = Evidence(True, .1, False, 2)


def advance(policy, start, seconds, evidence):
    return [policy.step(start + i / 10, evidence) for i in range(int(seconds * 10))]


def test_one_episode_and_quiet_cooldown():
    p = EventPolicy()
    assert not any(a for a, _ in advance(p, 0, 2, POS))
    p.arm()
    assert sum(a for a, _ in advance(p, 0, 10, POS)) == 1
    assert p.state == 'alert_active'
    assert sum(b for _, b in advance(p, 10, 3, NEG)) == 1
    assert not any(a for a, _ in advance(p, 13, 29, POS))
    assert sum(a for a, _ in advance(p, 42, 2, POS)) == 1


def test_uncertain_lone_undirected_and_frame_gap_abstain():
    for evidence in (Evidence(False, .99, True, 2), Evidence(True, .99, True, 1), Evidence(True, .99, False, 2)):
        p = EventPolicy(); p.arm()
        assert not any(a for a, _ in advance(p, 0, 5, evidence))
    p = EventPolicy(); p.arm()
    p.step(0, POS); p.step(.1, POS)
    assert p.step(2, POS) == (False, False)
    assert p.state == 'warming_up'
    assert p.step(2.1, POS) == (False, False)
    p.disarm()
    assert p.step(2.2, POS) == (False, False)


def test_uncertainty_does_not_close_active_episode():
    p = EventPolicy(); p.arm()
    advance(p, 0, 1, POS)
    assert p.event_open
    advance(p, 1, 10, Evidence(False))
    assert p.event_open
    assert not any(a for a, _ in advance(p, 11, 5, POS))
