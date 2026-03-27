"""Tests for slack_scheduler.cli

cli.py uses deferred imports inside cmd_* functions, so we must patch at the
source module (e.g., slack_scheduler.config.load_credentials) rather than
slack_scheduler.cli.load_credentials.
"""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from slack_scheduler.auth import TokenExpiredError, TokenInvalidError
from slack_scheduler.cli import cmd_init, cmd_run, cmd_send, cmd_status, cmd_trigger, cmd_validate, main
from slack_scheduler.config import AppConfig, ChannelConfig, ScheduleConfig
from slack_scheduler.sender import SendResult, SlackAPIError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_args(**kwargs) -> SimpleNamespace:
    defaults = dict(
        config=Path("/nonexistent/config.yaml"),
        env=Path("/nonexistent/credentials.env"),
        dry_run=False,
        verbose=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# Patch targets for deferred imports used by cmd_* functions
P_LOAD_CREDS = "slack_scheduler.config.load_credentials"
P_LOAD_CONFIG = "slack_scheduler.config.load_config"
P_VALIDATE = "slack_scheduler.auth.validate_credentials"
P_SEND = "slack_scheduler.sender.send_message"
P_RENDER = "slack_scheduler.templates.render"
P_PICK = "slack_scheduler.selector.pick_message"
P_RUN_DAEMON = "slack_scheduler.scheduler.run_daemon"
P_PRINT_UPCOMING = "slack_scheduler.scheduler.print_upcoming"
P_SLEEP = "time.sleep"


# ---------------------------------------------------------------------------
# cmd_init
# ---------------------------------------------------------------------------

class TestCmdInit:
    def test_creates_directories(self, tmp_path):
        with patch("slack_scheduler.cli.paths.config_dir", return_value=tmp_path / "config"), \
             patch("slack_scheduler.cli.paths.data_dir", return_value=tmp_path / "data"), \
             patch("slack_scheduler.cli.paths.log_dir", return_value=tmp_path / "logs"):
            cmd_init(make_args())
        assert (tmp_path / "config").is_dir()
        assert (tmp_path / "data").is_dir()
        assert (tmp_path / "logs").is_dir()

    def test_writes_credentials_template(self, tmp_path, capsys):
        with patch("slack_scheduler.cli.paths.config_dir", return_value=tmp_path / "cfg"), \
             patch("slack_scheduler.cli.paths.data_dir", return_value=tmp_path / "data"), \
             patch("slack_scheduler.cli.paths.log_dir", return_value=tmp_path / "logs"):
            cmd_init(make_args())
        content = (tmp_path / "data" / "credentials.env").read_text()
        assert "SLACK_XOXC_TOKEN" in content
        assert "SLACK_D_COOKIE" in content

    def test_skips_existing_credentials(self, tmp_path, capsys):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "credentials.env").write_text("existing")
        with patch("slack_scheduler.cli.paths.config_dir", return_value=tmp_path / "cfg"), \
             patch("slack_scheduler.cli.paths.data_dir", return_value=data_dir), \
             patch("slack_scheduler.cli.paths.log_dir", return_value=tmp_path / "logs"):
            cmd_init(make_args())
        assert (data_dir / "credentials.env").read_text() == "existing"
        assert "already exists" in capsys.readouterr().out

    def test_prints_path_summary(self, tmp_path, capsys):
        with patch("slack_scheduler.cli.paths.config_dir", return_value=tmp_path / "cfg"), \
             patch("slack_scheduler.cli.paths.data_dir", return_value=tmp_path / "data"), \
             patch("slack_scheduler.cli.paths.log_dir", return_value=tmp_path / "logs"):
            cmd_init(make_args())
        assert "Paths:" in capsys.readouterr().out

    def test_chmod_called_on_non_windows(self, tmp_path):
        with patch("slack_scheduler.cli.paths.config_dir", return_value=tmp_path / "cfg"), \
             patch("slack_scheduler.cli.paths.data_dir", return_value=tmp_path / "data"), \
             patch("slack_scheduler.cli.paths.log_dir", return_value=tmp_path / "logs"), \
             patch("slack_scheduler.cli.platform.system", return_value="Linux"):
            cmd_init(make_args())
        assert (tmp_path / "data" / "credentials.env").exists()

    def test_chmod_skipped_on_windows(self, tmp_path):
        with patch("slack_scheduler.cli.paths.config_dir", return_value=tmp_path / "cfg"), \
             patch("slack_scheduler.cli.paths.data_dir", return_value=tmp_path / "data"), \
             patch("slack_scheduler.cli.paths.log_dir", return_value=tmp_path / "logs"), \
             patch("slack_scheduler.cli.platform.system", return_value="Windows"):
            cmd_init(make_args())
        assert (tmp_path / "data" / "credentials.env").exists()


