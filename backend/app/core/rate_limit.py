import time
from fastapi import HTTPException, Request
from redis import Redis
from app.core.config import get_settings

settings = get_settings()
_redis = Redis.from_url(settings.redis_url, decode_responses=True)


def check_rate_limit(request: Request, tenant_id: str, user_id: str) -> None:
    key = f"rl:{tenant_id}:{user_id}:{int(time.time() // 60)}"
    try:
        count = _redis.incr(key)
        if count == 1:
            _redis.expire(key, 70)
        if count > settings.rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="Превышен лимит запросов")
    except HTTPException:
        raise
    except Exception as exc:
        if settings.rate_limit_fail_open:
            # Keep API available if Redis is temporarily unavailable.
            return
        raise HTTPException(status_code=503, detail="Сервис ограничения запросов недоступен") from exc
