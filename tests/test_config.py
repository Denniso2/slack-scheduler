"""Tests for slack_scheduler.config"""
import textwrap
from datetime import date
from pathlib import Path

import pytest

from slack_scheduler.config import (
    AppConfig,
    ScheduleConfig,
    _validate_skip_dates,
    load_config,
    load_credentials,
    resolve_skip_dates,
)


# --- _validate_skip_dates ---------------------------------------------------

class TestValidateSkipDates:
    def test_valid_dates_returned_unchanged(self):
        dates = ["2026-12-25", "2026-01-01"]
        assert _validate_skip_dates(dates, "ctx") == dates

    def test_empty_list_is_valid(self):
        assert _validate_skip_dates([], "ctx") == []

    @pytest.mark.parametrize("bad_date", [
        "25-12-2026",
        "2026/12/25",
        "not-a-date",
        "2026-13-01",
        "",
    ])
    def test_invalid_format_raises_value_error(self, bad_date):
        with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
            _validate_skip_dates([bad_date], "ctx")

    def test_error_message_contains_context(self):
        with pytest.raises(ValueError, match="my context"):
            _validate_skip_dates(["bad"], "my context")


# --- resolve_skip_dates ------------------------------------------------------

class TestResolveSkipDates:
    def test_combines_global_and_schedule_dates(self):
        result = resolve_skip_dates(["2026-12-25"], ["2026-07-04"])
        assert date(2026, 12, 25) in result
        assert date(2026, 7, 4) in result

    def test_deduplicates_overlapping_dates(self):
        result = resolve_skip_dates(["2026-12-25"], ["2026-12-25"])
        assert len(result) == 1

    def test_empty_inputs_return_empty_set(self):
        assert resolve_skip_dates([], []) == set()

    def test_returns_set_of_date_objects(self):
        result = resolve_skip_dates(["2026-01-01"], [])
        assert all(isinstance(d, date) for d in result)


# --- load_credentials --------------------------------------------------------

class TestLoadCredentials:
    def test_loads_valid_env_file(self, mock_creds_env):
        creds = load_credentials(mock_creds_env)
        assert creds.xoxc_token == "xoxc-test-token-abc123"
        assert creds.d_cookie == "xoxd-test-cookie-def456"

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_credentials(tmp_path / "missing.env")

    def test_empty_values_raise_value_error(self, empty_creds_env):
        with pytest.raises(ValueError, match="SLACK_XOXC_TOKEN"):
            load_credentials(empty_creds_env)

    def test_missing_token_key_raises_value_error(self, tmp_path):
        f = tmp_path / "creds.env"
        f.write_text("SLACK_D_COOKIE=xoxd-abc\n")
        with pytest.raises(ValueError):
            load_credentials(f)

    def test_missing_cookie_key_raises_value_error(self, tmp_path):
        f = tmp_path / "creds.env"
        f.write_text("SLACK_XOXC_TOKEN=xoxc-abc\n")
        with pytest.raises(ValueError):
            load_credentials(f)

    def test_empty_file_raises_value_error(self, tmp_path):
        f = tmp_path / "creds.env"
        f.write_text("")
        with pytest.raises(ValueError):
            load_credentials(f)


# --- load_config: happy path -------------------------------------------------