# ---------------------------------------------------------------------------
# cmd_send
# ---------------------------------------------------------------------------

class TestCmdSend:
    def test_sends_cli_message(self, tmp_path, capsys):
        mock_result = SendResult(ok=True, channel_id="C1", message="hello", ts="1")
        args = make_args(
            channel="C1", message=["hello"],
            jitter=0, selection_mode=None,
            env=tmp_path / "creds.env", config=tmp_path / "missing.yaml",
        )
        with patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m):
            cmd_send(args)
        assert "Message sent" in capsys.readouterr().out

    def test_jitter_calls_sleep(self, tmp_path):
        mock_result = SendResult(ok=True, channel_id="C1", message="hi")
        args = make_args(
            channel="C1", message=["hi"],
            jitter=5, selection_mode=None,
            env=tmp_path / "creds.env", config=tmp_path / "missing.yaml",
        )
        with patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             patch(P_SLEEP) as mock_sleep:
            cmd_send(args)
        mock_sleep.assert_called_once()

    def test_zero_jitter_no_sleep(self, tmp_path):
        mock_result = SendResult(ok=True, channel_id="C1", message="hi")
        args = make_args(
            channel="C1", message=["hi"],
            jitter=0, selection_mode=None,
            env=tmp_path / "creds.env", config=tmp_path / "missing.yaml",
        )
        with patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             patch(P_SLEEP) as mock_sleep:
            cmd_send(args)
        mock_sleep.assert_not_called()

    def test_failed_send_exits_1(self, tmp_path):
        mock_result = SendResult(ok=False, channel_id="C1", message="hi",
                                 error_code="channel_not_found")
        args = make_args(
            channel="C1", message=["hi"],
            jitter=0, selection_mode=None,
            env=tmp_path / "creds.env", config=tmp_path / "missing.yaml",
        )
        with patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             pytest.raises(SystemExit) as exc_info:
            cmd_send(args)
        assert exc_info.value.code == 1

    def test_cycle_mode_with_cli_messages(self, tmp_path, capsys):
        mock_result = SendResult(ok=True, channel_id="C1", message="a", ts="1")
        args = make_args(
            channel="C1", message=["a", "b", "c"],
            jitter=0, selection_mode="cycle",
            env=tmp_path / "creds.env", config=tmp_path / "missing.yaml",
        )
        with patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             patch(P_PICK, return_value="a") as mock_pick:
            cmd_send(args)
        mock_pick.assert_called_once_with("C1", ["a", "b", "c"], "cycle")
        assert "Message sent" in capsys.readouterr().out

    def test_dry_run_does_not_require_credentials(self, tmp_path, capsys):
        mock_result = SendResult(ok=True, channel_id="C1", message="hello")
        args = make_args(
            channel="C1", message=["hello"],
            jitter=0, selection_mode=None,
            env=tmp_path / "missing.env", config=tmp_path / "missing.yaml",
            dry_run=True,
        )
        with patch(P_VALIDATE) as mock_validate, \
             patch(P_SEND, return_value=mock_result) as mock_send, \
             patch(P_RENDER, side_effect=lambda m, *a: m):
            cmd_send(args)
        mock_validate.assert_not_called()
        assert mock_send.call_args.kwargs["dry_run"] is True
        assert "Message sent" in capsys.readouterr().out



# ---------------------------------------------------------------------------
# cmd_trigger
# ---------------------------------------------------------------------------

