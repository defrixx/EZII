import ipaddress
from functools import lru_cache

from fastapi import Request

from app.core.config import get_settings

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache
def _trusted_proxy_networks() -> tuple[IpNetwork, ...]:
    raw = (get_settings().trusted_proxy_cidrs or "").strip()
    if not raw:
        return tuple()
    networks: list[IpNetwork] = []
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted_proxy(host: str) -> bool:
    try:
        host_ip = ipaddress.ip_address(host.strip())
    except ValueError:
        return False
    return any(host_ip in network for network in _trusted_proxy_networks())


def extract_client_ip(request: Request) -> str:
    client_host = request.client.host if request.client else ""
    if not client_host:
        return "unknown"
    if not _is_trusted_proxy(client_host):
        return client_host

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        chain: list[str] = []
        for part in forwarded.split(","):
            candidate = part.strip()
            if not candidate:
                continue
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                continue
            chain.append(candidate)
        if chain:
            # Walk from right to left and stop at the first non-trusted proxy address.
            # This is resilient to proxy append mode and mixed trusted/untrusted hops.
            for candidate in reversed(chain):
                if not _is_trusted_proxy(candidate):
                    return candidate
            # If all hops are trusted proxies, fall back to the left-most valid value.
            return chain[0]
    return client_host
