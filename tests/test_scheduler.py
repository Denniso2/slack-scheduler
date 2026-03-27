"""Tests for slack_scheduler.scheduler"""
import re
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from slack_scheduler.auth import TokenExpiredError
from slack_scheduler.config import AppConfig, ChannelConfig, ScheduleConfig
from slack_scheduler.scheduler import _fire, print_upcoming, run_daemon
from slack_scheduler.sender import SendResult, SlackAPIError


# --- run_daemon: job registration -------------------------------------------

class TestRunDaemon:
    def test_registers_one_job_per_schedule(self, app_config, credentials_obj):
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(app_config, credentials_obj, dry_run=True)
        instance.add_job.assert_called_once()

    def test_registers_multiple_schedules(self, credentials_obj):
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[
                ScheduleConfig(cron="0 9 * * 1-5"),
                ScheduleConfig(cron="0 14 * * 3"),
            ],
        )
        config = AppConfig(channels=[channel])
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock(), MagicMock()]
            run_daemon(config, credentials_obj)
        assert instance.add_job.call_count == 2

    def test_no_schedules_does_not_start(self, credentials_obj):
        config = AppConfig(channels=[])
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = []
            run_daemon(config, credentials_obj)
        instance.start.assert_not_called()

    def test_job_id_format(self, app_config, credentials_obj):
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(app_config, credentials_obj)
        assert instance.add_job.call_args.kwargs["id"] == "general_0"

    def test_jitter_seconds_passed(self, credentials_obj):
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *", jitter_minutes=15)],
        )
        config = AppConfig(channels=[channel])
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(config, credentials_obj)
        assert instance.add_job.call_args.kwargs["jitter"] == 15 * 60

    def test_zero_jitter_passes_none(self, app_config, credentials_obj):
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(app_config, credentials_obj)
        assert instance.add_job.call_args.kwargs["jitter"] is None

    def test_skips_channels_with_no_messages(self, credentials_obj):
        channel = ChannelConfig(
            id="C1", name="empty", messages=[],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
        )
        config = AppConfig(channels=[channel])
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = []
            run_daemon(config, credentials_obj)
        instance.add_job.assert_not_called()
        instance.start.assert_not_called()

    def test_jitter_minutes_passed_in_args(self, credentials_obj):
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *", jitter_minutes=15)],
        )
        config = AppConfig(channels=[channel])
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(config, credentials_obj)
        # jitter_minutes is the last positional arg
        args = instance.add_job.call_args.kwargs["args"]
        assert args[-1] == 15

    def test_zero_jitter_minutes_passed_in_args(self, app_config, credentials_obj):
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(app_config, credentials_obj)
        args = instance.add_job.call_args.kwargs["args"]
        assert args[-1] == 0


# --- _fire: skip logic -------------------------------------------------------

CREDS = MagicMock()


def _make_fire_kwargs(**overrides):
    base = dict(
        channel_id="C1", channel_name="general", messages=["hi"],
        selection_mode="random", skip_weekends=False, skip_dates=set(),
        credentials=CREDS, dry_run=False,
    )
    base.update(overrides)
    return base


def _mock_now(dt):
    """Return a patch context that makes datetime.now() return *dt*."""
    return patch(
        "slack_scheduler.scheduler.datetime",
        wraps=datetime,
        **{"now.return_value": dt},
    )


