"""Tests for slack_scheduler.auth"""
import pytest
import requests as req_lib
from unittest.mock import MagicMock, patch

from slack_scheduler.auth import (
    TokenExpiredError,
    TokenInvalidError,
    validate_credentials,
)


def _mock_auth_response(ok: bool, extra: dict | None = None) -> MagicMock:
    r = MagicMock()
    payload = {"ok": ok}
    if extra:
        payload.update(extra)
    r.json.return_value = payload
    return r


class TestValidateCredentials:
    def test_success_does_not_raise(self, credentials_obj):
        with patch("slack_scheduler.auth.requests.post") as mock_post:
            mock_post.return_value = _mock_auth_response(True, {"user": "alice", "team": "ACME"})
            validate_credentials(credentials_obj)

    def test_posts_to_auth_test_endpoint(self, credentials_obj):
        with patch("slack_scheduler.auth.requests.post") as mock_post:
            mock_post.return_value = _mock_auth_response(True)
            validate_credentials(credentials_obj)
        assert mock_post.call_args[0][0] == "https://slack.com/api/auth.test"

    def test_invalid_auth_raises_token_expired(self, credentials_obj):
        with patch("slack_scheduler.auth.requests.post") as mock_post:
            mock_post.return_value = _mock_auth_response(False, {"error": "invalid_auth"})
            with pytest.raises(TokenExpiredError):
                validate_credentials(credentials_obj)

    def test_other_error_raises_token_invalid(self, credentials_obj):
        with patch("slack_scheduler.auth.requests.post") as mock_post:
            mock_post.return_value = _mock_auth_response(False, {"error": "account_inactive"})
            with pytest.raises(TokenInvalidError, match="account_inactive"):
                validate_credentials(credentials_obj)

    def test_missing_error_key_defaults_to_unknown(self, credentials_obj):
        with patch("slack_scheduler.auth.requests.post") as mock_post:
            mock_post.return_value = _mock_auth_response(False)
            with pytest.raises(TokenInvalidError, match="unknown"):
                validate_credentials(credentials_obj)

    def test_network_error_raises_token_invalid(self, credentials_obj):
        with patch("slack_scheduler.auth.requests.post",
                   side_effect=req_lib.ConnectionError("timeout")):
            with pytest.raises(TokenInvalidError, match="Failed to reach Slack API"):
                validate_credentials(credentials_obj)

    def test_sends_bearer_token(self, credentials_obj):
        with patch("slack_scheduler.auth.requests.post") as mock_post:
            mock_post.return_value = _mock_auth_response(True)
            validate_credentials(credentials_obj)
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == f"Bearer {credentials_obj.xoxc_token}"

    def test_sends_d_cookie(self, credentials_obj):
        with patch("slack_scheduler.auth.requests.post") as mock_post:
            mock_post.return_value = _mock_auth_response(True)
            validate_credentials(credentials_obj)
        assert mock_post.call_args.kwargs["cookies"]["d"] == credentials_obj.d_cookie

    def test_uses_15s_timeout(self, credentials_obj):
        with patch("slack_scheduler.auth.requests.post") as mock_post:
            mock_post.return_value = _mock_auth_response(True)
            validate_credentials(credentials_obj)
        assert mock_post.call_args.kwargs["timeout"] == 15


class TestExceptionClasses:
    def test_token_expired_is_exception(self):
        assert issubclass(TokenExpiredError, Exception)

    def test_token_invalid_is_exception(self):
        assert issubclass(TokenInvalidError, Exception)

    def test_they_are_distinct_classes(self):
        assert TokenExpiredError is not TokenInvalidError
