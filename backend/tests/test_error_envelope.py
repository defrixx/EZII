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
