"""Unit tests for src.llm's retry predicate.

Regression coverage for a real failure: a 4,199-row Phase 2 run had 20 rows
(0.5%) fail on a bare httpx.ReadError (WinError 10054, connection reset)
that the original predicate -- APIError-only -- didn't retry, because a
transport-level error isn't an APIError. See METHODOLOGY.md.
"""
import httpx
from google.genai.errors import ClientError, ServerError

from src.llm import _is_retryable


def _api_error(code: int):
    return ServerError(code, {"error": {"message": "boom", "status": "UNAVAILABLE"}}) if code >= 500 else ClientError(
        code, {"error": {"message": "boom", "status": "RESOURCE_EXHAUSTED"}}
    )


def test_retries_rate_limit_and_server_errors():
    for code in (429, 500, 502, 503, 504):
        assert _is_retryable(_api_error(code)) is True


def test_does_not_retry_bad_request_or_auth_errors():
    for code in (400, 401, 403, 404):
        assert _is_retryable(_api_error(code)) is False


def test_retries_transport_level_connection_errors():
    assert _is_retryable(httpx.ReadError("connection reset")) is True
    assert _is_retryable(httpx.ConnectError("could not connect")) is True
    assert _is_retryable(TimeoutError("timed out")) is True
    assert _is_retryable(ConnectionError("reset")) is True


def test_does_not_retry_unrelated_exceptions():
    assert _is_retryable(ValueError("bad schema")) is False
    assert _is_retryable(KeyError("missing field")) is False
