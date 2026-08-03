from fastapi import FastAPI

from app.api.routers.health import health
from main import app


EXPECTED_ROUTES = {
    ("GET", "/health"),
    ("GET", "/recommend"),
    ("POST", "/gifticons/{gifticon_id}/purchase"),
    ("POST", "/point-payments/{point_package_id}/prepare"),
    ("POST", "/point-payments/{payment_id}/complete"),
    ("POST", "/stamp-verifications"),
    ("POST", "/dev/stamps/issue"),
}


def test_public_api_contract_remains_available() -> None:
    assert isinstance(app, FastAPI)

    openapi_paths = app.openapi()["paths"]
    actual_routes = {
        (method.upper(), path)
        for path, operations in openapi_paths.items()
        for method in operations
    }

    assert actual_routes == EXPECTED_ROUTES


def test_health_endpoint_returns_ok() -> None:
    assert health() == {"status": "ok"}