class TestFire:
    def test_sends_on_normal_weekday(self):
        monday = datetime(2026, 3, 2, 9, 0)
        with _mock_now(monday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi", ts="1")) as mock_send:
            _fire(**_make_fire_kwargs())
        mock_send.assert_called_once()

    def test_skips_saturday_when_skip_weekends(self):
        saturday = datetime(2026, 3, 7, 10, 0)
        with _mock_now(saturday), \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            _fire(**_make_fire_kwargs(skip_weekends=True))
        mock_send.assert_not_called()

    def test_skips_sunday_when_skip_weekends(self):
        sunday = datetime(2026, 3, 8, 10, 0)
        with _mock_now(sunday), \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            _fire(**_make_fire_kwargs(skip_weekends=True))
        mock_send.assert_not_called()

    def test_sends_on_weekend_when_skip_weekends_false(self):
        saturday = datetime(2026, 3, 7, 10, 0)
        with _mock_now(saturday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi")) as mock_send:
            _fire(**_make_fire_kwargs(skip_weekends=False))
        mock_send.assert_called_once()

    def test_skips_when_today_in_skip_dates(self):
        xmas = datetime(2026, 12, 25, 10, 0)
        with _mock_now(xmas), \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            _fire(**_make_fire_kwargs(skip_dates={date(2026, 12, 25)}))
        mock_send.assert_not_called()

    def test_sends_when_today_not_in_skip_dates(self):
        tuesday = datetime(2026, 3, 3, 10, 0)
        with _mock_now(tuesday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi")) as mock_send:
            _fire(**_make_fire_kwargs(skip_dates={date(2026, 12, 25)}))
        mock_send.assert_called_once()

    def test_dry_run_forwarded_to_send_message(self):
        monday = datetime(2026, 3, 2, 9, 0)
        with _mock_now(monday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi")) as mock_send:
            _fire(**_make_fire_kwargs(dry_run=True))
        assert mock_send.call_args.kwargs["dry_run"] is True

    def test_logs_error_on_failed_send(self):
        monday = datetime(2026, 3, 2, 9, 0)
        with _mock_now(monday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=False, channel_id="C1", message="hi",
                                           error_code="channel_not_found")):
            # Should not raise, just log
            _fire(**_make_fire_kwargs())

    def test_skips_when_no_messages_configured(self):
        monday = datetime(2026, 3, 2, 9, 0)
        with _mock_now(monday), \
             patch("slack_scheduler.scheduler.send_message") as mock_send, \
             patch("slack_scheduler.scheduler.pick_message") as mock_pick:
            _fire(**_make_fire_kwargs(messages=[]))
        mock_pick.assert_not_called()
        mock_send.assert_not_called()

    def test_token_expired_shuts_down_scheduler(self):
        monday = datetime(2026, 3, 2, 9, 0)
        mock_scheduler = MagicMock()
        with _mock_now(monday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   side_effect=TokenExpiredError("expired")):
            _fire(**_make_fire_kwargs(scheduler=mock_scheduler))
        mock_scheduler.shutdown.assert_called_once_with(wait=False)

    def test_token_expired_does_not_raise(self):
        monday = datetime(2026, 3, 2, 9, 0)
        mock_scheduler = MagicMock()
        with _mock_now(monday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   side_effect=TokenExpiredError("expired")):
            # Should not raise
            _fire(**_make_fire_kwargs(scheduler=mock_scheduler))

    def test_token_expired_without_scheduler_does_not_raise(self):
        monday = datetime(2026, 3, 2, 9, 0)
        with _mock_now(monday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   side_effect=TokenExpiredError("expired")):
            # Should not raise even without scheduler
            _fire(**_make_fire_kwargs())

    def test_slack_api_error_does_not_raise(self):
        monday = datetime(2026, 3, 2, 9, 0)
        with _mock_now(monday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   side_effect=SlackAPIError("some_error")):
            # Should not raise
            _fire(**_make_fire_kwargs())

    def test_slack_api_error_does_not_shut_down_scheduler(self):
        monday = datetime(2026, 3, 2, 9, 0)
        mock_scheduler = MagicMock()
        with _mock_now(monday), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   side_effect=SlackAPIError("some_error")):
            _fire(**_make_fire_kwargs(scheduler=mock_scheduler))
        mock_scheduler.shutdown.assert_not_called()


# --- _fire: jitter cross-midnight handling -----------------------------------

class TestFireJitterCrossMidnight:
    """Verify that jitter pushing execution across a day boundary does not
    incorrectly trigger skip_weekends / skip_dates checks."""

    def test_jitter_cross_midnight_friday_to_saturday_not_skipped(self):
        """Friday 23:50 job with 15min jitter fires at Saturday 00:05.
        skip_weekends is True but the intended date is Friday, so it must send."""
        sat_00_05 = datetime(2026, 3, 7, 0, 5)  # Saturday 00:05
        with _mock_now(sat_00_05), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi", ts="1")) as mock_send:
            _fire(**_make_fire_kwargs(skip_weekends=True, jitter_minutes=15))
        mock_send.assert_called_once()

    def test_genuine_saturday_with_jitter_still_skipped(self):
        """Saturday 10:00 job with 15min jitter — 15 min before is still
        Saturday, so skip_weekends correctly skips."""
        sat_10_00 = datetime(2026, 3, 7, 10, 0)  # Saturday 10:00
        with _mock_now(sat_10_00), \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            _fire(**_make_fire_kwargs(skip_weekends=True, jitter_minutes=15))
        mock_send.assert_not_called()

    def test_jitter_cross_midnight_into_skip_date_not_skipped(self):
        """Job intended for March 2 (not a skip date) fires at March 3 00:05
        (a skip date). Must still send because March 2 is valid."""
        mar_3_00_05 = datetime(2026, 3, 3, 0, 5)  # March 3 00:05
        skip = {date(2026, 3, 3)}
        with _mock_now(mar_3_00_05), \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi", ts="1")) as mock_send:
            _fire(**_make_fire_kwargs(skip_dates=skip, jitter_minutes=15))
        mock_send.assert_called_once()

    def test_zero_jitter_preserves_original_behavior(self):
        """With jitter_minutes=0 on a Saturday, skip_weekends still works."""
        sat_10_00 = datetime(2026, 3, 7, 10, 0)
        with _mock_now(sat_10_00), \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            _fire(**_make_fire_kwargs(skip_weekends=True, jitter_minutes=0))
        mock_send.assert_not_called()

    def test_both_possible_dates_are_skip_dates(self):
        """If both the current date and the date jitter_minutes ago are in
        skip_dates, the message should be skipped."""
        # March 4 00:05, jitter=15 -> possible_dates = {March 4, March 3}
        mar_4_00_05 = datetime(2026, 3, 4, 0, 5)
        skip = {date(2026, 3, 3), date(2026, 3, 4)}
        with _mock_now(mar_4_00_05), \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            _fire(**_make_fire_kwargs(skip_dates=skip, jitter_minutes=15))
        mock_send.assert_not_called()

    def test_both_possible_dates_are_weekend_skipped(self):
        """Sunday 00:05 with 15min jitter — Saturday 23:50 would also be
        weekend, so both possible dates are weekends. Should skip."""
        sun_00_05 = datetime(2026, 3, 8, 0, 5)  # Sunday 00:05
        with _mock_now(sun_00_05), \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            _fire(**_make_fire_kwargs(skip_weekends=True, jitter_minutes=15))
        mock_send.assert_not_called()


# --- print_upcoming ----------------------------------------------------------

class TestPrintUpcoming:
    def test_empty_config_prints_no_schedules(self, capsys):
        config = AppConfig(channels=[])
        print_upcoming(config)
        assert "No schedules configured" in capsys.readouterr().out

    def test_prints_channel_name_and_cron(self, app_config, capsys):
        print_upcoming(app_config, count=1)
        out = capsys.readouterr().out
        assert "general" in out
        assert "0 9 * * 1-5" in out

    def test_prints_expected_count(self, app_config, capsys):
        print_upcoming(app_config, count=3)
        out = capsys.readouterr().out
        time_lines = [l for l in out.splitlines() if l.strip().startswith("- 20")]
        assert len(time_lines) == 3

    def test_skips_weekends(self, capsys):
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
            skip_weekends=True,
        )
        config = AppConfig(channels=[channel])
        print_upcoming(config, count=7)
        out = capsys.readouterr().out
        date_strs = re.findall(r"\d{4}-\d{2}-\d{2}", out)
        for ds in date_strs:
            dt = datetime.strptime(ds, "%Y-%m-%d")
            assert dt.weekday() < 5, f"{ds} is a weekend day"

    def test_global_skip_weekends(self, capsys):
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
        )
        config = AppConfig(channels=[channel], skip_weekends=True)
        print_upcoming(config, count=7)
        out = capsys.readouterr().out
        date_strs = re.findall(r"\d{4}-\d{2}-\d{2}", out)
        for ds in date_strs:
            dt = datetime.strptime(ds, "%Y-%m-%d")
            assert dt.weekday() < 5, f"{ds} is a weekend day"

    def test_skip_dates_excluded(self, capsys):
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
        )
        skip_date = "2026-03-04"
        config = AppConfig(
            channels=[channel], skip_dates=[skip_date],
        )
        print_upcoming(config, count=10)
        assert skip_date not in capsys.readouterr().out

    def test_jitter_label_shown(self, capsys):
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *", jitter_minutes=10)],
        )
        config = AppConfig(channels=[channel])
        print_upcoming(config, count=1)
        assert "10min jitter" in capsys.readouterr().out

    def test_no_jitter_label_when_zero(self, app_config, capsys):
        print_upcoming(app_config, count=1)
        assert "jitter" not in capsys.readouterr().out

    def test_skip_holidays_excluded(self, capsys):
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
        )
        config = AppConfig(channels=[channel], skip_holidays="US")
        print_upcoming(config, count=10)
        assert "2026-12-25" not in capsys.readouterr().out


