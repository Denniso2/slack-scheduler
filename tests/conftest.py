"""Shared fixtures for slack-scheduler tests."""
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slack_scheduler.config import (
    AppConfig,
    ChannelConfig,
    Credentials,
    ScheduleConfig,
)


# ---------------------------------------------------------------------------
# Auth / credential fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def credentials_obj() -> Credentials:
    """A valid in-memory Credentials object. No filesystem I/O."""
    return Credentials(
        xoxc_token="xoxc-test-token-abc123",
        d_cookie="xoxd-test-cookie-def456",
    )


@pytest.fixture
def mock_creds_env(tmp_path: Path) -> Path:
    """A real .env file on disk containing valid credential values."""
    env_file = tmp_path / "credentials.env"
    env_file.write_text(
        "SLACK_XOXC_TOKEN=xoxc-test-token-abc123\n"
        "SLACK_D_COOKIE=xoxd-test-cookie-def456\n"
    )
    return env_file


@pytest.fixture
def empty_creds_env(tmp_path: Path) -> Path:
    """A .env file with empty values."""
    env_file = tmp_path / "credentials.env"
    env_file.write_text(
        "SLACK_XOXC_TOKEN=\n"
        "SLACK_D_COOKIE=\n"
    )
    return env_file


# ---------------------------------------------------------------------------
# Config YAML fixtures
# ---------------------------------------------------------------------------

MINIMAL_CONFIG_YAML = textwrap.dedent("""\
    workspace_url: "https://test.slack.com"
    channels:
      - id: "C111"
        name: "general"
        messages:
          - "Hello!"
        schedules:
          - cron: "0 9 * * 1-5"
""")

FULL_CONFIG_YAML = textwrap.dedent("""\
    workspace_url: "https://test.slack.com"
    default_selection_mode: "cycle"
    skip_dates:
      - "2026-12-25"
      - "2026-01-01"
    channels:
      - id: "C111"
        name: "standup"
        messages:
          - "Good morning!"
          - "Rise and shine!"
        selection_mode: "cycle"
        schedules:
          - cron: "0 9 * * 1-5"
            jitter_minutes: 10
            skip_weekends: true
            skip_dates:
              - "2026-07-04"
      - id: "C222"
        name: "random-chat"
        messages:
          - "Hello world"
        selection_mode: "random"
        schedules:
          - cron: "0 14 * * 3"
""")


@pytest.fixture
def minimal_config_file(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(MINIMAL_CONFIG_YAML)
    return p


@pytest.fixture
def full_config_file(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(FULL_CONFIG_YAML)
    return p


# ---------------------------------------------------------------------------
# In-memory config object fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def schedule_config() -> ScheduleConfig:
    return ScheduleConfig(
        cron="0 9 * * 1-5",
        jitter_minutes=0,
        skip_weekends=False,
        skip_dates=[],
    )


@pytest.fixture
def channel_config(schedule_config: ScheduleConfig) -> ChannelConfig:
    return ChannelConfig(
        id="C111",
        name="general",
        messages=["Hello!", "World!"],
        schedules=[schedule_config],
        selection_mode="random",
    )


@pytest.fixture
def app_config(channel_config: ChannelConfig) -> AppConfig:
    return AppConfig(
        workspace_url="https://test.slack.com",
        channels=[channel_config],
        default_selection_mode="random",
        skip_dates=[],
    )


# ---------------------------------------------------------------------------
# HTTP response mock helpers (functions, not fixtures, for use in side_effect)
# ---------------------------------------------------------------------------

def make_slack_response(ok: bool, extra: dict | None = None) -> MagicMock:
    """Build a MagicMock mimicking a requests.Response for Slack API calls."""
    response = MagicMock()
    payload = {"ok": ok}
    if extra:
        payload.update(extra)
    response.json.return_value = payload
    response.headers = {}
    response.status_code = 200
    return response


def make_rate_limited_response(retry_after: int = 1) -> MagicMock:
    """A mock response signaling Slack rate limiting."""
    response = MagicMock()
    response.json.return_value = {"ok": False, "error": "ratelimited"}
    response.headers = {"Retry-After": str(retry_after)}
    response.status_code = 429
    return response
