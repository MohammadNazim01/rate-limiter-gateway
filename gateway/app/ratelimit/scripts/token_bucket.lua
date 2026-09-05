-- Atomic token-bucket check-and-consume.
--
-- KEYS[1] = bucket key, e.g. "ratelimit:token_bucket:<client_id>"
-- ARGV[1] = capacity      (max tokens / burst allowance)
-- ARGV[2] = refill_rate   (tokens added per second)
-- ARGV[3] = now           (unix timestamp, seconds, float)
-- ARGV[4] = cost          (tokens this request consumes, usually 1)
--
-- Returns {allowed (1/0), tokens_remaining, retry_after_seconds}
--
-- IMPORTANT: Redis converts Lua numbers to RESP integers on return,
-- silently TRUNCATING decimals (e.g. 2.9 becomes 2). Both tokens_remaining
-- and retry_after_seconds must stay fractional, so we return them via
-- tostring() and parse them back to float in Python — a classic
-- Redis-Lua gotcha that would otherwise corrupt the refill math.
--
-- Runs as a single EVAL: the read (HMGET), the compute, and the write
-- (HMSET) happen atomically inside Redis, so two concurrent requests for
-- the same client can never both read the same starting token count.

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local bucket = redis.call("HMGET", key, "tokens", "last_refill")
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    -- first request from this client: bucket starts full
    tokens = capacity
    last_refill = now
end

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
local retry_after = 0

if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
else
    local deficit = cost - tokens
    retry_after = deficit / refill_rate
end

redis.call("HMSET", key, "tokens", tokens, "last_refill", now)
-- Let an idle client's bucket expire instead of growing Redis memory forever.
redis.call("EXPIRE", key, math.ceil(capacity / refill_rate) + 60)

return {allowed, tostring(tokens), tostring(retry_after)}