class TestCmdTrigger:
    def _make_config(self, **channel_overrides):
        channel_defaults = dict(
            id="C1", name="standup",
            messages=["Good morning!", "Rise and shine!"],
            schedules=[ScheduleConfig(cron="0 9 * * 1-5")],
            selection_mode="random",
        )
        channel_defaults.update(channel_overrides)
        return AppConfig(channels=[ChannelConfig(**channel_defaults)])

    def test_sends_config_message(self, capsys):
        config = self._make_config()
        mock_result = SendResult(ok=True, channel_id="C1", message="Good morning!", ts="1")
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=False)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_SEND, return_value=mock_result) as mock_send, \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             patch("random.choice", return_value="Good morning!"):
            cmd_trigger(args)
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["channel_id"] == "C1"
        assert "Triggered standup" in capsys.readouterr().out

    def test_unknown_name_exits_1(self):
        config = self._make_config()
        args = make_args(name="nonexistent", message=None, jitter=0, selection_mode=None, respect_skips=False)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             pytest.raises(SystemExit) as exc_info:
            cmd_trigger(args)
        assert exc_info.value.code == 1

    def test_message_override(self, capsys):
        config = self._make_config()
        mock_result = SendResult(ok=True, channel_id="C1", message="override", ts="1")
        args = make_args(name="standup", message=["override"], jitter=0, selection_mode=None, respect_skips=False)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m):
            cmd_trigger(args)
        assert "override" in capsys.readouterr().out

    def test_selection_mode_override(self, capsys):
        config = self._make_config(selection_mode="random")
        mock_result = SendResult(ok=True, channel_id="C1", message="a", ts="1")
        args = make_args(name="standup", message=None, jitter=0, selection_mode="cycle", respect_skips=False)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_PICK, return_value="a") as mock_pick, \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m):
            cmd_trigger(args)
        mock_pick.assert_called_once_with("standup", ["Good morning!", "Rise and shine!"], "cycle")

    def test_jitter_calls_sleep(self):
        config = self._make_config()
        mock_result = SendResult(ok=True, channel_id="C1", message="hi", ts="1")
        args = make_args(name="standup", message=None, jitter=5, selection_mode=None, respect_skips=False)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_PICK, return_value="hi"), \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             patch(P_SLEEP) as mock_sleep:
            cmd_trigger(args)
        mock_sleep.assert_called_once()

    def test_zero_jitter_no_sleep(self):
        config = self._make_config()
        mock_result = SendResult(ok=True, channel_id="C1", message="hi", ts="1")
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=False)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_PICK, return_value="hi"), \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             patch(P_SLEEP) as mock_sleep:
            cmd_trigger(args)
        mock_sleep.assert_not_called()

    def test_failed_send_exits_1(self):
        config = self._make_config()
        mock_result = SendResult(ok=False, channel_id="C1", message="hi",
                                 error_code="channel_not_found")
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=False)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_PICK, return_value="hi"), \
             patch(P_SEND, return_value=mock_result), \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             pytest.raises(SystemExit) as exc_info:
            cmd_trigger(args)
        assert exc_info.value.code == 1

    def test_no_messages_exits_1(self):
        config = self._make_config(messages=[])
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=False)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             pytest.raises(SystemExit) as exc_info:
            cmd_trigger(args)
        assert exc_info.value.code == 1

    def test_dry_run_forwarded(self, capsys):
        config = self._make_config()
        mock_result = SendResult(ok=True, channel_id="C1", message="hi", ts="1")
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=False, dry_run=True)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_PICK, return_value="hi"), \
             patch(P_SEND, return_value=mock_result) as mock_send, \
             patch(P_RENDER, side_effect=lambda m, *a: m):
            cmd_trigger(args)
        assert mock_send.call_args.kwargs["dry_run"] is True

    def test_respect_skips_skips_weekend(self):
        config = self._make_config(skip_weekends=True)
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=True)
        saturday = date(2026, 3, 7)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch("datetime.date", wraps=date) as mock_date, \
             patch(P_SEND) as mock_send:
            mock_date.today.return_value = saturday
            cmd_trigger(args)
        mock_send.assert_not_called()

    def test_respect_skips_skips_date(self):
        config = self._make_config(skip_dates=["2026-03-05"])
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=True)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch("datetime.date", wraps=date) as mock_date, \
             patch(P_SEND) as mock_send:
            mock_date.today.return_value = date(2026, 3, 5)
            cmd_trigger(args)
        mock_send.assert_not_called()

    def test_respect_skips_sends_on_normal_day(self, capsys):
        config = self._make_config(skip_weekends=True)
        mock_result = SendResult(ok=True, channel_id="C1", message="hi", ts="1")
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=True)
        monday = date(2026, 3, 2)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch("datetime.date", wraps=date) as mock_date, \
             patch(P_PICK, return_value="hi"), \
             patch(P_SEND, return_value=mock_result) as mock_send, \
             patch(P_RENDER, side_effect=lambda m, *a: m):
            mock_date.today.return_value = monday
            cmd_trigger(args)
        mock_send.assert_called_once()

    def test_no_respect_skips_ignores_weekend(self, capsys):
        config = self._make_config(skip_weekends=True)
        mock_result = SendResult(ok=True, channel_id="C1", message="hi", ts="1")
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=False)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_PICK, return_value="hi"), \
             patch(P_SEND, return_value=mock_result) as mock_send, \
             patch(P_RENDER, side_effect=lambda m, *a: m):
            cmd_trigger(args)
        mock_send.assert_called_once()

    def test_respect_skips_global_skip_weekends(self):
        config = self._make_config()
        config.skip_weekends = True
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=True)
        saturday = date(2026, 3, 7)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch("datetime.date", wraps=date) as mock_date, \
             patch(P_SEND) as mock_send:
            mock_date.today.return_value = saturday
            cmd_trigger(args)
        mock_send.assert_not_called()

    def test_dry_run_does_not_require_credentials(self, tmp_path, capsys):
        config = self._make_config()
        mock_result = SendResult(ok=True, channel_id="C1", message="Good morning!", ts="1")
        args = make_args(
            name="standup", message=None, jitter=0, selection_mode=None,
            respect_skips=False, dry_run=True, env=tmp_path / "missing.env",
        )
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_VALIDATE) as mock_validate, \
             patch(P_SEND, return_value=mock_result) as mock_send, \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             patch("random.choice", return_value="Good morning!"):
            cmd_trigger(args)
        mock_validate.assert_not_called()
        assert mock_send.call_args.kwargs["dry_run"] is True
        assert "Triggered standup" in capsys.readouterr().out

    def test_respect_skips_channel_false_overrides_global_true(self, capsys):
        """Channel skip_weekends=False overrides global True — sends on weekend."""
        config = self._make_config(skip_weekends=False)
        config.skip_weekends = True
        mock_result = SendResult(ok=True, channel_id="C1", message="hi", ts="1")
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=True)
        saturday = date(2026, 3, 7)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch("datetime.date", wraps=date) as mock_date, \
             patch(P_PICK, return_value="hi"), \
             patch(P_SEND, return_value=mock_result) as mock_send, \
             patch(P_RENDER, side_effect=lambda m, *a: m):
            mock_date.today.return_value = saturday
            cmd_trigger(args)
        mock_send.assert_called_once()

    def test_respect_skips_channel_none_inherits_global_true(self):
        """Channel skip_weekends=None inherits global True — skips on weekend."""
        config = self._make_config()  # channel skip_weekends defaults to None
        config.skip_weekends = True
        args = make_args(name="standup", message=None, jitter=0, selection_mode=None, respect_skips=True)
        saturday = date(2026, 3, 7)
        with patch(P_LOAD_CONFIG, return_value=config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch("datetime.date", wraps=date) as mock_date, \
             patch(P_SEND) as mock_send:
            mock_date.today.return_value = saturday
            cmd_trigger(args)
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_run
# ---------------------------------------------------------------------------

class TestCmdRun:
    def test_skip_holidays_overrides_config(self, tmp_path):
        args = make_args(
            config=tmp_path / "config.yaml",
            env=tmp_path / "creds.env",
            skip_holidays="US",
        )
        mock_config = AppConfig(channels=[])
        with patch(P_LOAD_CONFIG, return_value=mock_config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_RUN_DAEMON):
            cmd_run(args)
        assert mock_config.skip_holidays == "US"

    def test_skip_holidays_none_leaves_config(self, tmp_path):
        args = make_args(
            config=tmp_path / "config.yaml",
            env=tmp_path / "creds.env",
            skip_holidays=None,
        )
        mock_config = AppConfig(channels=[], skip_holidays="NL")
        with patch(P_LOAD_CONFIG, return_value=mock_config), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_RUN_DAEMON):
            cmd_run(args)
        assert mock_config.skip_holidays == "NL"

    def test_skip_holidays_invalid_raises(self, tmp_path):
        args = make_args(
            config=tmp_path / "config.yaml",
            env=tmp_path / "creds.env",
            skip_holidays="XX",
        )
        with patch(P_LOAD_CONFIG, return_value=AppConfig(channels=[])), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             pytest.raises(ValueError, match="not recognized"):
            cmd_run(args)


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

