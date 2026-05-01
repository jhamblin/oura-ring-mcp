"""Tests for OuraClient: success, error mapping, pagination, header redaction."""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from oura_ring_mcp.client import BASE_URL, OuraAPIError, OuraClient, _RedactAuthHeader


@respx.mock
async def test_get_returns_parsed_json():
    respx.get(f"{BASE_URL}/personal_info").mock(
        return_value=httpx.Response(200, json={"age": 40, "sex": "male"})
    )
    async with OuraClient("token") as c:
        data = await c.get("personal_info")
    assert data == {"age": 40, "sex": "male"}


@respx.mock
async def test_get_non_200_raises_api_error():
    respx.get(f"{BASE_URL}/personal_info").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )
    async with OuraClient("token") as c:
        with pytest.raises(OuraAPIError) as exc:
            await c.get("personal_info")
    assert exc.value.status == 401
    assert exc.value.endpoint == "personal_info"
    assert "Unauthorized" in exc.value.body


@respx.mock
async def test_authorization_header_sent():
    route = respx.get(f"{BASE_URL}/personal_info").mock(
        return_value=httpx.Response(200, json={})
    )
    async with OuraClient("my-secret-token") as c:
        await c.get("personal_info")
    assert route.calls[0].request.headers["Authorization"] == "Bearer my-secret-token"


@respx.mock
async def test_get_all_walks_next_token():
    route = respx.get(f"{BASE_URL}/sleep")
    route.mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": 1}], "next_token": "abc"}),
            httpx.Response(200, json={"data": [{"id": 2}, {"id": 3}], "next_token": None}),
        ]
    )
    async with OuraClient("token") as c:
        items = await c.get_all("sleep", {"start_date": "2026-04-01"})
    assert items == [{"id": 1}, {"id": 2}, {"id": 3}]
    # Second call should include the next_token plus the original params.
    second_url = str(route.calls[1].request.url)
    assert "next_token=abc" in second_url
    assert "start_date=2026-04-01" in second_url


@respx.mock
async def test_get_all_single_page():
    respx.get(f"{BASE_URL}/personal_info").mock(
        return_value=httpx.Response(200, json={"data": [{"x": 1}]})
    )
    async with OuraClient("token") as c:
        items = await c.get_all("personal_info")
    assert items == [{"x": 1}]


@respx.mock
async def test_get_all_propagates_errors():
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(500, text="boom"))
    async with OuraClient("token") as c:
        with pytest.raises(OuraAPIError):
            await c.get_all("sleep", {"start_date": "2026-04-01"})


def _make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="httpx",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_redact_filter_removes_bearer_token():
    f = _RedactAuthHeader()
    rec = _make_record("GET /personal_info Authorization: Bearer abc123-supersecret-token")
    f.filter(rec)
    assert "abc123" not in rec.getMessage()
    assert "supersecret" not in rec.getMessage()
    assert "REDACTED" in rec.getMessage()


def test_redact_filter_removes_bare_bearer():
    f = _RedactAuthHeader()
    rec = _make_record("headers={'Authorization': 'Bearer my.secret.jwt'}")
    f.filter(rec)
    assert "my.secret.jwt" not in rec.getMessage()


def test_redact_filter_passes_through_innocuous_messages():
    f = _RedactAuthHeader()
    rec = _make_record("Connecting to api.ouraring.com")
    assert f.filter(rec) is True
    assert rec.getMessage() == "Connecting to api.ouraring.com"


def test_redact_filter_installed_on_httpx_logger():
    """Module import should have installed the filter on the relevant loggers."""
    httpx_logger = logging.getLogger("httpx")
    assert any(isinstance(f, _RedactAuthHeader) for f in httpx_logger.filters)
