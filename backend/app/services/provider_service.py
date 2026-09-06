import ipaddress, socket
from urllib.parse import urlparse
import httpx

def validate_base_url(kind:str,base_url:str,local_hosts:set[str])->str:
    value=base_url.rstrip("/"); parsed=urlparse(value); host=(parsed.hostname or "").lower()
    if not host or parsed.scheme not in {"http","https"} or parsed.username or parsed.password or parsed.query or parsed.fragment: raise ValueError("invalid_provider_url")
    if kind=="lm_studio":
        if host not in local_hosts:
            try:
                if not ipaddress.ip_address(host).is_private: raise ValueError("lm_studio_must_be_local")
            except ValueError as exc:
                if str(exc)=="lm_studio_must_be_local": raise
                raise ValueError("lm_studio_must_be_local") from exc
        return value
    if parsed.scheme!="https": raise ValueError("cloud_provider_requires_https")
    try:
        for row in socket.getaddrinfo(host,parsed.port or 443,proto=socket.IPPROTO_TCP):
            ip=ipaddress.ip_address(row[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: raise ValueError("cloud_provider_must_be_public")
    except socket.gaierror as exc: raise ValueError("provider_host_unresolvable") from exc
    return value

class OpenAIProvider:
    def __init__(self,base_url:str,api_key:str|None,timeout_s:int=30,retries:int=2,kind:str="openai_compatible",local_hosts:set[str]|None=None):
        self.kind=kind;self.local_hosts=local_hosts or set();self.base_url=validate_base_url(kind,base_url,self.local_hosts); self.api_key=api_key or ""; self.timeout=timeout_s; self.retries=retries;self.last_usage={}
    @property
    def headers(self): return {"Content-Type":"application/json",**({"Authorization":f"Bearer {self.api_key}"} if self.api_key else {})}
    async def _request(self,method:str,path:str,**kwargs):
        last_error=None
        for attempt in range(self.retries+1):
            try:
                self.base_url=validate_base_url(self.kind,self.base_url,self.local_hosts)
                parsed=urlparse(self.base_url);expected={row[4][0] for row in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=="https" else 80),proto=socket.IPPROTO_TCP)}
                async with httpx.AsyncClient(timeout=self.timeout,follow_redirects=False,trust_env=False) as c:
                    response=await c.request(method,f"{self.base_url}{path}",headers=self.headers,**kwargs)
                    response.raise_for_status()
                    stream=response.extensions.get("network_stream");address=stream.get_extra_info("server_addr") if stream and hasattr(stream,"get_extra_info") else None;peer=address[0] if address else None
                    if peer not in expected: raise httpx.NetworkError("provider_peer_mismatch")
                    return response
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {408,429,500,502,503,504} or attempt==self.retries: raise
                last_error=exc
            except (httpx.TimeoutException,httpx.NetworkError) as exc:
                last_error=exc
                if attempt==self.retries: raise
        raise RuntimeError("provider_request_failed") from last_error
    async def models(self):
        return (await self._request("GET","/models")).json().get("data",[])
    async def embeddings(self,model:str,texts:list[str]):
        r=await self._request("POST","/embeddings",json={"model":model,"input":texts}); return [x["embedding"] for x in r.json().get("data",[])]
    async def answer(self,model:str,messages:list[dict]):
        r=await self._request("POST","/chat/completions",json={"model":model,"messages":messages});payload=r.json();self.last_usage=payload.get("usage") or {};return payload["choices"][0]["message"]["content"]
    async def probe_chat(self,model:str)->bool:
        r=await self._request("POST","/chat/completions",json={"model":model,"messages":[{"role":"user","content":"Reply OK"}],"max_tokens":1});return bool(r.json().get("choices"))
