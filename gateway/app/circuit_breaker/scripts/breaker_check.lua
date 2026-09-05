-- Atomic "may I call downstream right now?" check.
--
-- KEYS[1] = breaker key, e.g. "circuitbreaker:downstream_mock"
-- ARGV[1] = now (unix timestamp, seconds)
-- ARGV[2] = cooldown_seconds
--
-- Returns {allowed (1/0), reported_state}
--
-- Persisted state is only ever "closed" or "open" — "half_open" is a
-- transient label reported back to exactly one caller per cooldown expiry
-- (the one that atomically claims "trial_in_flight"), so two concurrent
-- requests arriving the instant the cooldown elapses can't both slip
-- through as the trial. That single-trial guarantee is the entire reason
-- this has to be a Lua script and not a read-then-write in Python.

local data = redis.call("HMGET", KEYS[1], "state", "opened_at", "trial_in_flight")
local state = data[1] or "closed"

if state == "closed" then
    return {1, "closed"}
end

-- state == "open"
local opened_at = tonumber(data[2]) or 0
local now = tonumber(ARGV[1])
local cooldown = tonumber(ARGV[2])
local trial_in_flight = data[3]

if (now - opened_at) < cooldown then
    return {0, "open"}
end

if trial_in_flight == "1" then
    -- cooldown has elapsed, but another concurrent request already claimed
    -- the one trial slot for this cooldown window
    return {0, "open"}
end

redis.call("HSET", KEYS[1], "trial_in_flight", "1")
redis.call("EXPIRE", KEYS[1], 3600)
return {1, "half_open"}
