from datetime import datetime, timedelta, timezone


def limit_window_start_utc(now: datetime | None = None) -> datetime:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


def limit_window_reset_at_utc(now: datetime | None = None) -> datetime:
    return limit_window_start_utc(now) + timedelta(days=1)


def format_limit_reset_at_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
