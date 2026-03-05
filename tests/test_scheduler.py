"""Tests for slack_scheduler.scheduler"""
import re
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from slack_scheduler.config import AppConfig, ChannelConfig, ScheduleConfig
from slack_scheduler.scheduler import _fire, print_upcoming, run_daemon
from slack_scheduler.sender import SendResult


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
        assert instance.add_job.call_args.kwargs["id"] == "C111_0"

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


class TestFire:
    def test_sends_on_normal_weekday(self):
        monday = date(2026, 3, 2)
        with patch("slack_scheduler.scheduler.date", side_effect=date, today=MagicMock()) as mock_date, \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi", ts="1")) as mock_send:
            mock_date.today.return_value = monday
            _fire(**_make_fire_kwargs())
        mock_send.assert_called_once()

    def test_skips_saturday_when_skip_weekends(self):
        saturday = date(2026, 3, 7)
        with patch("slack_scheduler.scheduler.date", side_effect=date, today=MagicMock()) as mock_date, \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            mock_date.today.return_value = saturday
            _fire(**_make_fire_kwargs(skip_weekends=True))
        mock_send.assert_not_called()

    def test_skips_sunday_when_skip_weekends(self):
        sunday = date(2026, 3, 8)
        with patch("slack_scheduler.scheduler.date", side_effect=date, today=MagicMock()) as mock_date, \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            mock_date.today.return_value = sunday
            _fire(**_make_fire_kwargs(skip_weekends=True))
        mock_send.assert_not_called()

    def test_sends_on_weekend_when_skip_weekends_false(self):
        saturday = date(2026, 3, 7)
        with patch("slack_scheduler.scheduler.date", side_effect=date, today=MagicMock()) as mock_date, \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi")) as mock_send:
            mock_date.today.return_value = saturday
            _fire(**_make_fire_kwargs(skip_weekends=False))
        mock_send.assert_called_once()

    def test_skips_when_today_in_skip_dates(self):
        today = date(2026, 12, 25)
        with patch("slack_scheduler.scheduler.date", side_effect=date, today=MagicMock()) as mock_date, \
             patch("slack_scheduler.scheduler.send_message") as mock_send:
            mock_date.today.return_value = today
            _fire(**_make_fire_kwargs(skip_dates={today}))
        mock_send.assert_not_called()

    def test_sends_when_today_not_in_skip_dates(self):
        today = date(2026, 3, 3)
        with patch("slack_scheduler.scheduler.date", side_effect=date, today=MagicMock()) as mock_date, \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi")) as mock_send:
            mock_date.today.return_value = today
            _fire(**_make_fire_kwargs(skip_dates={date(2026, 12, 25)}))
        mock_send.assert_called_once()

    def test_dry_run_forwarded_to_send_message(self):
        monday = date(2026, 3, 2)
        with patch("slack_scheduler.scheduler.date", side_effect=date, today=MagicMock()) as mock_date, \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=True, channel_id="C1", message="hi")) as mock_send:
            mock_date.today.return_value = monday
            _fire(**_make_fire_kwargs(dry_run=True))
        assert mock_send.call_args.kwargs["dry_run"] is True

    def test_logs_error_on_failed_send(self):
        monday = date(2026, 3, 2)
        with patch("slack_scheduler.scheduler.date", side_effect=date, today=MagicMock()) as mock_date, \
             patch("slack_scheduler.scheduler.pick_message", return_value="hi"), \
             patch("slack_scheduler.scheduler.render", return_value="hi"), \
             patch("slack_scheduler.scheduler.send_message",
                   return_value=SendResult(ok=False, channel_id="C1", message="hi",
                                           error_code="channel_not_found")):
            mock_date.today.return_value = monday
            # Should not raise, just log
            _fire(**_make_fire_kwargs())


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
            schedules=[ScheduleConfig(cron="0 9 * * *", skip_weekends=True)],
        )
        config = AppConfig(channels=[channel])
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
            schedules=[ScheduleConfig(cron="0 9 * * *", skip_holidays="NL")],
        )
        config = AppConfig(channels=[channel], skip_holidays="US")
        with patch("slack_scheduler.scheduler.BlockingScheduler") as MockSched, \
             patch("slack_scheduler.scheduler.resolve_skip_dates") as mock_resolve:
            instance = MockSched.return_value
            instance.get_jobs.return_value = [MagicMock()]
            mock_resolve.return_value = set()
            run_daemon(config, credentials_obj)
        mock_resolve.assert_called_once_with(
            [], [], global_holidays="US", schedule_holidays="NL",
        )
