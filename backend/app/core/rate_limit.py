import time
from fastapi import HTTPException, Request
from redis import Redis
from app.core.client_ip import extract_client_ip
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
            raise HTTPException(status_code=429, detail="Request rate limit exceeded")
    except HTTPException:
        raise
    except Exception as exc:
        if settings.rate_limit_fail_open:
            # Keep API available if Redis is temporarily unavailable.
            return
        raise HTTPException(status_code=503, detail="Rate limit service is unavailable") from exc


def _client_ip(request: Request) -> str:
    return extract_client_ip(request)


def check_registration_rate_limit(request: Request, email: str) -> None:
    current_bucket = int(time.time() // 3600)
    client_ip = _client_ip(request)
    key_ip = f"rl:register:ip:{client_ip}:{current_bucket}"
    key_email = f"rl:register:email:{email}:{current_bucket}"
    try:
        ip_count = _redis.incr(key_ip)
        if ip_count == 1:
            _redis.expire(key_ip, 3700)
        if ip_count > settings.register_rate_limit_per_ip_per_hour:
            raise HTTPException(status_code=429, detail="Too many registration attempts from this IP")

        email_count = _redis.incr(key_email)
        if email_count == 1:
            _redis.expire(key_email, 3700)
        if email_count > settings.register_rate_limit_per_email_per_hour:
            raise HTTPException(status_code=429, detail="Too many registration attempts for this email")
    except HTTPException:
        raise
    except Exception as exc:
        if settings.rate_limit_fail_open:
            return
        raise HTTPException(status_code=503, detail="Rate limit service is unavailable") from exc


def check_registration_captcha_rate_limit(request: Request) -> None:
    current_bucket = int(time.time() // 3600)
    client_ip = _client_ip(request)
    key_ip = f"rl:register:captcha:ip:{client_ip}:{current_bucket}"
    try:
        ip_count = _redis.incr(key_ip)
        if ip_count == 1:
            _redis.expire(key_ip, 3700)
        if ip_count > settings.register_captcha_rate_limit_per_ip_per_hour:
            raise HTTPException(status_code=429, detail="Too many CAPTCHA requests from this IP")
    except HTTPException:
        raise
    except Exception as exc:
        if settings.rate_limit_fail_open:
            return
        raise HTTPException(status_code=503, detail="Rate limit service is unavailable") from exc
