import fakeredis

from app.circuit_breaker.breaker import CircuitBreaker


def make_breaker(threshold=3, cooldown=10.0, clock=None, name="test"):
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    return CircuitBreaker(
        name=name,
        failure_threshold=threshold,
        cooldown_seconds=cooldown,
        redis_client=fake_redis,
        **kwargs,
    )


async def test_fresh_breaker_is_closed_and_allows():
    breaker = make_breaker()
    result = await breaker.check()
    assert result.allowed is True
    assert result.state == "closed"


async def test_opens_after_threshold_consecutive_failures():
    breaker = make_breaker(threshold=3, clock=lambda: 1000.0)

    assert (await breaker.record_failure()) == "closed"
    assert (await breaker.record_failure()) == "closed"
    assert (await breaker.record_failure()) == "open"  # 3rd failure trips it

    result = await breaker.check()
    assert result.allowed is False
    assert result.state == "open"


async def test_denied_during_cooldown_window():
    breaker = make_breaker(threshold=1, cooldown=10.0, clock=lambda: 1000.0)
    await breaker.record_failure()  # trips immediately (threshold=1)

    result = await breaker.check()
    assert result.allowed is False
    assert result.state == "open"


async def test_success_resets_failure_count_before_threshold_is_reached():
    breaker = make_breaker(threshold=3, clock=lambda: 1000.0)

    await breaker.record_failure()
    await breaker.record_failure()  # 2/3, not open yet
    state = await breaker.record_success()
    assert state == "closed"

    # two more failures now should NOT open it (count was reset by the success)
    await breaker.record_failure()
    state = await breaker.record_failure()
    assert state == "closed"


async def test_single_trial_granted_after_cooldown_others_denied():
    current_time = {"t": 1000.0}
    breaker = make_breaker(threshold=1, cooldown=10.0, clock=lambda: current_time["t"])
    await breaker.record_failure()  # open

    current_time["t"] += 10.0  # cooldown elapsed

    first = await breaker.check()
    second = await breaker.check()  # simulates a concurrent request

    assert first.allowed is True
    assert first.state == "half_open"
    # the trial slot is already claimed — a second concurrent caller must
    # not also be let through, or the breaker would let N requests hammer a
    # downstream that's still down the instant the cooldown expires
    assert second.allowed is False
    assert second.state == "open"


async def test_failed_trial_keeps_breaker_open_and_restarts_cooldown():
    current_time = {"t": 1000.0}
    breaker = make_breaker(threshold=1, cooldown=10.0, clock=lambda: current_time["t"])
    await breaker.record_failure()  # open

    current_time["t"] += 10.0
    trial = await breaker.check()
    assert trial.allowed is True

    state = await breaker.record_failure()  # trial fails
    assert state == "open"

    # immediately after — still within the *new* cooldown window
    still_denied = await breaker.check()
    assert still_denied.allowed is False


async def test_successful_trial_closes_the_breaker():
    current_time = {"t": 1000.0}
    breaker = make_breaker(threshold=1, cooldown=10.0, clock=lambda: current_time["t"])
    await breaker.record_failure()  # open

    current_time["t"] += 10.0
    trial = await breaker.check()
    assert trial.allowed is True

    state = await breaker.record_success()
    assert state == "closed"

    after = await breaker.check()
    assert after.allowed is True
    assert after.state == "closed"


async def test_different_breaker_names_are_independent():
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    a = CircuitBreaker(name="service_a", failure_threshold=1, cooldown_seconds=10.0,
                        redis_client=fake_redis, clock=lambda: 1000.0)
    b = CircuitBreaker(name="service_b", failure_threshold=1, cooldown_seconds=10.0,
                        redis_client=fake_redis, clock=lambda: 1000.0)

    await a.record_failure()  # trips only breaker "a"

    a_check = await a.check()
    b_check = await b.check()
    assert a_check.allowed is False
    assert b_check.allowed is True
