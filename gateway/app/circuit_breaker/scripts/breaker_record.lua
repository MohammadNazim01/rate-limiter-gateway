-- Atomically records the outcome of a downstream call and applies the
-- state transition. Called once after every downstream call that
-- breaker_check.lua allowed through.
--
-- KEYS[1] = breaker key
-- ARGV[1] = success (1/0)
-- ARGV[2] = now (unix timestamp, seconds)
-- ARGV[3] = failure_threshold
--
-- Returns the new persisted state ("closed" or "open").

local success = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local threshold = tonumber(ARGV[3])

local data = redis.call("HMGET", KEYS[1], "state", "failure_count")
local state = data[1] or "closed"
local failure_count = tonumber(data[2]) or 0

if success == 1 then
    -- Any success — including the single half-open trial — closes the
    -- breaker and resets everything.
    redis.call("HSET", KEYS[1], "state", "closed", "failure_count", 0, "trial_in_flight", "0")
    redis.call("EXPIRE", KEYS[1], 3600)
    return "closed"
end

-- failure
if state == "open" then
    -- This was the half-open trial failing: stay open, restart the
    -- cooldown clock so the next trial isn't attempted immediately.
    redis.call("HSET", KEYS[1], "state", "open", "opened_at", now, "trial_in_flight", "0")
    redis.call("EXPIRE", KEYS[1], 3600)
    return "open"
end

-- state == "closed": accumulate consecutive failures
failure_count = failure_count + 1
if failure_count >= threshold then
    redis.call(
        "HSET", KEYS[1],
        "state", "open", "opened_at", now,
        "failure_count", failure_count, "trial_in_flight", "0"
    )
    redis.call("EXPIRE", KEYS[1], 3600)
    return "open"
end

redis.call("HSET", KEYS[1], "failure_count", failure_count)
redis.call("EXPIRE", KEYS[1], 3600)
return "closed"
