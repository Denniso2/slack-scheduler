"""Tests for slack_scheduler.templates"""
import logging
from datetime import datetime

import pytest

from slack_scheduler.templates import _SafeDict, render

FIXED_DT = datetime(2026, 3, 3, 9, 15, 0)  # Tuesday


class TestSafeDict:
    def test_returns_value_for_known_key(self):
        d = _SafeDict(foo="bar")
        assert d["foo"] == "bar"

    def test_returns_placeholder_for_missing_key(self):
        d = _SafeDict()
        assert d["missing"] == "{missing}"


class TestRender:
    def test_renders_date_variable(self):
        assert render("Today is {date}", now=FIXED_DT) == "Today is 2026-03-03"

    def test_renders_day_of_week_variable(self):
        assert render("Happy {day_of_week}!", now=FIXED_DT) == "Happy Tuesday!"

    def test_renders_time_variable(self):
        assert render("It is {time}", now=FIXED_DT) == "It is 09:15"

    def test_renders_multiple_variables(self):
        result = render("{day_of_week} {date} at {time}", now=FIXED_DT)
        assert result == "Tuesday 2026-03-03 at 09:15"

    def test_unknown_placeholder_preserved(self):
        assert render("Hello {name}!", now=FIXED_DT) == "Hello {name}!"

    def test_mixed_known_and_unknown_placeholders(self):
        result = render("{date} - {unknown}", now=FIXED_DT)
        assert result == "2026-03-03 - {unknown}"

    def test_no_placeholders_unchanged(self):
        assert render("Plain text", now=FIXED_DT) == "Plain text"

    def test_empty_string_returns_empty(self):
        assert render("", now=FIXED_DT) == ""

    def test_uses_current_time_when_now_is_none(self):
        result = render("{date}")
        assert len(result) == 10  # YYYY-MM-DD format

    def test_malformed_format_returns_template_as_is(self):
        bad = "Hello {name!badconv}"
        assert render(bad, now=FIXED_DT) == bad

    def test_malformed_format_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="slack_scheduler.templates"):
            render("Hello {name!badconv}", now=FIXED_DT)
        assert "Failed to render template" in caplog.text

    @pytest.mark.parametrize("template,expected_substr", [
        ("Morning! Today is {date}.", "2026-03-03"),
        ("{day_of_week} standup", "Tuesday"),
        ("Meeting at {time}", "09:15"),
    ])
    def test_parametrized_substitution(self, template, expected_substr):
        assert expected_substr in render(template, now=FIXED_DT)
