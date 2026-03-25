from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from app.main import app


def test_global_http_exception_envelope_contains_request_id():
    router = APIRouter()

    @router.get("/_test/http-error")
    def _http_error():
        raise HTTPException(status_code=418, detail="teapot")

    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    response = client.get("/api/v1/_test/http-error")
    assert response.status_code == 418
    assert response.headers.get("x-request-id")
    payload = response.json()
    assert payload["detail"] == "teapot"
    assert payload["error"]["code"] == "http_error"
    assert payload["error"]["message"] == "teapot"
    assert payload["error"]["request_id"]


def test_global_validation_error_envelope_contains_request_id():
    client = TestClient(app)

    response = client.post("/api/v1/auth/register", json={})
    assert response.status_code == 422
    assert response.headers.get("x-request-id")
    payload = response.json()
    assert payload["detail"] == "Invalid input data"
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["request_id"]
    assert isinstance(payload["error"]["detail"], list)


def test_validation_error_envelope_does_not_include_raw_input_values():
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": {"raw": "StrongPass123!"}},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    detail = payload["error"]["detail"]

    def _contains_input_key(value):
        if isinstance(value, dict):
            if "input" in value:
                return True
            return any(_contains_input_key(v) for v in value.values())
        if isinstance(value, list):
            return any(_contains_input_key(v) for v in value)
        return False

    assert not _contains_input_key(detail)
