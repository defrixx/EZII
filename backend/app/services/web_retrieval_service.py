import ipaddress
import re
import socket
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup


class WebRetrievalService:
    DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,63}$")
    BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}

    @classmethod
    def _resolve_public_ips(cls, domain: str) -> set[str] | None:
        d = domain.strip().lower()
        if not d or d in cls.BLOCKED_HOSTS:
            return None
        if not cls.DOMAIN_RE.fullmatch(d):
            return None
        resolved: set[str] = set()
        try:
            infos = socket.getaddrinfo(d, 443, proto=socket.IPPROTO_TCP)
            for info in infos:
                raw_ip = info[4][0]
                ip = ipaddress.ip_address(raw_ip)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    return None
                resolved.add(raw_ip)
        except Exception:
            return None
        return resolved or None

    async def fetch_allowed(self, query: str, domains: list[str]) -> tuple[list[dict], list[str]]:
        snippets: list[dict] = []
        used_domains: list[str] = []
        for domain in domains[:3]:
            initial_resolved = self._resolve_public_ips(domain)
            if not initial_resolved:
                continue
            url = f"https://{domain}"
            try:
                async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    final_domain = urlparse(str(resp.url)).netloc.split(":")[0].lower()
                    if final_domain != domain.lower():
                        continue
                    final_resolved = self._resolve_public_ips(final_domain)
                    if not final_resolved or final_resolved != initial_resolved:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    text = " ".join(soup.get_text(" ", strip=True).split())[:1000]
                    if query.lower() in text.lower():
                        snippets.append({"domain": domain, "snippet": text[:500]})
                        used_domains.append(domain)
            except Exception:
                continue
        return snippets, used_domains
