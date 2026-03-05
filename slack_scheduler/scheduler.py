import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from slack_scheduler.config import AppConfig, Credentials, resolve_skip_dates
from slack_scheduler.selector import pick_message
from slack_scheduler.sender import send_message
from slack_scheduler.templates import render

log = logging.getLogger(__name__)


def run_daemon(
    config: AppConfig,
    credentials: Credentials,
    dry_run: bool = False,
) -> None:
    scheduler = BlockingScheduler()

    for channel in config.channels:
        for i, schedule in enumerate(channel.schedules):
            skip_dates = resolve_skip_dates(config.skip_dates, schedule.skip_dates)

            scheduler.add_job(
                _fire,
                trigger=CronTrigger.from_crontab(schedule.cron),
                jitter=schedule.jitter_minutes * 60 if schedule.jitter_minutes else None,
                args=[channel.id, channel.name, channel.messages, channel.selection_mode,
                      schedule.skip_weekends, skip_dates, credentials, dry_run],
                id=f"{channel.id}_{i}",
                name=f"{channel.name} ({schedule.cron})",
            )
            log.info(
                f"Scheduled: {channel.name} ({schedule.cron})"
                f"{f', up to {schedule.jitter_minutes}min jitter' if schedule.jitter_minutes else ''}"
            )

    job_count = len(scheduler.get_jobs())
    if job_count == 0:
        log.warning("No schedules configured. Nothing to do.")
        return

    mode = "[DRY RUN] " if dry_run else ""
    log.info(f"{mode}Starting scheduler with {job_count} job(s). Press Ctrl-C to stop.")
    scheduler.start()


def _fire(
    channel_id: str,
    channel_name: str,
    messages: list[str],
    selection_mode: str,
    skip_weekends: bool,
    skip_dates: set[date],
    credentials: Credentials,
    dry_run: bool,
) -> None:
    today = date.today()

    if skip_weekends and today.weekday() >= 5:
        log.info(f"Skipping {channel_name}: weekend")
        return

    if today in skip_dates:
        log.info(f"Skipping {channel_name}: {today} is in skip_dates")
        return

    message = pick_message(channel_id, messages, selection_mode)
    message = render(message, datetime.now())

    result = send_message(
        channel_id=channel_id,
        message=message,
        credentials=credentials,
        dry_run=dry_run,
    )

    if result.ok and not dry_run:
        log.info(f"Sent to {channel_name}: {message!r} (ts={result.ts})")
    elif not result.ok:
        log.error(f"Failed to send to {channel_name}: {result.error_code}")


def print_upcoming(config: AppConfig, count: int = 5) -> None:
    if not config.channels:
        print("No schedules configured.")
        return

    print(f"\nUpcoming scheduled messages (next {count} per schedule):\n")

    for channel in config.channels:
        for schedule in channel.schedules:
            trigger = CronTrigger.from_crontab(schedule.cron)
            skip_dates = resolve_skip_dates(config.skip_dates, schedule.skip_dates)
            label = f"{channel.name} ({schedule.cron})"
            if schedule.jitter_minutes:
                label += f" up to {schedule.jitter_minutes}min jitter"

            print(f"  {label}")

            now = datetime.now(tz=trigger.timezone)
            upcoming = []
            cursor = now
            iterations = 0
            while len(upcoming) < count and iterations < 1000:
                iterations += 1
                next_time = trigger.get_next_fire_time(cursor, cursor)
                if next_time is None:
                    break
                cursor = next_time + timedelta(seconds=1)
                if schedule.skip_weekends and next_time.date().weekday() >= 5:
                    continue
                if next_time.date() in skip_dates:
                    continue
                upcoming.append(next_time)

            for t in upcoming:
                print(f"    - {t.strftime('%Y-%m-%d %H:%M:%S')}")
            print()
