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


@dataclass
class ChannelConfig:
    id: str
    name: str
    messages: list[str]
    schedules: list[ScheduleConfig]
    selection_mode: str = "random"
    skip_weekends: bool = False
    skip_dates: list[str] = field(default_factory=list)
    skip_holidays: str | None = None


@dataclass
class AppConfig:
    channels: list[ChannelConfig]
    default_selection_mode: str = "random"
    skip_weekends: bool = False
    skip_dates: list[str] = field(default_factory=list)
    skip_holidays: str | None = None


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


def _validate_messages(messages: object, context: str) -> list[str]:
    if not isinstance(messages, list):
        raise ValueError(
            f"Invalid messages in {context}: expected a list of strings"
        )
    if not all(isinstance(message, str) for message in messages):
        raise ValueError(
            f"Invalid messages in {context}: every message must be a string"
        )
    return messages


def _parse_holidays_code(code: str) -> tuple[str, str | None]:
    if "-" in code:
        country, subdiv = code.split("-", 1)
        return country, subdiv
    return code, None


def _validate_skip_holidays(value: str | None, context: str) -> str | None:
    if value is None:
        return None

    import holidays

    country, subdiv = _parse_holidays_code(value)
    try:
        holidays.country_holidays(country, subdiv=subdiv, years=2000)
    except NotImplementedError:
        msg = f"Invalid skip_holidays in {context}: {value!r}"
        if subdiv:
            msg += f" (country {country!r} or subdivision {subdiv!r} not recognized)"
        else:
            msg += " (country code not recognized)"
        raise ValueError(msg)

    return value


def _get_holiday_dates(holidays_code: str) -> set[date]:
    import holidays

    current_year = date.today().year
    country, subdiv = _parse_holidays_code(holidays_code)
    holiday_dict = holidays.country_holidays(
        country, subdiv=subdiv, years=[current_year, current_year + 1]
    )
    return set(holiday_dict.keys())


def _validate_cron(cron: str, context: str) -> str:
    from apscheduler.triggers.cron import CronTrigger

    try:
        CronTrigger.from_crontab(cron)
    except ValueError as e:
        raise ValueError(f"Invalid cron in {context}: {cron!r} ({e})")
    return cron


def _validate_jitter_minutes(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"Invalid jitter_minutes in {context}: expected a non-negative integer"
        )
    if value < 0:
        raise ValueError(
            f"Invalid jitter_minutes in {context}: expected a non-negative integer"
        )
    return value


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
    global_skip_weekends = raw.get("skip_weekends", False)
    global_skip = _validate_skip_dates(raw.get("skip_dates", []), "global skip_dates")
    global_skip_holidays = _validate_skip_holidays(
        raw.get("skip_holidays"), "global skip_holidays"
    )

    raw_channels = raw.get("channels", [])
    if not isinstance(raw_channels, list):
        raise ValueError("Invalid channels: expected a list")

    channels = []
    for idx, ch in enumerate(raw_channels):
        if not isinstance(ch, dict):
            raise ValueError(
                f"Channel at index {idx} must be a mapping"
            )
        if "id" not in ch:
            raise ValueError(
                f"Channel at index {idx} is missing required field 'id'"
            )
        channel_id = ch["id"]
        channel_name = ch.get("name", channel_id)

        channel_skip_weekends = ch.get("skip_weekends", False)
        channel_skip_dates = _validate_skip_dates(
            ch.get("skip_dates", []),
            f"channel '{channel_name}' skip_dates",
        )
        channel_skip_holidays = _validate_skip_holidays(
            ch.get("skip_holidays"),
            f"channel '{channel_name}' skip_holidays",
        )

        raw_schedules = ch.get("schedules", [])
        if not isinstance(raw_schedules, list):
            raise ValueError(
                f"Channel '{channel_name}' schedules must be a list"
            )

        schedules = []
        for s_idx, s in enumerate(raw_schedules):
            if not isinstance(s, dict):
                raise ValueError(
                    f"Channel '{channel_name}' schedule at index {s_idx} must be a mapping"
                )
            if "cron" not in s:
                raise ValueError(
                    f"Channel '{channel_name}' schedule at index {s_idx} is missing required field 'cron'"
                )
            schedules.append(ScheduleConfig(
                cron=_validate_cron(
                    s["cron"],
                    f"channel '{channel_name}' schedule at index {s_idx}",
                ),
                jitter_minutes=_validate_jitter_minutes(
                    s.get("jitter_minutes", 0),
                    f"channel '{channel_name}' schedule at index {s_idx}",
                ),
            ))

        messages = _validate_messages(
            ch.get("messages", []),
            f"channel '{channel_name}'",
        )

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
            skip_weekends=channel_skip_weekends,
            skip_dates=channel_skip_dates,
            skip_holidays=channel_skip_holidays,
        ))

    seen_names: set[str] = set()
    for ch in channels:
        if ch.name in seen_names:
            raise ValueError(
                f"Duplicate channel name: {ch.name!r}. "
                "Each channel entry must have a unique name."
            )
        seen_names.add(ch.name)

    return AppConfig(
        channels=channels,
        default_selection_mode=default_mode,
        skip_weekends=global_skip_weekends,
        skip_dates=global_skip,
        skip_holidays=global_skip_holidays,
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
    global_dates: list[str],
    channel_dates: list[str],
    global_holidays: str | None = None,
    channel_holidays: str | None = None,
) -> set[date]:
    """Combine global and entry-specific skip dates into a set of date objects.

    All dates are guaranteed to be valid ISO format strings (validated at config load time).
    If skip_holidays is specified, the corresponding country holidays are merged in.
    """
    combined = set(global_dates) | set(channel_dates)
    result = {date.fromisoformat(d) for d in combined}

    for holidays_code in (global_holidays, channel_holidays):
        if holidays_code is not None:
            result |= _get_holiday_dates(holidays_code)

    return result
