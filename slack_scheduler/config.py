import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from dotenv import dotenv_values

log = logging.getLogger(__name__)


@dataclass
class ScheduleConfig:
    cron: str
    jitter_minutes: int = 0
    skip_weekends: bool = False
    skip_dates: list[str] = field(default_factory=list)


@dataclass
class ChannelConfig:
    id: str
    name: str
    messages: list[str]
    schedules: list[ScheduleConfig]
    selection_mode: str = "random"


@dataclass
class AppConfig:
    workspace_url: str
    channels: list[ChannelConfig]
    default_selection_mode: str = "random"
    skip_dates: list[str] = field(default_factory=list)


@dataclass
class Credentials:
    xoxc_token: str
    d_cookie: str


def load_config(config_path: Path) -> AppConfig:
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ValueError(f"Config file is empty: {config_path}")

    workspace_url = raw.get("workspace_url")
    if not workspace_url:
        raise ValueError("workspace_url is required in config")

    default_mode = raw.get("default_selection_mode", "random")
    global_skip = raw.get("skip_dates", [])

    channels = []
    for ch in raw.get("channels", []):
        schedules = []
        for s in ch.get("schedules", []):
            schedules.append(ScheduleConfig(
                cron=s["cron"],
                jitter_minutes=s.get("jitter_minutes", 0),
                skip_weekends=s.get("skip_weekends", False),
                skip_dates=s.get("skip_dates", []),
            ))

        channel_id = ch["id"]
        channel_name = ch.get("name", channel_id)
        messages = ch.get("messages", [])

        if not schedules:
            log.warning(f"Channel {channel_name} ({channel_id}) has no schedules — it will never fire in daemon mode.")
        if not messages:
            log.warning(f"Channel {channel_name} ({channel_id}) has no messages defined.")

        channels.append(ChannelConfig(
            id=channel_id,
            name=channel_name,
            messages=messages,
            schedules=schedules,
            selection_mode=ch.get("selection_mode", default_mode),
        ))

    return AppConfig(
        workspace_url=workspace_url,
        channels=channels,
        default_selection_mode=default_mode,
        skip_dates=global_skip,
    )


def load_credentials(env_path: Path) -> Credentials:
    if not env_path.exists():
        raise FileNotFoundError(
            f"Credentials file not found: {env_path}\n"
            "Run `slack-scheduler init` to create a template."
        )

    values = dotenv_values(env_path)
    token = values.get("SLACK_XOXC_TOKEN", "")
    cookie = values.get("SLACK_D_COOKIE", "")

    if not token or not cookie:
        raise ValueError(
            f"SLACK_XOXC_TOKEN and SLACK_D_COOKIE must be set in {env_path}. "
            "Run `slack-scheduler init` to create a template, then add your credentials."
        )

    return Credentials(xoxc_token=token, d_cookie=cookie)


def resolve_skip_dates(
    global_dates: list[str], schedule_dates: list[str]
) -> set[date]:
    combined = set(global_dates) | set(schedule_dates)
    result = set()
    for d in combined:
        try:
            result.add(date.fromisoformat(d))
        except ValueError:
            log.warning(f"Invalid skip_date format (expected YYYY-MM-DD): {d!r}")
    return result