class TestCmdStatus:
    def test_calls_print_upcoming_with_count(self):
        args = make_args(config=Path("/fake"), count=3, skip_holidays=None)
        mock_config = MagicMock()
        with patch(P_LOAD_CONFIG, return_value=mock_config), \
             patch(P_PRINT_UPCOMING) as mock_upcoming:
            cmd_status(args)
        mock_upcoming.assert_called_once_with(mock_config, count=3)

    def test_skip_holidays_overrides_config(self):
        args = make_args(config=Path("/fake"), count=5, skip_holidays="NL")
        mock_config = AppConfig(channels=[])
        with patch(P_LOAD_CONFIG, return_value=mock_config), \
             patch(P_PRINT_UPCOMING):
            cmd_status(args)
        assert mock_config.skip_holidays == "NL"

    def test_skip_holidays_invalid_raises(self):
        args = make_args(config=Path("/fake"), count=5, skip_holidays="XX")
        with patch(P_LOAD_CONFIG, return_value=AppConfig(channels=[])), \
             pytest.raises(ValueError, match="not recognized"):
            cmd_status(args)


# ---------------------------------------------------------------------------
# cmd_validate
# ---------------------------------------------------------------------------

class TestCmdValidate:
    def test_prints_valid_on_success(self, tmp_path, capsys):
        args = make_args(env=tmp_path / "creds.env", config=tmp_path / "config.yaml")
        with patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE):
            cmd_validate(args)
        assert "valid" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------