class TestRunDaemonHolidays:
    def test_passes_holidays_to_resolve(self, credentials_obj):
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
            skip_holidays="NL",
        )
        config = AppConfig(channels=[channel], skip_holidays="US")
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched, \
             patch("slack_scheduler.scheduler.resolve_skip_dates") as mock_resolve:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            mock_resolve.return_value = set()
            run_daemon(config, credentials_obj)
        mock_resolve.assert_called_once_with(
            [], [], global_holidays="US", channel_holidays="NL",
        )


# --- skip_weekends inheritance / override ------------------------------------

class TestSkipWeekendsOverride:
    """Verify that per-channel skip_weekends can override the global setting."""

    def test_channel_none_inherits_global_true_in_run_daemon(self, credentials_obj):
        """Channel with skip_weekends=None inherits global True."""
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
            skip_weekends=None,
        )
        config = AppConfig(channels=[channel], skip_weekends=True)
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(config, credentials_obj)
        # skip_weekends is the 5th positional arg (index 4) passed to _fire
        args = instance.add_job.call_args.kwargs["args"]
        assert args[4] is True

    def test_channel_none_inherits_global_false_in_run_daemon(self, credentials_obj):
        """Channel with skip_weekends=None inherits global False."""
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
            skip_weekends=None,
        )
        config = AppConfig(channels=[channel], skip_weekends=False)
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(config, credentials_obj)
        args = instance.add_job.call_args.kwargs["args"]
        assert args[4] is False

    def test_channel_false_overrides_global_true_in_run_daemon(self, credentials_obj):
        """Channel with skip_weekends=False overrides global True."""
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
            skip_weekends=False,
        )
        config = AppConfig(channels=[channel], skip_weekends=True)
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(config, credentials_obj)
        args = instance.add_job.call_args.kwargs["args"]
        assert args[4] is False

    def test_channel_true_overrides_global_false_in_run_daemon(self, credentials_obj):
        """Channel with skip_weekends=True overrides global False."""
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
            skip_weekends=True,
        )
        config = AppConfig(channels=[channel], skip_weekends=False)
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            run_daemon(config, credentials_obj)
        args = instance.add_job.call_args.kwargs["args"]
        assert args[4] is True

    def test_channel_false_overrides_global_true_in_print_upcoming(self, capsys):
        """Channel with skip_weekends=False overrides global True — weekends appear."""
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
            skip_weekends=False,
        )
        config = AppConfig(channels=[channel], skip_weekends=True)
        print_upcoming(config, count=14)
        out = capsys.readouterr().out
        date_strs = re.findall(r"\d{4}-\d{2}-\d{2}", out)
        weekdays = {datetime.strptime(ds, "%Y-%m-%d").weekday() for ds in date_strs}
        assert any(wd >= 5 for wd in weekdays), "Expected weekends when channel overrides global"

    def test_channel_none_inherits_global_true_in_print_upcoming(self, capsys):
        """Channel with skip_weekends=None inherits global True — no weekends."""
        channel = ChannelConfig(
            id="C1", name="ch", messages=["hi"],
            schedules=[ScheduleConfig(cron="0 9 * * *")],
            skip_weekends=None,
        )
        config = AppConfig(channels=[channel], skip_weekends=True)
        print_upcoming(config, count=7)
        out = capsys.readouterr().out
        date_strs = re.findall(r"\d{4}-\d{2}-\d{2}", out)
        for ds in date_strs:
            dt = datetime.strptime(ds, "%Y-%m-%d")
            assert dt.weekday() < 5, f"{ds} is a weekend day"
