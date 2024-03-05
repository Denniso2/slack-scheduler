"""Tests for slack_scheduler.sender"""
import pytest
import requests as req_lib
from unittest.mock import call, patch

from slack_scheduler.auth import TokenExpiredError
from slack_scheduler.sender import SendResult, SlackAPIError, _post, send_message
from tests.conftest import make_rate_limited_response, make_slack_response

WORKSPACE = "https://test.slack.com"


# --- SlackAPIError -----------------------------------------------------------

def test_slack_api_error_stores_error_code():
    err = SlackAPIError("channel_not_found")
    assert err.error_code == "channel_not_found"
    assert "channel_not_found" in str(err)


# --- SendResult defaults ----------------------------------------------------

def test_send_result_defaults():
    r = SendResult(ok=True, channel_id="C1", message="hi")
    assert r.ts is None
    assert r.error_code is None


# --- send_message: dry_run ---------------------------------------------------

class TestDryRun:
    def test_returns_ok_without_posting(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            result = send_message("C1", "hello", credentials_obj, WORKSPACE, dry_run=True)
        mock_post.assert_not_called()
        assert result.ok is True
        assert result.channel_id == "C1"
        assert result.message == "hello"


# --- send_message: success ---------------------------------------------------

class TestSuccess:
    def test_returns_ok_with_ts(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(True, {"ts": "123.456"})
            result = send_message("C1", "hi", credentials_obj, WORKSPACE)
        assert result.ok is True
        assert result.ts == "123.456"

    def test_single_attempt_on_first_success(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(True, {"ts": "1"})
            send_message("C1", "hi", credentials_obj, WORKSPACE)
        assert mock_post.call_count == 1


# --- send_message: retry on network error -----------------------------------

class TestRetry:
    def test_retries_then_succeeds(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post, \
             patch("slack_scheduler.sender.time.sleep"):
            mock_post.side_effect = [
                req_lib.ConnectionError("timeout"),
                make_slack_response(True, {"ts": "1"}),
            ]
            result = send_message("C1", "hi", credentials_obj, WORKSPACE, max_attempts=3)
        assert result.ok is True
        assert mock_post.call_count == 2

    def test_raises_after_all_attempts_exhausted(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post, \
             patch("slack_scheduler.sender.time.sleep"):
            mock_post.side_effect = req_lib.ConnectionError("down")
            with pytest.raises(req_lib.ConnectionError):
                send_message("C1", "hi", credentials_obj, WORKSPACE, max_attempts=3)
        assert mock_post.call_count == 3

    def test_exponential_backoff(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post, \
             patch("slack_scheduler.sender.time.sleep") as mock_sleep:
            mock_post.side_effect = req_lib.ConnectionError("e")
            with pytest.raises(req_lib.ConnectionError):
                send_message("C1", "hi", credentials_obj, WORKSPACE, max_attempts=3)
        # backoff = 2**attempt where attempt is already incremented:
        # attempt=1 fail -> sleep(2**1=2), attempt=2 fail -> sleep(2**2=4), attempt=3 -> raise
        assert mock_sleep.call_args_list == [call(2), call(4)]


# --- send_message: rate limiting --------------------------------------------

class TestRateLimit:
    def test_retries_on_rate_limit_then_succeeds(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post, \
             patch("slack_scheduler.sender.time.sleep"):
            mock_post.side_effect = [
                make_rate_limited_response(retry_after=1),
                make_slack_response(True, {"ts": "1"}),
            ]
            result = send_message("C1", "hi", credentials_obj, WORKSPACE,
                                  max_rate_limit_retries=5)
        assert result.ok is True

    def test_sleeps_for_retry_after_header_value(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post, \
             patch("slack_scheduler.sender.time.sleep") as mock_sleep:
            mock_post.side_effect = [
                make_rate_limited_response(retry_after=30),
                make_slack_response(True, {"ts": "1"}),
            ]
            send_message("C1", "hi", credentials_obj, WORKSPACE,
                         max_rate_limit_retries=5)
        mock_sleep.assert_called_once_with(30)

    def test_gives_up_after_max_rate_limit_retries(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post, \
             patch("slack_scheduler.sender.time.sleep"):
            mock_post.return_value = make_rate_limited_response()
            result = send_message("C1", "hi", credentials_obj, WORKSPACE,
                                  max_rate_limit_retries=2)
        assert result.ok is False
        assert result.error_code == "ratelimited"
        # Should attempt max_rate_limit_retries + 1 times (retries 1,2 then give up on 3)
        assert mock_post.call_count == 3

    def test_rate_limits_do_not_consume_attempt_budget(self, credentials_obj):
        """3 rate limits followed by success should work with max_attempts=1."""
        with patch("slack_scheduler.sender.requests.post") as mock_post, \
             patch("slack_scheduler.sender.time.sleep"):
            mock_post.side_effect = [
                make_rate_limited_response(),
                make_rate_limited_response(),
                make_rate_limited_response(),
                make_slack_response(True, {"ts": "ok"}),
            ]
            result = send_message("C1", "hi", credentials_obj, WORKSPACE,
                                  max_attempts=1, max_rate_limit_retries=5)
        assert result.ok is True


# --- send_message: API errors -----------------------------------------------

class TestAPIErrors:
    def test_invalid_auth_raises_token_expired(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(False, {"error": "invalid_auth"})
            with pytest.raises(TokenExpiredError):
                send_message("C1", "hi", credentials_obj, WORKSPACE)

    @pytest.mark.parametrize("error_code", [
        "channel_not_found",
        "not_in_channel",
        "msg_too_long",
    ])
    def test_other_errors_raise_slack_api_error(self, credentials_obj, error_code):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(False, {"error": error_code})
            with pytest.raises(SlackAPIError) as exc_info:
                send_message("C1", "hi", credentials_obj, WORKSPACE)
        assert exc_info.value.error_code == error_code

    def test_missing_error_key_defaults_to_unknown(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(False)
            with pytest.raises(SlackAPIError) as exc_info:
                send_message("C1", "hi", credentials_obj, WORKSPACE)
        assert exc_info.value.error_code == "unknown"


# --- send_message: JSON decode failure --------------------------------------

class TestJSONDecodeFailure:
    def test_non_json_response_falls_back_to_raise_for_status(self, credentials_obj):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.json.side_effect = ValueError("No JSON")
        response.raise_for_status.side_effect = req_lib.HTTPError("502 Bad Gateway")
        with patch("slack_scheduler.sender.requests.post", return_value=response), \
             patch("slack_scheduler.sender.time.sleep"):
            with pytest.raises(req_lib.HTTPError):
                send_message("C1", "hi", credentials_obj, WORKSPACE, max_attempts=1)


# --- _post: payload shape ---------------------------------------------------

class TestPost:
    def test_url_construction(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(True)
            _post("C1", "hi", credentials_obj, "https://test.slack.com")
        assert mock_post.call_args[0][0] == "https://test.slack.com/api/chat.postMessage"

    def test_strips_trailing_slash(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(True)
            _post("C1", "hi", credentials_obj, "https://test.slack.com/")
        url = mock_post.call_args[0][0]
        assert "//api" not in url

    def test_sends_bearer_token(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(True)
            _post("C1", "hi", credentials_obj, WORKSPACE)
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == f"Bearer {credentials_obj.xoxc_token}"

    def test_sends_d_cookie(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(True)
            _post("C1", "hi", credentials_obj, WORKSPACE)
        assert mock_post.call_args.kwargs["cookies"]["d"] == credentials_obj.d_cookie

    def test_sends_channel_and_text_in_body(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(True)
            _post("C1", "hello", credentials_obj, WORKSPACE)
        body = mock_post.call_args.kwargs["json"]
        assert body == {"channel": "C1", "text": "hello"}

    def test_uses_30s_timeout(self, credentials_obj):
        with patch("slack_scheduler.sender.requests.post") as mock_post:
            mock_post.return_value = make_slack_response(True)
            _post("C1", "hi", credentials_obj, WORKSPACE)
        assert mock_post.call_args.kwargs["timeout"] == 30