class TestMainIntegration:
    def test_no_command_exits_1(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["slack-scheduler"])
        with patch("slack_scheduler.cli.setup_logging"), \
             pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_token_expired_exits_1(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", [
            "slack-scheduler",
            "--env", str(tmp_path / "creds.env"),
            "validate",
        ])
        with patch("slack_scheduler.cli.setup_logging"), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE, side_effect=TokenExpiredError("expired")), \
             pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_keyboard_interrupt_exits_0(self, monkeypatch, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text('channels: []\n')
        monkeypatch.setattr(sys, "argv", [
            "slack-scheduler",
            "--config", str(config_file),
            "--env", str(tmp_path / "creds.env"),
            "run",
        ])
        with patch("slack_scheduler.cli.setup_logging"), \
             patch(P_LOAD_CONFIG,
                   return_value=AppConfig(channels=[])), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_RUN_DAEMON, side_effect=KeyboardInterrupt), \
             pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_slack_api_error_exits_1(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", [
            "slack-scheduler",
            "--config", str(tmp_path / "config.yaml"),
            "--env", str(tmp_path / "creds.env"),
            "send", "--channel", "C1", "--message", "hi",
        ])
        with patch("slack_scheduler.cli.setup_logging"), \
             patch(P_LOAD_CREDS, return_value=MagicMock()), \
             patch(P_VALIDATE), \
             patch(P_SEND, side_effect=SlackAPIError("channel_not_found")), \
             patch(P_RENDER, side_effect=lambda m, *a: m), \
             pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_value_error_exits_1(self, monkeypatch, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")  # empty -> ValueError
        monkeypatch.setattr(sys, "argv", [
            "slack-scheduler",
            "--config", str(config_file),
            "--env", str(tmp_path / "creds.env"),
            "status",
        ])
        with patch("slack_scheduler.cli.setup_logging"), \
             pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
