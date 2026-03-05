import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from dotenv import dotenv_values

log = logging.getLogger(__name__)

VALID_SELECTION_MODES = {"random", "cycle"}
SLACK_API_BASE = "https://slack.com/api"


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
    channels: list[ChannelConfig]
    default_selection_mode: str = "random"
    skip_dates: list[str] = field(default_factory=list)


@dataclass
class Credentials:
    xoxc_token: str
    d_cookie: str


def _validate_skip_dates(dates: list[str], context: str) -> list[str]:
    """Validate skip_dates entries are valid ISO format dates.

    Args:
        dates: List of date strings to validate.
        context: Description of where these dates come from (e.g., "global skip_dates")
                for error messages.

    Returns:
        The validated list of dates.

    Raises:
        ValueError: If any date is not in YYYY-MM-DD format.
    """
    for d in dates:
        try:
            date.fromisoformat(d)
        except ValueError:
            raise ValueError(
                f"Invalid skip_dates format in {context}: {d!r} "
                "(expected YYYY-MM-DD)"
            )
    return dates


def load_config(config_path: Path) -> AppConfig:
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ValueError(f"Config file is empty: {config_path}")

    default_mode = raw.get("default_selection_mode", "random")
    if default_mode not in VALID_SELECTION_MODES:
        raise ValueError(
            f"Invalid default_selection_mode: {default_mode!r} "
            f"(expected one of {sorted(VALID_SELECTION_MODES)})"
        )
    global_skip = _validate_skip_dates(raw.get("skip_dates", []), "global skip_dates")

    channels = []
    for idx, ch in enumerate(raw.get("channels", [])):
        if "id" not in ch:
            raise ValueError(
                f"Channel at index {idx} is missing required field 'id'"
            )
        channel_id = ch["id"]
        channel_name = ch.get("name", channel_id)
        schedules = []
        for s_idx, s in enumerate(ch.get("schedules", [])):
            if "cron" not in s:
                raise ValueError(
                    f"Channel '{channel_name}' schedule at index {s_idx} is missing required field 'cron'"
                )
            schedule_skip_dates = s.get("skip_dates", [])
            context = f"channel '{channel_name}' schedule {s_idx} skip_dates"
            validated_skip_dates = _validate_skip_dates(schedule_skip_dates, context)
            schedules.append(ScheduleConfig(
                cron=s["cron"],
                jitter_minutes=s.get("jitter_minutes", 0),
                skip_weekends=s.get("skip_weekends", False),
                skip_dates=validated_skip_dates,
            ))

        messages = ch.get("messages", [])

        if not schedules:
            log.warning(f"Channel {channel_name} ({channel_id}) has no schedules — it will never fire in daemon mode.")
        if not messages:
            log.warning(f"Channel {channel_name} ({channel_id}) has no messages defined.")

        selection_mode = ch.get("selection_mode", default_mode)
        if selection_mode not in VALID_SELECTION_MODES:
            raise ValueError(
                f"Channel '{channel_name}' has invalid selection_mode: {selection_mode!r} "
                f"(expected one of {sorted(VALID_SELECTION_MODES)})"
            )

        channels.append(ChannelConfig(
            id=channel_id,
            name=channel_name,
            messages=messages,
            schedules=schedules,
            selection_mode=selection_mode,
        ))

    return AppConfig(
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
    """Combine global and schedule-specific skip dates into a set of date objects.

    All dates are guaranteed to be valid ISO format strings (validated at config load time).
    """
    combined = set(global_dates) | set(schedule_dates)
    return {date.fromisoformat(d) for d in combined}
