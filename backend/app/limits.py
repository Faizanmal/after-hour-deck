from __future__ import annotations

import re
import threading
import time
from collections import deque

from fastapi import Request

_IP = re.compile(r"^[0-9a-fA-F:.]+$")


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, checks: list[tuple[str, int, int]]) -> str | None:
        """Record every check, or return the first key that is already over its limit."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 5000:
                stale = [key for key, hits in self._hits.items() if not hits]
                for key in stale:
                    del self._hits[key]
            windows: list[deque[float]] = []
            for key, limit, window_seconds in checks:
                hits = self._hits.setdefault(key, deque())
                while hits and now - hits[0] > window_seconds:
                    hits.popleft()
                if len(hits) >= limit:
                    return key
                windows.append(hits)
            for hits in windows:
                hits.append(now)
        return None


limiter = RateLimiter()


class InflightGuard:
    """Caps how many requests run at once so a flood cannot pin the process."""

    def __init__(self, per_ip: int, total: int) -> None:
        self.per_ip = per_ip
        self.total = total
        self._by_ip: dict[str, int] = {}
        self._total = 0
        self._lock = threading.Lock()

    def enter(self, ip: str) -> str | None:
        with self._lock:
            current = self._by_ip.get(ip, 0)
            if current >= self.per_ip:
                return "ip"
            if self._total >= self.total:
                return "global"
            self._by_ip[ip] = current + 1
            self._total += 1
            return None

    def leave(self, ip: str) -> None:
        with self._lock:
            current = self._by_ip.get(ip, 0)
            if current <= 1:
                self._by_ip.pop(ip, None)
            else:
                self._by_ip[ip] = current - 1
            if self._total:
                self._total -= 1


inflight = InflightGuard(per_ip=8, total=24)


def _last_forwarded_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    parts = [part.strip() for part in forwarded.split(",") if _IP.fullmatch(part.strip())]
    if not parts:
        return None
    return parts[-1][:64]


def client_ip(request: Request) -> str:
    from app.config import get_settings

    peer = request.client.host if request.client else ""
    if get_settings().trust_proxy:
        forwarded = _last_forwarded_ip(request)
        if forwarded:
            return forwarded
    if peer in {"127.0.0.1", "::1"}:
        marked = request.headers.get("x-client-ip", "").strip()
        if _IP.fullmatch(marked):
            return marked[:64]
        return "unknown"
    return peer or "unknown"
