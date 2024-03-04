import logging
import time
from dataclasses import dataclass

import requests

from slack_scheduler.auth import TokenExpiredError
from slack_scheduler.config import Credentials

log = logging.getLogger(__name__)


class SlackAPIError(Exception):
    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__(f"Slack API error: {error_code}")


@dataclass
class SendResult:
    ok: bool
    channel_id: str
    message: str
    ts: str | None = None
    error_code: str | None = None


def send_message(
    channel_id: str,
    message: str,
    credentials: Credentials,
    workspace_url: str,
    dry_run: bool = False,
    max_attempts: int = 3,
    max_rate_limit_retries: int = 5,
) -> SendResult:
    if dry_run:
        log.info(f"[DRY RUN] Would send to {channel_id}: {message!r}")
        return SendResult(ok=True, channel_id=channel_id, message=message)

    attempt = 0
    rate_limit_retries = 0

    while attempt < max_attempts:
        attempt += 1
        try:
            response = _post(channel_id, message, credentials, workspace_url)
            try:
                data = response.json()
            except (ValueError, requests.JSONDecodeError):
                response.raise_for_status()
                raise

            if data.get("ok"):
                return SendResult(
                    ok=True,
                    channel_id=channel_id,
                    message=message,
                    ts=data.get("ts"),
                )

            error = data.get("error", "unknown")

            if error == "invalid_auth":
                raise TokenExpiredError(
                    "Slack token has expired. Update your credentials file."
                )

            if error == "ratelimited":
                rate_limit_retries += 1
                if rate_limit_retries > max_rate_limit_retries:
                    log.error(
                        f"Rate limited {rate_limit_retries} times, giving up."
                    )
                    return SendResult(
                        ok=False,
                        channel_id=channel_id,
                        message=message,
                        error_code="ratelimited",
                    )
                retry_after = int(response.headers.get("Retry-After", 1))
                log.warning(
                    f"Rate limited. Retrying in {retry_after}s "
                    f"(rate limit retry {rate_limit_retries}/{max_rate_limit_retries})."
                )
                time.sleep(retry_after)
                # Don't count rate limits against the attempt budget
                attempt -= 1
                continue

            raise SlackAPIError(error)

        except requests.RequestException as e:
            if attempt == max_attempts:
                raise
            backoff = 2 ** attempt
            log.warning(
                f"Request failed (attempt {attempt}/{max_attempts}): {e}. "
                f"Retrying in {backoff}s."
            )
            time.sleep(backoff)

    raise AssertionError("Unreachable: all attempts should return or raise")


def _post(
    channel_id: str,
    message: str,
    credentials: Credentials,
    workspace_url: str,
) -> requests.Response:
    response = requests.post(
        f"{workspace_url.rstrip('/')}/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {credentials.xoxc_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        cookies={"d": credentials.d_cookie},
        json={"channel": channel_id, "text": message},
        timeout=30,
    )
    return response
