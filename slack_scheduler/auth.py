import logging

import requests

from slack_scheduler.config import Credentials

log = logging.getLogger(__name__)


class TokenExpiredError(Exception):
    pass


class TokenInvalidError(Exception):
    pass


def validate_credentials(credentials: Credentials, workspace_url: str) -> None:
    try:
        response = requests.post(
            f"{workspace_url.rstrip('/')}/api/auth.test",
            headers={"Authorization": f"Bearer {credentials.xoxc_token}"},
            cookies={"d": credentials.d_cookie},
            timeout=15,
        )
        data = response.json()
    except requests.RequestException as e:
        raise TokenInvalidError(f"Failed to reach Slack API: {e}")

    if not data.get("ok"):
        error = data.get("error", "unknown")
        if error == "invalid_auth":
            raise TokenExpiredError(
                "Slack credentials have expired. Update your credentials file."
            )
        raise TokenInvalidError(f"Slack auth.test failed: {error}")

    user = data.get("user", "unknown")
    team = data.get("team", "unknown")
    log.info(f"Authenticated as {user} in workspace {team}")
