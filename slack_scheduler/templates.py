import logging
from datetime import datetime

log = logging.getLogger(__name__)


class _SafeDict(dict):
    """Returns the key placeholder for missing keys instead of raising."""

    def __missing__(self, key):
        return f"{{{key}}}"


def render(template: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    variables = _SafeDict(
        date=now.strftime("%Y-%m-%d"),
        day_of_week=now.strftime("%A"),
        time=now.strftime("%H:%M"),
    )
    try:
        return template.format_map(variables)
    except ValueError:
        log.warning(f"Failed to render template (bad format syntax), sending as-is: {template!r}")
        return template