class TestLoadConfigHappyPath:
    def test_loads_minimal_config(self, minimal_config_file):
        cfg = load_config(minimal_config_file)
        assert len(cfg.channels) == 1

    def test_loads_full_config(self, full_config_file):
        cfg = load_config(full_config_file)
        assert len(cfg.channels) == 2
        assert cfg.default_selection_mode == "cycle"

    def test_channel_fields_parsed(self, minimal_config_file):
        ch = load_config(minimal_config_file).channels[0]
        assert ch.id == "C111"
        assert ch.name == "general"
        assert ch.messages == ["Hello!"]

    def test_schedule_fields_parsed(self, minimal_config_file):
        s = load_config(minimal_config_file).channels[0].schedules[0]
        assert isinstance(s, ScheduleConfig)
        assert s.cron == "0 9 * * 1-5"
        assert s.jitter_minutes == 0
        assert s.skip_weekends is False

    def test_global_skip_dates_parsed(self, full_config_file):
        cfg = load_config(full_config_file)
        assert "2026-12-25" in cfg.skip_dates

    def test_schedule_skip_dates_parsed(self, full_config_file):
        cfg = load_config(full_config_file)
        assert "2026-07-04" in cfg.channels[0].schedules[0].skip_dates

    def test_channel_name_defaults_to_id(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(textwrap.dedent("""\
            channels:
              - id: "C999"
                messages: ["hi"]
                schedules:
                  - cron: "0 9 * * *"
        """))
        assert load_config(p).channels[0].name == "C999"

    def test_selection_mode_inherits_from_default(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(textwrap.dedent("""\
            default_selection_mode: "cycle"
            channels:
              - id: "C111"
                messages: ["hi"]
                schedules:
                  - cron: "0 9 * * *"
        """))
        assert load_config(p).channels[0].selection_mode == "cycle"

    def test_no_channels_key_returns_empty_list(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text('default_selection_mode: "random"\n')
        assert load_config(p).channels == []

    def test_default_selection_mode_defaults_to_random(self, minimal_config_file):
        assert load_config(minimal_config_file).default_selection_mode == "random"


# --- load_config: validation errors -----------------------------------------

class TestLoadConfigValidation:
    def _write(self, tmp_path, text):
        p = tmp_path / "config.yaml"
        p.write_text(textwrap.dedent(text))
        return p

    def test_empty_file_raises(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_config(p)

    def test_invalid_default_selection_mode_raises(self, tmp_path):
        p = self._write(tmp_path, """\
            default_selection_mode: "weekly"
            channels: []
        """)
        with pytest.raises(ValueError, match="default_selection_mode"):
            load_config(p)

    def test_channel_missing_id_raises(self, tmp_path):
        p = self._write(tmp_path, """\
            channels:
              - name: "oops"
                messages: ["hi"]
                schedules:
                  - cron: "0 9 * * *"
        """)
        with pytest.raises(ValueError, match="missing required field 'id'"):
            load_config(p)

    def test_schedule_missing_cron_raises(self, tmp_path):
        p = self._write(tmp_path, """\
            channels:
              - id: "C111"
                messages: ["hi"]
                schedules:
                  - skip_weekends: true
        """)
        with pytest.raises(ValueError, match="missing required field 'cron'"):
            load_config(p)

    def test_invalid_channel_selection_mode_raises(self, tmp_path):
        p = self._write(tmp_path, """\
            channels:
              - id: "C111"
                selection_mode: "bogus"
                messages: ["hi"]
                schedules:
                  - cron: "0 9 * * *"
        """)
        with pytest.raises(ValueError, match="invalid selection_mode"):
            load_config(p)

    def test_invalid_global_skip_date_raises(self, tmp_path):
        p = self._write(tmp_path, """\
            skip_dates:
              - "25/12/2026"
            channels: []
        """)
        with pytest.raises(ValueError, match="global skip_dates"):
            load_config(p)

    def test_invalid_schedule_skip_date_raises(self, tmp_path):
        p = self._write(tmp_path, """\
            channels:
              - id: "C111"
                messages: ["hi"]
                schedules:
                  - cron: "0 9 * * *"
                    skip_dates:
                      - "not-a-date"
        """)
        with pytest.raises(ValueError, match="skip_dates"):
            load_config(p)


# --- dataclass default isolation --------------------------------------------

class TestDataclassDefaults:
    def test_schedule_config_skip_dates_not_shared(self):
        a = ScheduleConfig(cron="0 9 * * *")
        b = ScheduleConfig(cron="0 9 * * *")
        a.skip_dates.append("2026-01-01")
        assert b.skip_dates == []

    def test_app_config_skip_dates_not_shared(self):
        a = AppConfig(channels=[])
        b = AppConfig(channels=[])
        a.skip_dates.append("2026-01-01")
        assert b.skip_dates == []
