from starlette.requests import Request

from app.api.v1.auth import _request_ip
from app.core.rate_limit import _client_ip


def _request(headers: list[tuple[bytes, bytes]], client: tuple[str, int] = ("127.0.0.1", 1234)) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": client,
    }
    return Request(scope)


def test_rate_limit_uses_left_most_forwarded_for_ip():
    request = _request([(b"x-forwarded-for", b"1.1.1.1, 2.2.2.2")])
    assert _client_ip(request) == "1.1.1.1"


def test_auth_request_ip_uses_left_most_forwarded_for_ip():
    request = _request([(b"x-forwarded-for", b"1.1.1.1, 2.2.2.2")])
    assert _request_ip(request) == "1.1.1.1"


def test_untrusted_proxy_ignores_forwarded_for():
    request = _request(
        [(b"x-forwarded-for", b"1.1.1.1, 2.2.2.2")],
        client=("203.0.113.10", 1234),
    )
    assert _client_ip(request) == "203.0.113.10"
    assert _request_ip(request) == "203.0.113.10"


def test_docker_proxy_ip_is_treated_as_trusted():
    request = _request(
        [(b"x-forwarded-for", b"1.1.1.1, 2.2.2.2")],
        client=("172.18.0.5", 1234),
    )
    assert _client_ip(request) == "1.1.1.1"
    assert _request_ip(request) == "1.1.1.1"
